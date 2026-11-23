"""Exercise the locked Zipformer graphs with real PCM in persistent ORT C API sessions."""
import argparse
from collections import Counter
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from tempfile import TemporaryDirectory
import wave
import zipfile

import numpy as np
from ort_client import OrtRunner, compare

FILES = {
    "encoder": "8fa764187a261844f859d7143ebaa563af5d10adfece4c18a8f414c88cba2a9b",
    "decoder": "1a70c593d71e53f023f5f55b0b4cfff5055abb786ee3992e5f63dc2e273cc4fa",
    "joiner": "1ed689c5ed19dbaa725d9d191bb4822b5f4855a39e1ffd28cbc1f340d25b2ee0",
}
AUDIO_HASH = "8bfb42c963e623ebab31b81ff4404867d07d3102507c87ac14577c4c61663b8c"
TOKEN_HASH = "a8e0e4ec53810e433789b54a5c0134a7eaa2ffca595a6334d54c00da858841d3"
WHEEL_HASH = "f16e74372fe9e20abb4183f98a8e2288d5ee4c48d04d94b6160311170e007661"


def file_hash(path):
    import hashlib
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(path, expected):
    if file_hash(path) != expected:
        raise ValueError(f"SHA-256 mismatch: {path.name}")


def input_frames(wav_path):
    with wave.open(str(wav_path)) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes(),
                wav.getcomptype()) != (1, 2, 16000, 81600, "NONE"):
            raise ValueError("expected the fixed mono PCM16 speech sample")
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), "<i2").astype(np.float32) / np.float32(32768)
    silence = np.zeros(320, dtype=np.float32)
    for frame in pcm.reshape(-1, 320):
        yield "speech1", frame
    for _ in range(130):
        yield "interveningSilence", silence
    for frame in pcm.reshape(-1, 320):
        yield "speech2", frame


def new_fbank(knf):
    opts = knf.FbankOptions()
    frame = opts.frame_opts
    frame.samp_freq, frame.frame_length_ms, frame.frame_shift_ms = 16000, 25, 10
    frame.dither, frame.snip_edges = 0., False
    frame.remove_dc_offset, frame.preemph_coeff = True, 0.97
    frame.window_type, frame.round_to_power_of_two = "povey", True
    mel = opts.mel_opts
    mel.num_bins, mel.low_freq, mel.high_freq, mel.is_librosa = 80, 20., -400., False
    return knf.OnlineFbank(opts)


def initial_states():
    states = {}
    for group in ["len", "avg", "key", "val", "val2", "conv1", "conv2"]:
        for i, (layers, context) in enumerate(zip([2, 4, 3, 2, 4], [64, 32, 16, 8, 32])):
            shape = {
                "len": (layers, 1), "avg": (layers, 1, 384),
                "key": (layers, context, 1, 192), "val": (layers, context, 1, 96),
                "val2": (layers, context, 1, 96),
                "conv1": (layers, 1, 384, 30), "conv2": (layers, 1, 384, 30),
            }[group]
            states[f"cached_{group}_{i}"] = np.zeros(shape, np.int64 if group == "len" else np.float32)
    return states


def check_shape(value, dtype, shape):
    if value.dtype != dtype or value.shape != shape:
        raise ValueError((value.dtype, value.shape, dtype, shape))


def encode_record(h, description):
    h.update(json.dumps(description, sort_keys=True, separators=(",", ":")).encode() + b"\n")


class DecoderSide:
    def __init__(self, runners, unk):
        self.runners = runners
        self.unk = unk
        self.state = initial_states()
        self.context = [-1, 0]
        self.cache = None
        self.segment_tokens = []
        self.processed = 0
        self.trailing_blanks = 0
        self.counts = Counter()
        self.endpoints = []
        self.decisions = sha256()
        self.output_hashes = {key: sha256() for key in runners}
        self.min_margin = None

    def call(self, role, key, inputs, trace):
        outputs = self.runners[role].run(inputs)
        for name, array in outputs.items():
            if not np.isfinite(array).all():
                raise ArithmeticError(f"non-finite {role}.{name} at {key}")
            encode_record(self.output_hashes[role], [key, name, array.dtype.str, array.shape,
                                                     sha256(array.tobytes()).hexdigest()])
        trace[(role, key)] = (inputs, outputs)
        self.counts[role + "Runs"] += 1
        return outputs

    def decoder(self, key, trace):
        result = self.call("decoder", key, {"y": np.array([self.context], np.int64)}, trace)
        self.cache = result["decoder_out"]
        check_shape(self.cache, np.float32, (1, 512))

    def block(self, features):
        trace = {}
        inputs = {"x": features, **self.state}
        result = self.call("encoder", "chunk", inputs, trace)
        if set(result) != {"encoder_out", *("new_" + name for name in self.state)}:
            raise ValueError("unexpected encoder outputs")
        for name, previous in self.state.items():
            check_shape(result["new_" + name], previous.dtype, previous.shape)
        self.state = {name: result["new_" + name] for name in self.state}
        self.processed += 32
        encoder = result["encoder_out"]
        if encoder.dtype != np.float32 or encoder.ndim != 3 or encoder.shape[::2] != (1, 512):
            raise ValueError("unexpected encoder output shape")
        if self.cache is None:
            self.decoder("start", trace)
        else:
            self.counts["blocksUsingPriorDecoderOut"] += 1
        for i in range(encoder.shape[1]):
            args = {"encoder_out": encoder[:, i, :], "decoder_out": self.cache}
            logits = self.call("joiner", f"frame-{i}", args, trace)["logit"]
            check_shape(logits, np.float32, (1, 6254))
            values = logits[0]
            token = int(np.argmax(values))
            top = np.partition(values, -2)[-2:]
            margin = float(top[1]) - float(top[0])
            self.min_margin = margin if self.min_margin is None else min(self.min_margin, margin)
            encode_record(self.decisions, [self.counts["encoderRuns"], i, token])
            if token in (0, self.unk):
                self.counts["blank" if token == 0 else "unk"] += 1
                self.trailing_blanks += 1
            else:
                self.counts["emitted"] += 1
                self.segment_tokens.append(token)
                self.context = [self.context[-1], token]
                self.trailing_blanks = 0
                self.decoder(f"emit-{i}", trace)
        return trace

    def check_endpoint(self, delivered_frame, pcm_stage):
        # endpoint.cc multiplies float counters by 0.01f. The greedy model
        # counts blanks after 4x subsampling and processed on the fbank grid.
        length = np.float32(self.processed) * np.float32(.01)
        quiet = np.float32(self.trailing_blanks * 4) * np.float32(.01)
        rule = (1 if quiet >= np.float32(2.4) else
                2 if length > quiet and quiet >= np.float32(1.) else
                3 if length >= np.float32(110.) else 0)
        if not rule:
            return
        # Sherpa Reset keeps last context only when tokens.size()>2,
        # resets result/cache, leaves encoder states and feature stream alive.
        had_words = bool(self.segment_tokens)
        self.endpoints.append({
            "afterPcmFrame": delivered_frame, "inputPhase": pcm_stage, "rule": rule,
            "processedFeatureFrames": self.processed, "trailingBlanks": self.trailing_blanks,
            "segmentTokenCount": len(self.segment_tokens), "segmentTokenSha256":
                sha256(np.asarray(self.segment_tokens, dtype="<i8").tobytes()).hexdigest(),
            "restartContext": self.context.copy() if had_words else [-1, 0],
        })
        if not had_words:
            self.context = [-1, 0]
        self.processed = self.trailing_blanks = 0
        self.segment_tokens = []
        self.cache = None

    def report(self):
        return {
            "runs": dict(self.counts), "argmaxSequenceSha256": self.decisions.hexdigest(),
            "outputTraceSha256": {k: v.hexdigest() for k, v in self.output_hashes.items()},
            "minimumJoinerTop2Margin": self.min_margin, "endpoints": self.endpoints,
            "tokenCountAtFinalStop": len(self.segment_tokens),
            "finalStopTokenSha256": sha256(np.asarray(self.segment_tokens, dtype="<i8").tobytes()).hexdigest(),
        }


class PairEvidence:
    def __init__(self):
        self.counts = Counter()
        self.first = {}
        self.metrics = {}
        self.input_exceptions = []

    def block(self, block_id, left, right):
        # Match on the encoder block and local frame, never on call ordinal:
        # either independent side may emit or reset when the other does not.
        for key in dict.fromkeys([*left, *right]):
            role, event = key
            place = dict(block=block_id, role=role, event=event)
            if key not in left or key not in right:
                label = "candidateOnly" if key not in left else "baselineOnly"
                self.counts[label] += 1
                self.first.setdefault(label, place)
                self.input_exceptions.append({**place, "kind": label})
                continue
            ai, ao = left[key]
            bi, bo = right[key]
            differing_inputs = [
                name for name in dict.fromkeys([*ai, *bi])
                if name not in ai or name not in bi or ai[name].dtype != bi[name].dtype
                or ai[name].shape != bi[name].shape or ai[name].tobytes() != bi[name].tobytes()
            ]
            same_inputs = not differing_inputs
            label = "equalInputs" if same_inputs else "differentInputs"
            self.counts[role + "." + label] += 1
            if not same_inputs:
                self.first.setdefault("differentInputs", place)
                self.input_exceptions.append({**place, "kind": label, "differingInputs": differing_inputs})
            if ao.keys() != bo.keys():
                raise ValueError("output name sets differ")
            for name, a in ao.items():
                b = bo[name]
                metric = self.metrics.setdefault(f"{role}.{label}.{name}", {
                    "observations": 0, "bitwiseDifferent": 0, "maxAbsFinite": 0.0})
                metric["observations"] += 1
                if a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes():
                    continue
                detail = compare(a, b)
                metric["bitwiseDifferent"] += 1
                self.first.setdefault(label + "DifferentOutput", {**place, "name": name, "comparison": detail})
                if detail.get("maxAbsFinite") is not None:
                    metric["maxAbsFinite"] = max(metric["maxAbsFinite"], detail["maxAbsFinite"])


def probe(args, knf, unk, models):
    fbank = new_fbank(knf)
    sides = {}
    comparison = PairEvidence()
    window_hash = sha256()
    consumed = blocks = delivered = 0
    with ExitStack() as stack:
        for label, lib in [("baseline", args.library), ("candidate", args.candidate)]:
            if lib is None:
                continue
            runners = {role: stack.enter_context(OrtRunner(args.runner, lib, path,
                       args.out / f"{label}-{role}.stderr.txt", threads=2)) for role, path in models.items()}
            sides[label] = DecoderSide(runners, unk)
        def decode_ready():
            nonlocal consumed, blocks
            while consumed + 39 < fbank.num_frames_ready:
                x = np.stack([fbank.get_frame(i) for i in range(consumed, consumed + 39)])[None, :, :]
                check_shape(x, np.float32, (1, 39, 80))
                window_hash.update(x.tobytes())
                traces = [s.block(x) for s in sides.values()]
                if len(traces) == 2:
                    comparison.block(blocks, *traces)
                consumed += 32
                blocks += 1

        for stage, frame in input_frames(args.wav):
            fbank.accept_waveform(16000, frame.tolist())
            delivered += 1
            decode_ready()
            for side in sides.values():
                side.check_endpoint(delivered, stage)
        before_finish = blocks
        # Dart _SherpaDecoder.finish calls acceptWaveform(4800 zeros),
        # inputFinished(), then _decode(). It does not re-check endpoint here.
        fbank.accept_waveform(16000, [0.] * 4800)
        fbank.input_finished()
        decode_ready()
        reports = {key: side.report() for key, side in sides.items()}
        if any(side.counts["encoderRuns"] < 2 or not side.counts["emitted"] or not side.counts["blank"]
               for side in sides.values()):
            raise ValueError("sample did not cover repeated encoder chunks, actual emission and blank")
        run_identity = {k: {role: runner.ready for role, runner in v.runners.items()} for k, v in sides.items()}
    return {
        "scope": "raw 3-graph CPU C API runs, fixed fbank and greedy token decisions; no Sherpa UI/text rendering or Android execution",
        "host": platform.platform(), "python": sys.version, "numpy": np.__version__,
        "capi": run_identity, "intraAndInterThreadsRequested": [2, 2],
        "runnerSha256": file_hash(args.runner), "libraries": {k: file_hash(lib) for k, lib in
            [("baseline", args.library), ("candidate", args.candidate)] if lib is not None},
        "modelSha256": FILES, "audioSha256": AUDIO_HASH, "wheelSha256": WHEEL_HASH, "tokensSha256": TOKEN_HASH,
        "fbankPcmFrames": delivered, "inputPattern": "same 255 PCM frames, 130 silence, same 255 PCM frames",
        "windowBytesSha256": window_hash.hexdigest(), "blocksBeforeFinish": before_finish,
        "blocksAfterFinish": blocks - before_finish, "finalReadyFbankFrames": fbank.num_frames_ready,
        "sides": reports,
        "pair": {"counts": dict(comparison.counts), "first": comparison.first,
                 "inputExceptions": comparison.input_exceptions,
                 "outputMetrics": comparison.metrics} if args.candidate else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("runner", "library", "models", "wav", "tokens", "wheel", "out"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    verify(args.wav, AUDIO_HASH)
    verify(args.tokens, TOKEN_HASH)
    verify(args.wheel, WHEEL_HASH)
    models = {k: args.models / f"{k}-epoch-99-avg-1.int8.onnx" for k in FILES}
    for key, path in models.items():
        verify(path, FILES[key])
    vocab = {s: int(i) for s, i in (line.rsplit(maxsplit=1) for line in
             args.tokens.read_text(encoding="utf-8").splitlines())}
    if vocab["<blk>"] != 0:
        raise ValueError("expected blank=0")
    args.out.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(prefix="zipformer-fixed-fbank-") as directory:
        with zipfile.ZipFile(args.wheel) as archive:
            archive.extractall(directory)
        sys.path.insert(0, directory)
        import kaldi_native_fbank as knf
        report = probe(args, knf, vocab["<unk>"], models)
    (args.out / "result.json").write_text(json.dumps(report, indent=2, ensure_ascii=False,
                                                     allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
