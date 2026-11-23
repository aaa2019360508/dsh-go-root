"""Verify the exact UTF-8-only research delivery; does not run models or builds."""
from hashlib import sha256
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    files = manifest["files"]
    expected = set(files) | {"MANIFEST.json"}
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"symlink is not part of this delivery: {path.relative_to(root)}")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != expected:
        raise ValueError({"missing": sorted(expected - actual), "extra": sorted(actual - expected)})
    total = 0
    for name, identity in files.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unexpected path: {name}")
        data = (root / relative).read_bytes()
        data.decode("utf-8")
        if b"\0" in data:
            raise ValueError(f"NUL in a text delivery: {name}")
        if len(data) != identity["bytes"] or sha256(data).hexdigest() != identity["sha256"]:
            raise ValueError(f"identity mismatch: {name}")
        if name.endswith(".json"):
            json.loads(data)
        total += len(data)
    print(json.dumps({"status": "verified", "utf8FilesIncludingManifest": len(expected),
                      "payloadBytesExcludingManifest": total}, ensure_ascii=False))


if __name__ == "__main__":
    main()
