"""Continuous Silero state and actual WhisperMel speech inputs, one or two host ORT libraries."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import platform
import sys
import wave

import numpy as np
from ort_client import OrtRunner, compare, summary
from prepared_probe import read_inputs

WAV_SHA = "8bfb42c963e623ebab31b81ff4404867d07d3102507c87ac14577c4c61663b8c"
MODEL_SHA = {
    "silero_vad.onnx": "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
    "smart-turn-v3.2-cpu.onnx": "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same_inputs(left, right):
    return list(left) == list(right) and all(
        left[name].shape == right[name].shape and left[name].dtype == right[name].dtype
        and left[name].tobytes() == right[name].tobytes() for name in left)


class VadState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.input = np.zeros((1, 576), np.float32)
        self.state = np.zeros((2, 1, 128), np.float32)
        self.used = 0
        self.probability = np.float32(0)

    def tensors(self):
        return {"input": self.input, "state": self.state, "sr": np.array(16000, np.int64)}

    def accept_result(self, result):
        assert result["stateN"].shape == self.state.shape
        assert result["output"].shape == (1, 1)
        assert all(np.isfinite(value).all() for value in result.values())
        self.state = result["stateN"].copy()
        self.input[0, :64] = self.input[0, 512:576]
        self.used = 0
        self.probability = result["output"][0, 0]


def run_silero(runners, pcm):
    report = {"warmup": {}, "scenarios": []}
    warmup = VadState().tensors()
    warm_values = {side: runner.run(warmup) for side, runner in runners.items()}
    report["warmup"] = {side: {name: summary(value) for name, value in outputs.items()}
                        for side, outputs in warm_values.items()}
    if "right" in runners:
        report["warmupComparison"] = {name: compare(warm_values["left"][name], warm_values["right"][name])
                                      for name in warm_values["left"]}
    for scenario, mute in [("unmuted", range(0)), ("mute-frames-100-to-109", range(100, 110))]:
        state = {side: VadState() for side in runners}
        row = {"name": scenario, "frames": len(pcm) // 320, "mutedFrames": len(mute),
               "harnessResetOnEachMutedFrame": True, "runs": [], "frameOutputs": [], "framesWithoutRun": 0}
        for frame_number, frame in enumerate(pcm.reshape(-1, 320)):
            if frame_number in mute:
                for current in state.values():
                    current.reset()
                row["frameOutputs"].append({"frame": frame_number, "muted": True})
                continue
            offset = 0
            frame_runs = 0
            while offset < len(frame):
                used = state["left"].used
                count = min(512 - used, len(frame) - offset)
                values = frame[offset:offset + count].astype(np.float32) / np.float32(32768)
                for current in state.values():
                    assert current.used == used
                    current.input[0, 64 + used:64 + used + count] = values
                    current.used += count
                offset += count
                if state["left"].used == 512:
                    inputs = {side: current.tensors() for side, current in state.items()}
                    outputs = {side: runners[side].run(tensors) for side, tensors in inputs.items()}
                    record = {"run": len(row["runs"]), "endingPcmFrame": frame_number,
                              "throughFrameSample": offset,
                              "inputs": {side: {name: summary(value) for name, value in tensors.items()}
                                         for side, tensors in inputs.items()},
                              "outputs": {side: {name: summary(value) for name, value in result.items()}
                                          for side, result in outputs.items()}}
                    if "right" in runners:
                        record["sameInputs"] = same_inputs(inputs["left"], inputs["right"])
                        record["comparison"] = {name: compare(outputs["left"][name], outputs["right"][name])
                                                for name in outputs["left"]}
                    row["runs"].append(record)
                    for side, result in outputs.items():
                        state[side].accept_result(result)
                    frame_runs += 1
            if not frame_runs:
                row["framesWithoutRun"] += 1
            row["frameOutputs"].append({"frame": frame_number, "muted": False,
                                        "probability": {side: float(current.probability) for side, current in state.items()}})
        row["runCount"] = len(row["runs"])
        row["residualNewSamples"] = state["left"].used
        row["probabilityRange"] = {}
        for side in runners:
            probabilities = [frame["probability"][side] for frame in row["frameOutputs"] if not frame["muted"]]
            row["probabilityRange"][side] = {"min": min(probabilities), "max": max(probabilities),
                                                "framesAtLeastHalf": sum(p >= 0.5 for p in probabilities)}
        report["scenarios"].append(row)
        print(json.dumps({"silero": scenario, "runCount": row["runCount"],
                          "residual": row["residualNewSamples"], "probabilityRange": row["probabilityRange"]}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--left-library", type=Path, required=True)
    parser.add_argument("--right-library", type=Path)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--smart-cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    assert digest(a.wav) == WAV_SHA
    for name, expected in MODEL_SHA.items():
        assert digest(a.models / name) == expected
    with wave.open(str(a.wav)) as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes(), audio.getcomptype()) == (16000, 1, 2, 81600, "NONE")
        original = np.frombuffer(audio.readframes(audio.getnframes()), "<i2").copy()
    pcm = np.concatenate([original, np.zeros(41600, np.int16), original])
    assert len(pcm) == 204800
    libraries = {"left": a.left_library}
    if a.right_library:
        libraries["right"] = a.right_library
    report = {"scope": "host C API numeric input research; no candidate if only left library is supplied",
              "python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
              "wavSha256": WAV_SHA, "pcmSha256": hashlib.sha256(pcm.tobytes()).hexdigest(),
              "inputPattern": "5.1s public speech + 2.6s silence + same 5.1s speech; no resampling",
              "models": MODEL_SHA, "libraries": {side: digest(path) for side, path in libraries.items()},
              "threads": [1, 1], "optimization": "ORT_ENABLE_ALL", "execution": "sequential",
              "ORT_LOAD_CONFIG_FROM_MODEL": "0", "smartTurn": []}
    with ExitStack() as stack:
        runners = {side: stack.enter_context(OrtRunner(a.runner, path, a.models / "silero_vad.onnx",
                    a.output / f"silero-{side}-stderr.txt", threads=1)) for side, path in libraries.items()}
        report["silero"] = run_silero(runners, pcm)
    with ExitStack() as stack:
        runners = {side: stack.enter_context(OrtRunner(a.runner, path, a.models / "smart-turn-v3.2-cpu.onnx",
                    a.output / f"smart-{side}-stderr.txt", threads=1)) for side, path in libraries.items()}
        for case in ["spoken-1s", "spoken-5p1s", "joined-full-8s", "joined-wrap-9s"]:
            inputs = read_inputs(a.smart_cases / case / "input.tsv")
            outputs = {side: runner.run(inputs) for side, runner in runners.items()}
            record = {"case": case, "inputs": {name: summary(value) for name, value in inputs.items()},
                      "outputs": {side: {name: summary(value) for name, value in result.items()} for side, result in outputs.items()},
                      "probability": {side: float(result["logits"][0, 0]) for side, result in outputs.items()}}
            assert all(np.isfinite(result["logits"]).all() for result in outputs.values())
            record["atLeastHalf"] = {side: value >= 0.5 for side, value in record["probability"].items()}
            if "right" in runners:
                record["comparison"] = compare(outputs["left"]["logits"], outputs["right"]["logits"])
            report["smartTurn"].append(record)
            print(json.dumps({"smartTurn": case, "probability": record["probability"]}), flush=True)
    report["sourceIdentity"] = {name: digest(Path(__file__).with_name(name)) for name in ["speech_probe.py", "ort_client.py", "ort_runner.cc", "prepared_probe.py"]}
    (a.output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"done": True, "report": str(a.output / "result.json")}))


if __name__ == "__main__":
    main()
