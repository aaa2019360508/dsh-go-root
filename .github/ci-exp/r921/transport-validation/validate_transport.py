"""One real Silero warm-up, C API versus the same complete ORT Python release.

This validates the harness and scalar/state transport. It does not run a reduced
candidate, model speech, or an Android execution provider.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

import numpy as np
from ort_client import OrtRunner, compare, summary

parser = argparse.ArgumentParser()
parser.add_argument("--runner", required=True, type=Path)
parser.add_argument("--library", required=True, type=Path)
parser.add_argument("--model", required=True, type=Path)
parser.add_argument("--python-site", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
sys.path.insert(0, str(args.python_site.resolve()))
import onnxruntime as ort

args.output.mkdir(parents=True, exist_ok=False)
model_sha = hashlib.sha256(args.model.read_bytes()).hexdigest()
assert model_sha == "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
options = ort.SessionOptions()
options.intra_op_num_threads = options.inter_op_num_threads = 1
options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
inputs = {
    "input": np.zeros((1, 576), dtype=np.float32),
    "state": np.zeros((2, 1, 128), dtype=np.float32),
    "sr": np.array(16000, dtype=np.int64),
}
with OrtRunner(args.runner, args.library, args.model, args.output / "runner-stderr.txt") as runner:
    actual = runner.run(inputs)
    ready = runner.ready
session = ort.InferenceSession(str(args.model.resolve()), options, providers=["CPUExecutionProvider"])
expected = dict(zip([item.name for item in session.get_outputs()], session.run(None, inputs)))
result = {
    "purpose": "transport validation only; one real product Silero zero warm-up",
    "python": sys.version, "machine": platform.machine(), "platform": platform.platform(),
    "numpy": np.__version__, "ortPythonVersion": ort.__version__,
    "ortBuildInfo": ort.get_build_info(), "cApiReady": ready,
    "modelSha256": model_sha,
    "librarySha256": hashlib.sha256(args.library.read_bytes()).hexdigest(),
    "runnerSourceSha256": hashlib.sha256(Path(__file__).with_name("ort_runner.cc").read_bytes()).hexdigest(),
    "inputs": {name: summary(value) for name, value in inputs.items()},
    "outputs": {name: compare(actual[name], expected[name]) for name in expected},
}
result["allBitwiseEqual"] = all(item["bitwiseEqual"] for item in result["outputs"].values())
(args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"allBitwiseEqual": result["allBitwiseEqual"], "outputs": {
    name: {"shape": item["left"]["shape"], "bytes": item["left"]["bytes"],
           "finite": item["left"]["finite"], "maxAbsFinite": item["maxAbsFinite"]}
    for name, item in result["outputs"].items()
}}, ensure_ascii=False))
if not result["allBitwiseEqual"]:
    raise SystemExit(1)
