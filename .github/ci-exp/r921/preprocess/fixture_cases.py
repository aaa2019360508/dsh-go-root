"""Produce private synthetic/text inputs, exercise the Kotlin entry point, and print digests only."""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("classpath")
    parser.add_argument("vocab", type=Path)
    parser.add_argument("new_private_directory", type=Path)
    a = parser.parse_args()
    base = a.new_private_directory.absolute()
    base.mkdir(mode=0o700)
    assert sha(a.vocab.read_bytes()) == "3d09c84ebd10306706a79a8276b3ab736a40d8ec03251c7639f4e52c3a1a4f8e"
    cases = {"sampleRate": 16000, "mel": [], "bge": []}

    def run(*args):
        subprocess.run(["java", "-cp", a.classpath, "PrepareInputsKt", *map(str, args)], check=True)

    synth = base / "synthetic.pcm16le"
    # Deterministic integer waveform, no speech or identity attached.
    synthetic_samples = [((i * 109 + i // 97) % 65536) - 32768 for i in range(144000)]
    synth.write_bytes(struct.pack(f"<{len(synthetic_samples)}h", *synthetic_samples))
    silence = base / "silence.pcm16le"
    silence.write_bytes(bytes(16000 * 2))
    for name, source, end in [("silence-short", silence, 16000), ("synthetic-short", synth, 16000),
                              ("synthetic-full", synth, 128000), ("synthetic-wrap", synth, 144000)]:
        out = base / name
        run("mel", source, end, out)
        raw = (out / "input_features.f32le").read_bytes()
        assert len(raw) == 80 * 800 * 4
        values = struct.unpack("<64000f", raw)
        if source == silence:
            assert min(values) == max(values) == -1.5
        else:
            assert min(values) < max(values)
        cases["mel"].append(dict(case=name, sourceSha256=sha(source.read_bytes()), endSampleExclusive=end,
                                 keptSamples=min(end, 128000), leftPadded=max(0, 128000 - end), shape=[1, 80, 800],
                                 bytes=len(raw), sha256=sha(raw), minimum=min(values), maximum=max(values)))

    sentence = "今天在公园见面。"
    examples = [("empty-doc", "", "document"), ("same-doc", sentence, "document"), ("same-query", sentence, "query"),
                ("mixed-doc", "中文 A9, Hello! 🧩 [MASK][UNK] [SEP] [CLS] [PAD]", "document"),
                ("long-doc", "中" * 512, "document")]
    for name, text, mode in examples:
        out = base / name
        source = base / (name + ".txt")
        source.write_text(text, encoding="utf-8")
        run("bge", a.vocab, source, mode, out)
        tensors = {}
        for field in ["input_ids", "attention_mask", "token_type_ids"]:
            raw = (out / (field + ".i64le")).read_bytes()
            values = [v for (v,) in struct.iter_unpack("<q", raw)]
            if field == "input_ids":
                t = len(values)
                assert values[0] == 101 and values[-1] == 102
                if name == "empty-doc": assert values == [101, 102]
                if name == "long-doc": assert t == 512 and len(set(values[1:-1])) == 1
                if name == "mixed-doc": assert values.count(100) >= 2 and set([0, 100, 101, 102, 103]).issubset(values)
            elif field == "attention_mask": assert len(values) == t and set(values) == {1}
            else: assert len(values) == t and set(values) == {0}
            tensors[field] = dict(bytes=len(raw), sha256=sha(raw))
        cases["bge"].append(dict(case=name, mode=mode, text=text if name != "long-doc" else "repeat U+4E2D 512 times",
                                 textSha256=sha(source.read_bytes()), shape=[1, t], tensors=tensors))
    rows = {c["case"]: c for c in cases["bge"]}
    assert rows["same-query"]["shape"][1] > rows["same-doc"]["shape"][1]
    assert len({v["sha256"] for v in cases["mel"]}) == 4
    print(json.dumps(cases, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
