# 六模型双库复现入口

此包包含完整 Linux 库已运行的原始文本结果，以及下一次“相同源码完整 CPU 基线 / 保守算子候选”的构建与推理配方。**包内没有裁减候选的成功结果。** `MODEL-RUN-BASELINE.md` 说明既有基线；本文件说明如何得到一份新的成对证据。

仅在 Linux x86-64 主机运行，使用 CPython 3.12、NumPy 2.3.5、JDK 21 及固定 Kotlin JAR。先准备足够的构建磁盘与内存；本研究工作区剩余空间不足以稳妥放下两次完整源码构建，未在此启动它们，也没有测出该配方的峰值需求。整个过程不修改 App 仓库、APK 或发版流程。

## 1. 文件布局与已有证据

| 路径 | 用途 |
|---|---|
| `MODEL-RUN-BASELINE.md`、三份 `*-baseline/result.json` | 实际完整库的 1,207 次 Run 与边界 |
| `transport-validation/` | 更早的一次同库 C API / 官方 Python 小核对及当时源码 |
| `prepared-baseline/source/`、`speech-baseline/source/`、`zipformer-baseline/source/` | 与既有结果对应的当时源版本；复核历史结果时用它们 |
| `build-plan/` | 新的同源双库构建、依赖说明、4958 B 配置、四份生成文件的期望摘要 |
| `run-pair.py`、三份 `*_probe.py`、`ort_client.py`、`ort_runner.cc` | 下一次双库研究入口；新诊断和汇总不能冒充既有实际运行 |
| `preprocess/`、`product/`、`include/` | 固定产品前处理原件、输入生成器、公开 C 头 |
| `INPUT-SOURCES.json`、`fetch_inputs.py` | 11 件外部输入的固定身份与校验 / 获取 |
| `bundle-source-index.json`、`LICENSE/` | 公开来源及源码许可 |
| `MANIFEST.json`、`verify.py` | 本文本包的完整文件集合、长度、SHA-256 核对 |

所有模型、外部权重、声音、词表原件、tokenizer、wheel、JAR、动态库、编译输出和 tensor 均留在执行机私有目录。公开来源与摘要已经给齐，不需从本包重构任何二进制。包内的旧 `ZIPFORMER-RUN.md` 和前处理 README 保留当时单项复算用法；新双库执行以本文件的统一入口为准。

## 2. 准备环境与输入

`bundle` 是解包后的绝对路径，`private_root` 是执行机上的私有工作根目录。不要让后者位于前者里面。下例的占位路径由操作者替换；两次构建和推理各使用尚不存在的工作目录。

```bash
set -euo pipefail
bundle=/absolute/path/to/model-run-evidence
private_root=/absolute/path/to/private-work
ort_source=/absolute/path/to/fixed-ort-source
build_work="$private_root/new-ort-pair"
run_work="$private_root/new-model-pair"
inputs="$private_root/inputs"
cfg="$bundle/build-plan/required-operators.config"
private_work="$private_root"
src="$ort_source"
work="$build_work"
recipe="$bundle/build-plan"

python3.12 "$bundle/verify.py"
```

按 [DEPENDENCIES.md](build-plan/DEPENDENCIES.md) 准备 Python 包、11 个 Kotlin 编译 classpath JAR、单独的 org.json JAR、JDK 和系统构建工具。依赖来源清单与 JAR 身份均已实际核对。历史 NumPy 安装所用 wheel 没有保留；所给 PyPI wheel 是可选复现输入，不能写成旧安装文件的实测身份。新的两侧必须共用同一 Python / NumPy / JVM / 编译环境。

固定模型和输入可复用执行机已有原件，或按清单获取缺失项：

```bash
python3.12 "$bundle/fetch_inputs.py" --inputs "$inputs" --fetch-missing
```

不带 `--fetch-missing` 时只有校验，不访问网络。程序先校验已有文件，再取缺失项；不会用新下载覆盖身份不符的旧文件。11 件共 234,067,558 B，下载后的文件名放在同一个平面目录。若原件分散，`--verify-map` 可以只读核对现有绝对路径映射，但后续统一入口仍接受平面目录。映射及下载临时文件不属于回执内容。

## 3. 同源完整库和候选构建

按 [LINUX-X64-PAIR.md](build-plan/LINUX-X64-PAIR.md) 获取并验证：

- ORT commit `8f0278c77bf44b0cc83c098c6c722b92a36ac4b5`。
- 根树 `5ea4a49d0be5e5a620cabaa01f85d924b2fa5995` 及固定子模块。
- 研究配置 SHA-256 `1601aecf861212c77c9a92395369f4b89035b75b3824e657b3e45ab00bfcc826`。
- CPython 3.12、flatbuffers 25.2.10、CMake ≥3.28、Ninja、同一 C/C++ 编译器和链接器。

```bash
bash "$bundle/build-plan/build-pair.sh" plan "$ort_source" "$build_work" "$cfg"
bash "$bundle/build-plan/build-pair.sh" build "$ort_source" "$build_work" "$cfg"
```

两侧都是 Release、完整共享库、默认 CPU EP、顺序构建同一 `onnxruntime` 目标，使用相同并行度；候选只额外传入 `--include_ops_by_config`。没有 minimal、类型裁减、关闭 contrib / ML、训练包、Python 绑定、Java / JNI、Android 或新增 LTO。共同选项没有当作本候选的收益。

构建脚本保存环境、命令、日志、CMakeCache、Ninja build edge 和规则、ELF 摘要，以及候选生成的四份注册 / 类型文件 SHA。`936` 指生成源中的保留注册声明，不指当前主机构建最终注册内核。两侧完成后保存每侧 `build-identity.json` 和成对 `pair-build-identity.json`；它们把源码、配置、实际库路径 / 长度 / SHA、命令和生成文件记录连起来。只比两个路径名不足以证明加载了两份本次构建产物。

如果构建失败，先保存第一次错误和已经生成的文本证据。余下阶段保持 `NOT_RUN`，不为使候选通过临时删功能、改版本、换配置或加重试。前置检查失败可能还没有结果文件；外部中断或记录步骤失败也可能只留下 `STARTED`，此时按具体阶段说明，不能一律写作编译失败。成对运行只接受两侧精确 `SUCCESS` 及完整身份。`link.txt` 中若有 `@rsp`，按两份 Ninja 文本追查变量及输入；外部响应文件若不能从规则还原，补它的原始文本并指出缺失，不能把占位符叫作完整展开命令。

## 4. 构建完成后统一运行

先查看实际参数向量。`--plan` 只列计划，不运行外部命令，不创建输出目录，也不证明路径或依赖已可用。

```bash
python3.12 "$bundle/run-pair.py" \
  --inputs "$inputs" \
  --kotlin-jars "$private_root/kotlin-jars" \
  --json-jar "$private_root/json-jar/json-20240303.jar" \
  --baseline-library "$build_work/build-baseline/Release/libonnxruntime.so" \
  --candidate-library "$build_work/build-candidate/Release/libonnxruntime.so" \
  --build-evidence "$build_work/evidence" \
  --work "$run_work" --plan
```

确认是本次完整双构建记录后，去掉 `--plan` 执行同一命令。入口按次序校验 11 件输入、工具 / 产品源 / 头文件 / 两库身份，编译 C API runner 与 Kotlin 前处理，生成两组私有输入，执行 prepared、speech、zipformer 三组，最后汇总。

两库不能是同一个文件或 inode。若两次独立构建碰巧得到同 SHA，回执必须记录这个事实并用完整构建记录解释，不能伪造一个摘要或换名逃过核验。此时可记录 `allFixedCasesBitwiseEqual` 的事实，但 `artifactIdentity=IDENTICAL_ARTIFACT`，`distinctBuildComparisonPassed=false`，最终以非零退出，不能冒充独立候选对照通过。相同输入喂给不同库时，Silero 与 Zipformer 的循环状态分别推进；出现分叉后，输出误差和不同输入不能混在一起归因。

执行输出分为：

- `private/`：可执行件、Kotlin classes、音频 / tensor、临时 wheel 展开、进程工作文件及诊断原件。
- `evidence/`：可读 JSON 身份、各阶段状态、前处理摘要、模型统计、严格对照与诊断文本。

`status.json` 每步更新 `NOT_RUN → RUNNING → PASS/FAIL`，首处失败即停止。数值阶段成功完成而最后逐位判定失败时，保留三份结果与 `aggregate.json` 并非零退出；这表示发现了差异或证据不完整，不能写作缺内核，具体原因要读原结果。模型初始化 / Run 失败时看记录的阶段、模型、侧别和原始 ORT 错误；只给 Python 的 `Traceback` 首行不算可诊断回执。

当前模型阶段的 `modelSessions` 保留各侧控制状态及已经完成的 Run 数；中断会重读已落盘的事件，不把已运行项退回 `NOT_RUN`。`firstError.nativeDiagnostics` 只保存受限长度的 stderr 摘录，每项至多 4,000 字符；完整诊断仍在本机 private。若摘录缺少首个相关原因，请手工补它的文本上下文，并明确剩余缺口。

## 5. “这些用例逐位相同”的条件

本研究不新增容差。所有预期输出名必须齐全，观察次数必须和实际调用相符；空集合或缺少某一个结果不能算通过。

| 组 | 必须比较的内容 |
|---|---|
| BGE 5 例 | `last_hidden_state`、`sentence_embedding` 的 shape / type / 原字节；归一化 CLS；固定四文档得分和顺序 |
| SmartTurn 8 例 | 四个合成和四个语音窗口的 `logits`；两侧各使用相同的固定前处理输入 |
| Silero | warm-up 及 400 / 393 次实际调用的 `output`、`stateN`；每次循环输入同形同类型同字节；末尾余样 0 / 128 |
| Zipformer | 每个 encoder 调用的 36 项输出，decoder / joiner 各 1 项；所有对应输入；没有单侧调用；逐项观察数等于该模型 Run 数 |
| 决策轨迹 | Zipformer 端点记录、argmax、输出累积签名、最终 token；BGE 固定用例排序 |

候选失败或有数值不同就原样交回，不要求为得到“通过”修改输入。完整库的旧基线是 PyPI 产物，不能直接冒充本次重新构建的 baseline。即使这次 host CPU 全部逐位相同，结论也只覆盖这两个库与这组输入；Android arm64、NNAPI、Java / JNI、完整 Sherpa、其他语音 / 文本和设备性能另待证据。

## 6. 需要回传的文本

回传两处 `evidence/` 的 UTF-8 文件，以及执行入口 / 源码 / 配置身份。正文说明哪一阶段成功或失败、六图各自是否建 Session / Run、是否数值分叉、还有什么没执行。若进程被外部终止而最后状态仍为 `RUNNING`，按“中断、完成情况未知”回报，不能补写 PASS。

不回传 `.so`、APK、DEX、模型、外部权重、录音、PCM、原始张量、JAR、wheel 或可执行程序，也不用压缩成员、Base64 或差分恢复它们。文本 ZIP 只能由明确的文本文件清单建立，不能对整个 private / build 工作目录递归打包。本包的 `verify.py` 检查本包本身；新回执另提供逐文件长度 / SHA 与文本检查结果。

此研究对应 ADDENDUM-10 允许的会话验证；真机仍沿 916 清单，没有新设备请求，没有产品替换片。
