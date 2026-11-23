# Linux x86-64 的六模型双库 Run 配方（草案）

目的：让同一台 Linux x86-64 宿主上的 C API runner 分别加载两个**新构建**的完整 CPU 共享库，以相同输入对照六图的会话创建、实际推理和输出。上游 ORT 固定 1.27.0。基线使用默认完整算子集合，候选额外传入 `--include_ops_by_config`。919 曾构建的是 Android arm64 库，此处重新为 Linux 编译；PyPI 已有完整库的宿主结果也只作独立先例。产品 ABI、EP、打包、手机时延与 PSS 另属设备和集成边界。

## 准备

用同一 Linux x86-64 构建环境和独立、全新的两个构建目录，固定 C/C++ 编译器、链接器、CMake、Ninja、Python、相同环境变量及并行度。固定上游要求 CMake ≥3.28；GNU C 编译器版本检查为 ≥11.1。建议同一可用的较新 GCC/G++ 或 Clang、Python 3.11+ 与 flatbuffers 25.2.10（919 同版）。生成六图输入/比较结果另需 runner 研究包所列依赖。两次完整 Release 编译均需足够空间，`JOBS` 默认 2，可在开始前按机器容量固定。未测此配置的磁盘峰值或构建耗时。

有完整可信的固定 checkout 可直接使用。新获取时给 `src` 一个**尚不存在**的绝对目录。需要能访问 Git 仓库/子模块及 CMake FetchContent 依赖 URL，或用内容相同的可信缓存。Linux C API 路线不需 NDK、Android SDK、JDK 或 Gradle。

```bash
set -euo pipefail
rev=8f0278c77bf44b0cc83c098c6c722b92a36ac4b5
tree=5ea4a49d0be5e5a620cabaa01f85d924b2fa5995
mkdir "$src"
git -C "$src" init -q
git -C "$src" remote add origin https://github.com/microsoft/onnxruntime.git
if ! git -C "$src" fetch --no-tags --depth=1 origin "$rev"; then
  git -C "$src" remote set-url origin https://github.com/intel/onnxruntime.git
  git -C "$src" fetch --no-tags --depth=1 origin "$rev"
fi
test "$(git -C "$src" rev-parse 'FETCH_HEAD^{commit}')" = "$rev"
test "$(git -C "$src" rev-parse 'FETCH_HEAD^{tree}')" = "$tree"
git -C "$src" checkout --detach "$rev"
git -C "$src" submodule update --init --recursive --depth=1
```

`cmake/deps.txt` 记录固定依赖 URL、哈希；`cmake/external/onnxruntime_external_deps.cmake` 按启用选项取用，其中包括相应的宿主工具和传递依赖。保留原文件和校验。CMake 配置阶段仍可能下载第三方内容，克隆主库成功不等于所有依赖已经备妥。不要为规避网络错误改源版本或松动校验。

## 构建

`work` 为不存在的绝对工作目录，父目录可写；`cfg` 为研究包的 `build-plan/required-operators.config`（原始研究文件名 `experimental-cpu.config`），4,958 B，SHA-256 `1601aecf861212c77c9a92395369f4b89035b75b3824e657b3e45ab00bfcc826`。`recipe` 指向本目录。可显式指定现有的绝对 `CC` 和 `CXX` 路径。使用无凭据临时目录，构建采集日志时避免带入敏感环境配置。

```bash
bash "$recipe/build-pair.sh" plan "$src" "$work" "$cfg"
bash "$recipe/build-pair.sh" build "$src" "$work" "$cfg"
```

脚本用原 `tools/ci_build/build.py` 配置 Release、Ninja、CPU 默认 EP、完整共享库和 `--target onnxruntime`。两侧都跳过 ORT 自身测试，不生成 Python 绑定、训练包或 Android/JNI；使用相同的默认非 LTO 配置。主机只调用公开 C ABI。这些共同选项没有作为裁减的体积或速度贡献。保持兼容 ONNX、标准及 contrib/ML 和所有类型；避免 minimal、type reduction、禁用异常或另改源。候选的 full reduced 构建还能激活固定上游的 reduced 条件分支，其结果须由本次实际 Run 判断，不预设任意图都仍有效。

首轮读取结果的私有路径为 `$work/build-baseline/Release/libonnxruntime.so` 和 `$work/build-candidate/Release/libonnxruntime.so`。先确认两份完整 CMakeCache 中 C/C++ 工具、位宽、EP、优化配置和编译模式对齐，并复核实际链接命令；独立构建目录路径及选定 reduced 条件的派生差异单列。构建失败保留首个 CMake/编译/链接错误及命令。若 Ninja 未能自动抽取链接行，按生成的 build.ninja / 对应响应文件补记录，不必再次构建。

**实际链接配方。** 每侧在 configure 产物存在时保留原始 `build.ninja` 与 `CMakeFiles/rules.ninja`。前者给出最终库的 build edge、依赖对象和该边赋值，后者给出对应 link rule 的 command、rspfile 与 rspfile_content（若使用）。`link.txt` 是 `ninja -t commands` 提取的命令；出现 `@…rsp` 时须结合两份原文核对变量与输入，不将这个占位符称为完整展开。若另有不在 Ninja 规则里生成的外部响应文件，则随记录补其实际文本；缺失时只报告证据缺口。

**候选的生成物。** `expected-generated.sha256` 直接取自既有 `generated-result.json`（SHA-256 `8dda6ab95ad683dfc7666a7acd83df321445a61195308767b94c780e3871f171`）三张表的 output 与类型控制 include 的 identity。该记录里 CPU 主表 722、contrib 表 128、training 表 86，共 **936 条生成源码保留注册声明**。training 表同样会生成，而此主机构建没有启用训练。该数不能作为 Linux 宿主最终二进制注册的内核数量。候选若生成了 `Release/op_reduction.generated`，脚本将其全部文件按相对路径排序、逐一记录 SHA-256，与上述四项做完整清单 diff，新增/缺失路径亦可见。成功时 diff 为空；配置或构建失败仍尽量保留已产生的原始证据。

## 六模型结果

将同一 runner 与同一份模型和私有输入分别指向上述两份本地库。按上层研究包的 prepared、speech、zipformer 配方执行；每个模型应分别标识库 SHA、模型及外部数据身份、输入/状态摘要、初始化、Run 和数值对照。任一失败保留用例、阶段及准确错误。如果需要的新候选无法建立某个会话，应保留失败结果。仅回传命令、软件/源码/配置身份、CMake/cache/链接文本摘要、库大小/摘要及六模型的 JSON；不提供共享库、模型、声音或张量原件。完成这些特定用例也不能证明 Android arm64 上的图变换、数值或耗时相同。

## 本地已查

`ARGUMENT-PREFLIGHT.txt` 是本机真实运行 **plan** 的输出。它用该提交原版 `build_args.parse_arguments` 解析两组参数，未进入生成或编译。两组均解析为目标 `onnxruntime`、full CPU，候选仅增加研究配置文件；`build-pair.sh` 另通过 Bash 语法检查。固定源摘要见 `plan-sources.json`。本地未执行完整源码获取或双构建。

另在空临时目录实际调用固定上游的注册源生成器（仅生成四份文本），使用 `--is_extended_minimal_build_or_higher`、固定 config，未传类型裁减或 CUDA。得到的完整文件清单与旧记录逐字相同，SHA-256 `79d3d4f2d60e912e3e78000b34e5f3beaa2ac5ecb02eec6acc34451703f64175`；这一步没有调用 CMake、编译器或模型。

**两件身份。** 首个构建失败后另一侧仍为 `NOT_RUN`，不会生成成功的 pair 记录。每个成功构建由 `record_identity.py` 写 `evidence/<side>/build-identity.json`，记录实际库解析路径、长度、SHA-256、源码 commit/tree、配置、命令摘要与生成物对照。两侧都成功后 `evidence/pair-build-identity.json` 将基线和候选按角色绑定，供上层 run-pair 的 `--build-evidence` 参数使用。
