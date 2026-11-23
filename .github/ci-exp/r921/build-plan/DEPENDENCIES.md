# Linux x86-64 双库复算工具

用一套 Linux x86-64、CPython 3.12、JDK 21、Git、Bash、GNU coreutils、正常的系统 C/C++ 工具链、CMake ≥3.28、Ninja 和 binutils。C API runner 用 C++17 及 Linux libdl；ORT 本体的 GNU C 最低版本检查为 11.1。本次输入预处理的实测环境为 Python 3.12.14、NumPy 2.3.5、OpenJDK 21.0.13 和 Kotlin 编译器 2.4.0。新双库构建仍须两侧使用同一套环境。此前已跑的宿主六模型基线来自单独的完整 ORT 包。

在现有 CPython 3.12 环境新建 venv。以下命令给出相同版本的包；需要逐字确认 wheel 时，用本目录 `environment-dependencies.json` 内的 PyPI URL、长度和 SHA-256。已核 flatbuffers 的本地 wheel 与 PyPI 摘要；当前进程实际加载 NumPy 2.3.5，提供了适用于标准 CPython 3.12 Linux x86-64 的 PyPI wheel 身份，历史安装所用 wheel 未保留。Zipformer 的 kaldi-native-fbank 1.22.3 CPython 3.12 wheel 已由主流程列入 INPUT-SOURCES.json，运行时解开到私有目录，不要求 ORT Python 绑定。

```bash
python3.12 -m venv "$private_work/venv"
source "$private_work/venv/bin/activate"
python -m pip install --only-binary=:all: 'numpy==2.3.5' 'flatbuffers==25.2.10'
python -c 'import sys,numpy,flatbuffers; print(sys.version,numpy.__version__,flatbuffers.__version__)'
```

Kotlin 行为核验使用 11 个 JAR 的现有编译 classpath 和另行提供的 org.json:json:20240303。下面按精确 Maven Central URL 下载到私有目录。脚本逐个校验字节长度和 SHA-256，来源索引同时列出已同本地原件核实的 Maven .sha1。JUnit、Hamcrest、XZ 在原通配 classpath 中，并非六模型运行时依赖。研究入口运行的 JVM classpath 为编译输出、kotlin-stdlib-2.4.0 与 org.json。

```bash
python - "$bundle/build-plan/environment-dependencies.json" "$private_work" <<'PY'
import hashlib, json, pathlib, shutil, sys, urllib.request
src, root = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
for row in json.loads(src.read_text())["jars"]:
    folder = root / row["location"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / row["filename"]
    if not path.exists():
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(row["url"], timeout=120) as response, tmp.open("wb") as f:
            shutil.copyfileobj(response, f)
        with tmp.open("rb") as f:
            assert tmp.stat().st_size == row["bytes"] and hashlib.file_digest(f, "sha256").hexdigest() == row["sha256"]
        tmp.replace(path)
    with path.open("rb") as f:
        assert path.stat().st_size == row["bytes"] and hashlib.file_digest(f, "sha256").hexdigest() == row["sha256"]
PY
export JAVA_HOME=/absolute/path/to/jdk21
export PATH="$JAVA_HOME/bin:$PATH"
java -version
```

给 `run-pair.py` 的参数为 `--kotlin-jars "$private_work/kotlin-jars" --json-jar "$private_work/json-jar/json-20240303.jar"`。若已有这些文件可直接指定，源身份见同一 JSON。JDK 可使用机构已固定发行版；OpenJDK 21 官方下载及校验信息见 [OpenJDK 归档](https://jdk.java.net/archive/)。同一私有环境如需补 CMake 和 Ninja，可使用 `python -m pip install --only-binary=:all: 'cmake==3.31.6' 'ninja==1.11.1.4'`（[CMake](https://pypi.org/project/cmake/3.31.6/)、[Ninja](https://pypi.org/project/ninja/1.11.1.4/)）。这两版是可选工具来源；本轮没有用它们构建 x64 双库。GCC/G++ 或 Clang、binutils、Git 等按构建机原发行版固定软件包来源。研究包不附任何 JAR、wheel、SDK 或动态库。
