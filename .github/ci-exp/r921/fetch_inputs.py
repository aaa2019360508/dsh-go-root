"""校验用于六图 C API 研究的固定文件。仅 --fetch-missing 会读取网络。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen

MANIFEST = Path(__file__).with_name("INPUT-SOURCES.json")
CHUNK = 1024 * 1024


def check_stream(source, item, target=None):
    count = 0
    digest = hashlib.sha256()
    # 部分原件另外具有固定 Git blob，大小使用已登记的原始文件字节数。
    git = hashlib.sha1(f"blob {item['bytes']}\0".encode()) if "gitBlob" in item else None
    while block := source.read(CHUNK):
        count += len(block)
        if count > item["bytes"]:
            raise ValueError(f"{item['filename']}: 超出锁定字节数 {item['bytes']}")
        digest.update(block)
        if git is not None:
            git.update(block)
        if target is not None:
            target.write(block)
    if count != item["bytes"] or digest.hexdigest() != item["sha256"]:
        raise ValueError(f"{item['filename']}: 摘要或字节数不符，读到 {count} B，SHA-256 {digest.hexdigest()}")
    if git is not None and git.hexdigest() != item["gitBlob"]:
        raise ValueError(f"{item['filename']}: Git blob 不符")


def check_file(path, item):
    if not path.is_file():
        raise ValueError(f"{path}: 需要常规文件")
    with path.open("rb") as stream:
        check_stream(stream, item)


def fetch_missing(path, item):
    # 在同一目录完成校验后才公布文件。链接操作会保留并发到达的已存在原件。
    request = Request(item["url"], headers={"User-Agent": "dsh-go-model-reproduction/1"})
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".input-", delete=False) as out:
            temporary = Path(out.name)
            with urlopen(request, timeout=90) as source:
                check_stream(source, item, out)
        try:
            os.link(temporary, path)
        except FileExistsError:
            check_file(path, item)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--inputs", type=Path, help="11 个固定文件共用的平面目录")
    target.add_argument("--verify-map", type=Path, help="只读校验 JSON 对象，键为全部固定文件名，值为本机绝对路径")
    parser.add_argument("--fetch-missing", action="store_true", help="从清单中的固定公开来源获取缺失文件")
    args = parser.parse_args()
    files = json.loads(MANIFEST.read_text(encoding="utf-8"))["inputs"]
    if args.verify_map is not None:
        if args.fetch_missing:
            parser.error("--verify-map 是只读模式，与 --fetch-missing 互斥")
        paths = json.loads(args.verify_map.read_text(encoding="utf-8"))
        if not isinstance(paths, dict) or set(paths) != {f["filename"] for f in files}:
            parser.error("映射必须覆盖且只包含清单中的 11 个文件名")
        if any(not isinstance(path, str) or not Path(path).is_absolute() for path in paths.values()):
            parser.error("映射值必须是已有原件的绝对文件路径")
        paths = {name: Path(path) for name, path in paths.items()}
    else:
        paths = {f["filename"]: args.inputs / f["filename"] for f in files}

    missing = []
    for item in files:
        path = paths[item["filename"]]
        if os.path.lexists(path):
            check_file(path, item)
        else:
            missing.append(item)
    if missing and not args.fetch_missing:
        raise ValueError("缺少原件：" + "、".join(f["filename"] for f in missing))
    if missing:
        args.inputs.mkdir(parents=True, exist_ok=True)
        for item in missing:
            path = paths[item["filename"]]
            if os.path.lexists(path):
                check_file(path, item)
            else:
                fetch_missing(path, item)
    print(json.dumps({"files": len(files), "bytes": sum(i["bytes"] for i in files),
                      "initiallyMissing": [i["filename"] for i in missing],
                      "status": "verified"}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit(str(error))
