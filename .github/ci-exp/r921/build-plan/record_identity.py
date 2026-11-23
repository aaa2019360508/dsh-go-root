"""Tie pair-run inputs to the successful native build and its evidence."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record_side(evidence, source, config, side, library):
    owner = evidence / side
    reduced = side == "candidate"
    def rev(name):
        return subprocess.check_output(["git", "-C", str(source), "rev-parse", name], text=True).strip()
    library = library.resolve(strict=True)
    if reduced and (owner / "generated-diff.txt").stat().st_size:
        raise SystemExit("Candidate registration sources differ")
    row = {"role": side, "ortCommit": rev("HEAD"), "ortTree": rev("HEAD^{tree}"),
           "configSha256": digest(config), "reduced": reduced,
           "includeOpsConfigSha256": digest(config) if reduced else None,
           "libraryPath": str(library), "libraryBytes": library.stat().st_size, "librarySha256": digest(library),
           "commandSha256": digest(owner / "command.txt"),
           "generatedMatch": True if reduced else None,
           "generatedSha256": digest(owner / "generated.sha256") if reduced else None}
    (owner / "build-identity.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")


def record_pair(evidence):
    for role in ("baseline", "candidate"):
        if (evidence / role / "result.txt").read_bytes() != b"SUCCESS\n":
            raise SystemExit(f"{role} build has not completed successfully")
    rows = {role: json.loads((evidence / role / "build-identity.json").read_text(encoding="utf-8"))
            for role in ("baseline", "candidate")}
    b, c = rows["baseline"], rows["candidate"]
    if os.path.samefile(b["libraryPath"], c["libraryPath"]):
        raise SystemExit("Both roles resolve to the same file")
    if any(b[key] != c[key] for key in ("ortCommit", "ortTree", "configSha256")):
        raise SystemExit("The pair does not share a source and research configuration")
    result = {"schema": 1, **{key: b[key] for key in ("ortCommit", "ortTree", "configSha256")}, **rows}
    (evidence / "pair-build-identity.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "pair":
        record_pair(Path(sys.argv[2]))
    elif len(sys.argv) == 7 and sys.argv[1] == "side" and sys.argv[5] in ("baseline", "candidate"):
        record_side(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5], Path(sys.argv[6]))
    else:
        raise SystemExit("record_identity.py side EVIDENCE SOURCE CONFIG baseline|candidate LIBRARY | pair EVIDENCE")
