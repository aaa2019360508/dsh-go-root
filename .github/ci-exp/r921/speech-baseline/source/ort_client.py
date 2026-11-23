"""Private tensor transport for the fixed C API runner; reports contain summaries only."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np


class OrtRunner:
    def __init__(self, executable: Path, library: Path, model: Path, log: Path, threads: int = 1):
        self.log = log.open("wb")
        self.process = subprocess.Popen(
            [str(executable.resolve()), str(library.resolve()), str(model.resolve()), str(threads)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
            text=True, bufsize=1, env={**os.environ, "ORT_LOAD_CONFIG_FROM_MODEL": "0"},
        )
        self.ready = self.process.stdout.readline().rstrip("\n").split("\t")
        if len(self.ready) != 3 or self.ready[0] != "ready":
            self.close()
            raise RuntimeError(f"session initialization failed; see {log}")

    def run(self, inputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        with tempfile.TemporaryDirectory(prefix="ort-private-tensors-") as temporary:
            root = Path(temporary)
            rows = []
            for index, (name, value) in enumerate(inputs.items()):
                value = np.asarray(value)
                if value.dtype.kind == "f" and value.dtype.itemsize == 4:
                    value = value.astype("<f4", copy=False)
                    dtype = "float32"
                elif value.dtype.kind == "i" and value.dtype.itemsize == 8:
                    value = value.astype("<i8", copy=False)
                    dtype = "int64"
                else:
                    raise TypeError((name, value.dtype))
                shape = ",".join(map(str, value.shape)) if value.ndim else "scalar"
                path = root / f"input-{index}.bin"
                path.write_bytes(value.tobytes(order="C"))
                rows.append(f"{name}\t{dtype}\t{shape}\t{path}\n")
            manifest = root / "inputs.tsv"
            manifest.write_text("".join(rows))
            output = root / "out"
            self.process.stdin.write(f"{manifest}\t{output}\n")
            self.process.stdin.flush()
            reply = self.process.stdout.readline().rstrip("\n").split("\t")
            if len(reply) != 2 or reply[0] != "ok":
                raise RuntimeError(f"ORT Run failed: {reply}; see stderr log")
            result = {}
            for row in Path(reply[1]).read_text().splitlines():
                name, dtype, dimensions, path = row.split("\t")
                shape = () if dimensions == "scalar" else tuple(map(int, dimensions.split(",")))
                values = np.fromfile(path, dtype={"float32": "<f4", "int64": "<i8"}[dtype])
                result[name] = values.reshape(shape)
            return result

    def close(self):
        process = self.process
        if process.poll() is None:
            try:
                process.stdin.write("quit\n")
                process.stdin.flush()
            except BrokenPipeError:
                pass
        code = process.wait()
        process.stdin.close()
        process.stdout.close()
        self.log.close()
        return code

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        code = self.close()
        if kind is None and code:
            raise RuntimeError(f"ORT runner exited with {code}")


def summary(value: np.ndarray) -> dict:
    data = value.tobytes(order="C")
    finite = np.isfinite(value)
    return {
        "shape": list(value.shape), "dtype": value.dtype.str,
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "finite": int(finite.sum()), "elements": int(value.size),
        "min": float(value[finite].min()) if finite.any() else None,
        "max": float(value[finite].max()) if finite.any() else None,
    }


def compare(left: np.ndarray, right: np.ndarray) -> dict:
    same_shape_type = left.shape == right.shape and left.dtype == right.dtype
    result = {"sameShapeType": same_shape_type, "left": summary(left), "right": summary(right)}
    if same_shape_type:
        result["bitwiseEqual"] = left.tobytes() == right.tobytes()
        result["equalElements"] = int(np.count_nonzero(left == right))
        finite = np.isfinite(left) & np.isfinite(right)
        result["maxAbsFinite"] = float(np.max(np.abs(
            left[finite].astype(np.float64) - right[finite].astype(np.float64)
        ))) if finite.any() else None
    return result
