# 六张固定模型的主机实际 Run：完整库基线与裁减候选待验边界

**已实际完成的是完整 ORT 1.27.0 在 Linux x86-64 CPU 上的六图推理。裁减候选尚未执行本组 Session / Run。** 主测试合计 1,207 次 Run，覆盖 BGE 的实际 WordPiece 输入、SmartTurn 的产品 WhisperMel 输入、Silero 连续状态，以及 Zipformer 三图跨一次自然端点的贪心决策。另一次运输层核对用同库 C API 和官方 Python 各跑了 Silero 全零输入；两侧输出逐位一致。上述均不构成裁减候选、Android ABI、JNI 或完整 Sherpa 集成已通过的结论。

本项依据 ADDENDUM-10 允许的六模型验证继续。它没有更换产品库、修改 APK、提交产品补丁或推进本次发版替换。919 已测的 Android arm64 体积差保留原来的适用范围；下文新的 Linux 构建路线只服务于模型数值研究。

2026-11-23 09:23 UTC 巡检时 main 已到 `a707bbe2ae7cabc564683c949ed12f58c0c174ff`（PR1858）。与本研究固定 567 的完整比较只有 runtime 与维护 docs 的九条路径，产品前处理和输入锁未变。详见 [CURRENT-BASE.json](CURRENT-BASE.json)；原始结果仍保留实际运行时的 567 身份，没有因 main 前进而改写或重复运行。

## 1. 身份与观测口径

产品参考固定在 `567390d1f943777ac8f8e9c3abbbbe346821e5d1`，根树 `73ba2b42a0a9ecacf2de4071f547fbfae335cea0`。实际编译的产品前处理原件只有 `WhisperMel.kt` 与 `CompanionWordPiece.kt`，未改实现。来源、Git blob、SHA-256、Kotlin 编译 classpath、词表摘要见 [preprocess/source-identity.json](preprocess/source-identity.json)。相关生产路径在 5b→567 的合并中未变；本报告不把别线 7136–7138 的合入计入 native 的 28 片。

实际基线来自已核身份的官方 Python wheel 所带完整 Linux 库：

| 项 | 实际值 |
|---|---|
| 库版本 / C API | ORT 1.27.0 / 27 |
| `libonnxruntime.so.1.27.0` 原长 | 23,658,512 B |
| 库 SHA-256 | `b5c9d4f124d24707f514dad926dc181820807178855df1c528e3addb2dd0e6f7` |
| wheel 原长 / SHA-256 | 18,658,316 B / `7c65a7438632d55dfbc8a02ee60bd6cf7dd9d1ba05a43d4b851452f32338e194` |
| 本次主机 | Linux x86-64，glibc 2.41；Python 3.12.14，NumPy 2.3.5 |
| 前处理 JVM / Kotlin | OpenJDK 21.0.13 / Kotlin 2.4.0 |
| 执行配置 | CPU、顺序执行、`ORT_ENABLE_ALL`、`ORT_LOAD_CONFIG_FROM_MODEL=0` |
| intra / inter 请求线程数 | BGE、SmartTurn、Silero 均为 1 / 1；Zipformer 三图为 2 / 2 |

库、主机和各图的身份直接记录在三份原始 result.json。公开输入 11 件的固定下载地址、长度、SHA-256 及可用的 Git blob 见 [INPUT-SOURCES.json](INPUT-SOURCES.json)，合计 234,067,558 B。7 个模型文件对应 6 张图，其中 BGE 另有外置权重。声音、模型、JAR、wheel、PCM、原始张量和可执行件均不随此文本证据包交付。

`ort_runner.cc` 用固定源码提交 `8f0278c77bf44b0cc83c098c6c722b92a36ac4b5` 的公开 C API 头编译。两份头文件与根树 `5ea4a49d0be5e5a620cabaa01f85d924b2fa5995` 的 blob 对应，见 [header-identity.json](header-identity.json)。微软入口当时对补取的 EP 头返回 404，实际从 Intel 镜像相同 commit / tree 取得并核 blob；不将镜像读取写成微软端已成功下载。runner 在独立进程内 `dlopen` 一份库，复用同一 Session，按模型声明收集全部输出。它只接受本六图所需的 float32 / int64；`sr` 是 int64 标量。输入文件和输出文件仅作私有研究运输，不等同于 Android 的模型 byte[]、直接缓冲或预绑定输出路径。

## 2. 实际执行量

| 图 | 主测试 Run 次数 | 对应输入与状态 | 证据 |
|---|---:|---|---|
| BGE | 5 | 空文档、相同句子文档/查询、混合文本、达到 512 token 上限的文档 | `prepared-baseline/result.json` |
| SmartTurn | 8 | 4 个静音/合成窗口，4 个公开语音窗口 | prepared 与 speech 两份结果 |
| Silero | 794 | 1 次全零 warm-up；连续 400 次；带指定静音边界 393 次 | `speech-baseline/result.json` |
| Zipformer encoder | 40 | 连续 39 个实时窗，加 finish 后 1 个窗；35 个缓存状态续接 | `zipformer-baseline/result.json` |
| Zipformer decoder | 40 | 初始/端点后上下文及实际非空发射后的更新 | 同上 |
| Zipformer joiner | 320 | 每个 encoder 输出时间帧一次真实决策 | 同上 |
| **合计** | **1,207** | 只有完整 Linux 基线 | 三份 JSON 合计 |

这些计数来自实际完成结果与驱动中一条记录对应一次 Run 的关系，未使用挂钟推算。由成功完成的三段驱动源码可进一步推出：主测试建立了 7 个持久 Session——BGE 1、SmartTurn 2、Silero 1、Zipformer 3；这不是额外 API profiler 的独立计数。独立运输核对的 C API / Python 各 1 次 Run 不混入 1,207。

### 运输层的有限核对

[transport-validation/result.json](transport-validation/result.json) 保存全零 Silero 的同库对照：`output` 1 个 float32、`stateN` 256 个 float32，共 1,028 B，C API 与官方 Python 结果逐位相同，有限数的最大绝对差为 0。其当时 runner、client、检查脚本原件随同保存；当时 runner 尚未增加线程参数，后续通用 runner 也补了输出关闭与显式子进程环境设置。这次小核对验证当时这一模型与运输路径，不能扩张为后来所有形状、全部脚本或 Android API 已独立证明。

## 3. BGE：实际 WordPiece、两项原输出与 CLS 归一化

输入直接由固定产品 `CompanionWordPiece.kt` 编译执行。五个序列长度依次为 2、10、29、14、512；三项输入均为 int64 `[1,T]`。查询保留产品前缀“为这个句子生成表示以用于检索相关文章：”。混合用例包含中文、ASCII、标点、未知字符和五种特殊标记；内部 `[PAD]` 的 attention mask 仍按产品实现为 1。512 个“中”的文档只保留 510 个正文 token，再加首尾标记。21,128 个词表 ID 已逐项核唯一性。详见 [preprocess/README.md](preprocess/README.md) 与 [fixture-summary.json](preprocess/fixture-summary.json)。

五次实际 Run 的 `last_hidden_state` 均为 `[1,T,512]`，`sentence_embedding` 均为 `[1,512]`，所有元素有限。研究脚本取 `last_hidden_state[0,0,:]`，按产品相同顺序逐项用 Double 平方求和、开方再归一化，保留 512 个 Double 的摘要。此后处理在 Python 完成；相同公式和顺序不是 Android / JVM 浮点逐位相等的独立证明。成对验证将同时比较两个原输出和归一化 CLS，不能仅比较模型自带 sentence embedding。

固定 query 与四个文档的实际点积为：

| 文档 | 归一化 CLS 点积 |
|---|---:|
| same-doc | 0.8144987853191012 |
| mixed-doc | 0.2627432374739456 |
| empty-doc | 0.24794361369866746 |
| long-doc | 0.1748961828179109 |

这是这四个受控文档的排序，没有运行产品的记忆数据库、检索筛选或全部召回策略。证据为 [prepared-baseline/result.json](prepared-baseline/result.json) 的 `cases`、`normalizedCls` 和 `bgeSimilarity`；当前不存在候选侧数值。

## 4. SmartTurn：产品 Mel 与 0.5 两侧的实际结果

`PrepareInputs.kt` 以 PCM16 / 32768f 构造最近 8 秒的 128,000 位环，逐样本核对保留顺序，再调用未修改的 `WhisperMel.kt`。短片段在左侧补零；不是把模型特征直接填零。实际 1 秒静音经产品前处理得到的 `[1,80,800]` 特征全为 **−1.5**。所有用例的特征为 64,000 个 float32，即 256,000 B，且全部有限。

四个合成用例仅用于输入边界，得到概率约 0.9870、0.9823、0.9777、0.9794，不能当作真实语音端点覆盖。为补这个缺口，又用固定公开 5.1 秒语音构造四个实际窗口：

| 语音窗口 | 内容概要 | 实测 `logits[0,0]` | ≥0.5 |
|---|---|---:|---|
| spoken-1s | 左补 7 秒零，再接原音前 1 秒 | 0.9485659599304199 | 是 |
| spoken-5p1s | 左补 2.9 秒零，再接完整原音 | 0.9647200703620911 | 是 |
| joined-full-8s | 5.1 秒原音 + 2.6 秒零 + 重复原音前 0.3 秒 | 0.9848582744598389 | 是 |
| joined-wrap-9s | 从拼接流第 1 秒到第 9 秒，保留最后 8 秒 | 0.23476183414459229 | 否 |

窗口取样时点是本次输入设计，未模拟 NeuralGate 的话轮起点、预录音裁剪、200 ms 静音机会、异步 pending 或代际丢弃。因而已经观测到阈值两侧，不意味着还原了真人一次结束说话的判断时刻。输入公式及四份不同 SHA 见 [PUBLIC-WAV-RECIPE.md](preprocess/PUBLIC-WAV-RECIPE.md)、[public-wav-summary.json](preprocess/public-wav-summary.json) 和 speech 原始结果。

## 5. Silero：连续状态、余样与静音边界

受控 PCM 是“5.1 秒公开语音 + 2.6 秒静音 + 同一 5.1 秒语音”，共 204,800 个采样，以 320 个采样一帧送入，合计 640 个 20 ms 帧。Silero 每收满 512 个新样本才 Run，模型输入包含 64 个上下文样本，所以 shape 为 `[1,576]`。循环 state 为 `[2,1,128]`，下一次 Run 接上一次 `stateN`；每帧不一定触发一次模型调用。

| 场景 | Run | 帧内未触发 Run 的未静音帧 | 最后余样 | 帧输出最大概率 | 帧输出≥0.5 数 |
|---|---:|---:|---:|---:|---:|
| 不静音 | 400 | 240 | 0 | 0.999984622001648 | 404 |
| 输入帧下标 100–109 静音 | 393 | 237 | 128 | 0.9999880194664001 | 382 |

第二场景的计数可独立算回：前 100 帧为 32,000 个样本，完成 62 次 Run，256 个余样在静音边界舍弃；10 帧跳过；后 530 帧为 169,600 个样本，完成 331 次，余 128。合计 62+331=393。无静音场景为 204,800 / 512=400。帧输出会在没有 Run 的帧复用最近概率，故上表阈值计数是帧数，不能错写为模型 Run 数。

逐次 state 摘要的只读复核确认：无静音的 399 次相邻连接全部续接；有静音的唯一清零间断位于结束帧下标 99 与 111 的两次 Run 之间。成对脚本会让两侧分别推进自己的 state/context，比较本次输入后才更新状态，避免误把一侧状态喂给另一侧。

原始 JSON 的 `resetOnEachMutedFrame:true` 只描述研究脚本。产品 CallCapture 每个静音帧调用 gate.reset，但 NeuralGate.reset 在 size==0 时提前返回，连续后九帧不再实际调用 vad.reset。研究脚本在没有 Run、没有重新填样的这十帧重复清空已全零状态，数值输入相同；它不是生产清零次数、分配或耗时的测量。原始字段、SHA 和实际源版本保持不动，解释见 [INTERPRETATION.md](speech-baseline/INTERPRETATION.md)；后续通用入口仅把元数据字段名明确为 `harnessResetOnEachMutedFrame`。

## 6. Zipformer：三张图、真实发射与一次端点

同一段 12.8 秒 PCM 经固定 kaldi-native-fbank 1.22.3 生成特征。设置由固定 Sherpa 源码推导：16 kHz、25 ms 窗 / 10 ms 步长、80 mel bins、Povey、dither=0、snip_edges=false、去直流、0.97 预加重、FFT 取二次幂、低/高截止 20 / −400 Hz。词表核实 blank=0、unk=2。具体来源见 [ZIPFORMER-RUN.md](ZIPFORMER-RUN.md) 与 [14 项输入合同源码索引](SOURCE-CONTRACTS.json)；索引也列出本报告引用的 NeuralGate、OrtSpeechModels、CallCapture、EmbeddingPlugin 与 Dart finish 实现。

研究脚本按严格 `processed+39 < ready` 取 39 帧窗，每次推进 32 帧；每侧分别持有 35 份 encoder 状态、最后两枚 token 上下文和 decoder 输出缓存。初始上下文 `[-1,0]`，joiner 用 raw logits 的首个最大值决定发射，只有实际非 blank / 非 unk 发射才更新 decoder。自然端点保留 encoder 状态及词上下文，清空结果和 decoder 缓存。finish 追加 4,800 个零样本，inputFinished 后排空，不另作端点判断。

实际得到 39 个实时块和 1 个 finish 块，共 40 次 encoder、40 次 decoder、320 次 joiner；282 个 blank、38 次发射，另有 38 个块复用上一块的 decoder 输出。自然端点发生在累计送入第 325 个 PCM 帧后（此处从 1 计数），中间静音段，命中 rule2：640 个已处理特征帧、32 个连续 blank。第一段累计 18 次发射，第二段直到 finish 累计 20 次发射；**20 不是最后一块的发射数**。所有模型输出有限，320 次 joiner 观测的 top-2 raw-logit 最小差为 0.058086395263671875。

原始结果记录全部三图输出的逐调用累积签名、argmax 序列签名、端点和末尾 token 签名，见 [zipformer-baseline/result.json](zipformer-baseline/result.json)。这是公开图直接经 C API 执行与研究调度，不是完整 Sherpa OnlineRecognizer 的实跑；没有比较 UI 文字、文本规范化、`ys_probs` 或完整识别结果对象。rule1、rule3、unk、非 finish 取消、其他语音与设备线程行为未覆盖。

## 7. 结果文件、可复算性与下一证据

| 原始结果 | 字节 | SHA-256 |
|---|---:|---|
| prepared-baseline/result.json | 17,479 | `161c707bba3fdad5bd8179aea1e5895413315ea80a89c07e95a4dbd03e0badce` |
| speech-baseline/result.json | 2,219,566 | `0aeaacd8e79c0a32d49f8f00ccef008676a034d3e31e09a2a2744646a1781c11` |
| zipformer-baseline/result.json | 2,852 | `98bb9cbccf501ee01005244fdc0c9fc730a6853137702a704bf22d017f6007c5` |

三份原始 JSON 未为整理报告而重跑或改写。prepared / speech 的实际源文件按原 JSON 的 sourceIdentity 保存；Zipformer 的当时源文本另存清单，其原结果本身还记录 runner 可执行件 SHA。单独运输核对也保留其旧接口源版本。包级清单逐件核文本长度、SHA 和允许的文件集合。

下一步需要固定同一 ORT commit / tree，在同一 Linux x86-64 环境分别完整构建默认 CPU 基线和候选，候选仅额外传入 4,958 B 的保守配置 `--include_ops_by_config`。配置 SHA-256 为 `1601aecf861212c77c9a92395369f4b89035b75b3824e657b3e45ab00bfcc826`。源码中 936 条保留注册声明不等于最终宿主注册内核数；候选能否执行必须由新的实际 Session / Run 判定。具体入口见 [RUN-PAIR.md](RUN-PAIR.md) 和 [LINUX-X64-PAIR.md](build-plan/LINUX-X64-PAIR.md)。

新的自建完整库与此处 PyPI 基线来源不同，不能把两者的输出、体积或工具链身份混成一次成对实验。成对运行要求两侧实际库及构建记录相符，输入固定，各循环状态独立；严格逐位汇总还要核齐所有输出名和每项观察次数。若出现数值差异，保留首处位置和有限误差，不自行放宽容差或改候选集合。若构建、初始化或 Run 失败，保留首个错误和阶段，后续未执行项写 `NOT_RUN`。

**仍缺的证据**：候选这六图的真实运行及数值；Android arm64 / NNAPI / JNI 和 Sherpa 集成；其他模型输入与调度分支；实际设备的冷启动、CPU、耗电、PSS 和同条件 APK。固定主机输入全部逐位相同，最多能支持“这些库与这些用例逐位相同”；不能据此消除这些边界。设备事项仍只使用既有 916 清单。本项不增加产品补丁数，也不为等待外部运行停下后续研究。
