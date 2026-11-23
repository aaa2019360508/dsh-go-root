"""Create private SmartTurn inputs for four defined positions in the pinned 16 kHz WAV."""
import argparse
import hashlib
import json
import math
import struct
import subprocess
import wave
from pathlib import Path

WAV_SHA256 = "8bfb42c963e623ebab31b81ff4404867d07d3102507c87ac14577c4c61663b8c"
RATE = 16000
WINDOW = 8 * RATE


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("classpath")
    parser.add_argument("wav", type=Path)
    parser.add_argument("new_private_directory", type=Path)
    args = parser.parse_args()
    if sha(args.wav.read_bytes()) != WAV_SHA256:
        raise ValueError("WAV SHA-256 differs")
    with wave.open(str(args.wav), "rb") as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth(),
                stream.getnframes(), stream.getcomptype()) != (RATE, 1, 2, 81600, "NONE"):
            raise ValueError("Unexpected WAV parameters")
        frames = stream.readframes(stream.getnframes())
    if len(frames) != 81600 * 2:
        raise ValueError("Short PCM payload")
    pause = bytes(41600 * 2)
    joined = frames + pause + frames
    base = args.new_private_directory.absolute()
    base.mkdir(mode=0o700)
    original = base / "original.pcm16le"
    synthetic = base / "joined.pcm16le"
    original.write_bytes(frames)
    synthetic.write_bytes(joined)

    result = {"wavSha256": WAV_SHA256, "format": "mono PCM16LE", "rateHz": RATE,
              "original": {"samples": len(frames) // 2, "sha256": sha(frames)},
              "joined": {"samples": len(joined) // 2, "sha256": sha(joined),
                         "segments": [{"source": "original", "samples": 81600},
                                      {"source": "inserted-zero", "samples": 41600},
                                      {"source": "original", "samples": 81600}]}, "cases": []}
    for name, path, end in [("spoken-1s", original, 16000), ("spoken-5p1s", original, 81600),
                            ("joined-full-8s", synthetic, 128000), ("joined-wrap-9s", synthetic, 144000)]:
        out = base / name
        subprocess.run(["java", "-cp", args.classpath, "PrepareInputsKt", "mel", str(path),
                        str(end), str(out)], check=True)
        raw = (out / "input_features.f32le").read_bytes()
        if len(raw) != 80 * 800 * 4:
            raise ValueError(f"{name}: tensor byte count differs")
        values = [value for (value,) in struct.iter_unpack("<f", raw)]
        if not all(map(math.isfinite, values)) or min(values) == max(values):
            raise ValueError(f"{name}: invalid speech features")
        result["cases"].append({"case": name, "source": "original" if path == original else "joined",
                                "endSampleExclusive": end, "firstSourceSample": max(0, end - WINDOW),
                                "sourceSamplesKept": min(end, WINDOW), "leftPaddingSamples": max(0, WINDOW - end),
                                "input": "input_features", "shape": [1, 80, 800], "dtype": "float32le",
                                "bytes": len(raw), "sha256": sha(raw), "minimum": min(values), "maximum": max(values)})
    if len({row["sha256"] for row in result["cases"]}) != 4:
        raise ValueError("Unexpected identical features across windows")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
