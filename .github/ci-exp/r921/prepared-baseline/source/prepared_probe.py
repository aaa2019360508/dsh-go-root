"""Run actual Kotlin-prepared BGE/SmartTurn inputs through one or two pinned ORT libraries.

No wall-time assertions, allowed error tolerance, or Android equivalence is assumed.
Raw tensors are private temporary data; only identities and numeric summaries are saved.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
import platform
import sys

import numpy as np
from ort_client import OrtRunner, compare, summary

EXPECTED_MODELS = {
    "model_quantized.onnx": "99a6e522710c00220c89f8c52e0cc5aa09d4cbb1c34c0e932eab3a9dfdc65df3",
    "model_quantized.onnx_data": "952623481ca8beea884e3d3c9ecaf8a3c7bf1d0c21de29e970cd31af9d37a90b",
    "smart-turn-v3.2-cpu.onnx": "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f",
}
GROUPS = {
    "bge": ("model_quantized.onnx", ["empty-doc", "same-doc", "same-query", "mixed-doc", "long-doc"]),
    "smartTurn": ("smart-turn-v3.2-cpu.onnx", ["silence-short", "synthetic-short", "synthetic-full", "synthetic-wrap"]),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_inputs(manifest):
    result = {}
    for line in manifest.read_text().splitlines():
        name, dtype, dimensions, path = line.split("\t")
        shape = () if dimensions == "scalar" else tuple(map(int, dimensions.split(",")))
        result[name] = np.fromfile(path, dtype={"float32": "<f4", "int64": "<i8"}[dtype]).reshape(shape)
    return result


def normalize_cls(hidden):
    cls = hidden[0, 0, :]
    assert cls.shape == (512,) and np.isfinite(cls).all()
    squared = 0.0
    for value in cls:
        squared += float(value) * float(value)
    assert math.isfinite(squared) and squared > 0
    norm = math.sqrt(squared)
    return np.array([float(value) / norm for value in cls], dtype=np.float64)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--left-library", type=Path, required=True)
    parser.add_argument("--right-library", type=Path)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    model_identity = {}
    for name, digest in EXPECTED_MODELS.items():
        path = a.models / name
        actual = sha(path)
        assert actual == digest, name
        model_identity[name] = {"bytes": path.stat().st_size, "sha256": actual}
    libraries = {"left": a.left_library}
    if a.right_library:
        libraries["right"] = a.right_library
    report = {
        "scope": "host C API runs; complete baseline only" if len(libraries) == 1 else "same-input host C API library comparison",
        "platform": platform.platform(), "machine": platform.machine(), "python": sys.version,
        "numpy": np.__version__, "libraries": {key: {"sha256": sha(path), "bytes": path.stat().st_size} for key, path in libraries.items()},
        "modelIdentity": model_identity, "threads": {"intra": 1, "inter": 1},
        "execution": "sequential", "optimization": "ORT_ENABLE_ALL", "ORT_LOAD_CONFIG_FROM_MODEL": "0",
        "cases": [], "bgeSimilarity": {},
    }
    embeddings = {key: {} for key in libraries}
    for group, (model, cases) in GROUPS.items():
        with ExitStack() as stack:
            runners = {key: stack.enter_context(OrtRunner(a.runner, path, a.models / model,
                        a.output / f"{group}-{key}-stderr.txt", threads=1)) for key, path in libraries.items()}
            for case in cases:
                inputs = read_inputs(a.cases / case / "input.tsv")
                values = {key: runner.run(inputs) for key, runner in runners.items()}
                row = {"model": group, "case": case, "inputs": {name: summary(value) for name, value in inputs.items()},
                       "outputs": {key: {name: summary(value) for name, value in output.items()} for key, output in values.items()}}
                for output in values.values():
                    assert all(np.isfinite(value).all() for value in output.values())
                if group == "bge":
                    t = inputs["input_ids"].shape[1]
                    for key, output in values.items():
                        assert output["last_hidden_state"].shape == (1, t, 512)
                        embeddings[key][case] = normalize_cls(output["last_hidden_state"])
                    row["normalizedCls"] = {key: summary(embeddings[key][case]) for key in libraries}
                else:
                    row["probability"] = {key: float(output["logits"][0, 0]) for key, output in values.items()}
                    row["atLeastHalf"] = {key: probability >= 0.5 for key, probability in row["probability"].items()}
                if "right" in values:
                    assert list(values["left"]) == list(values["right"])
                    row["comparison"] = {name: compare(values["left"][name], values["right"][name]) for name in values["left"]}
                    if group == "bge":
                        row["normalizedClsComparison"] = compare(embeddings["left"][case], embeddings["right"][case])
                report["cases"].append(row)
                print(json.dumps({"model": group, "case": case, "finite": True,
                                  "compared": "comparison" in row}), flush=True)
    for key, vectors in embeddings.items():
        query = vectors["same-query"]
        scores = {}
        for name in ["empty-doc", "same-doc", "mixed-doc", "long-doc"]:
            value = 0.0
            for x, y in zip(query, vectors[name]):
                value += float(x) * float(y)
            scores[name] = value
        report["bgeSimilarity"][key] = {"scores": scores, "descending": sorted(scores, key=scores.get, reverse=True)}
    if "right" in libraries:
        report["allRawOutputsBitwiseEqual"] = all(
            c["bitwiseEqual"] for row in report["cases"] for c in row["comparison"].values())
        report["sameBgeOrder"] = report["bgeSimilarity"]["left"]["descending"] == report["bgeSimilarity"]["right"]["descending"]
    report["sourceIdentity"] = {name: sha(Path(__file__).with_name(name)) for name in ["prepared_probe.py", "ort_client.py", "ort_runner.cc"]}
    (a.output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"cases": len(report["cases"]), "libraries": list(libraries), "report": str(a.output / "result.json")}))


if __name__ == "__main__":
    main()
