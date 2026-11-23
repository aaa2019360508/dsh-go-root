# 冻结前独立复核

2026-11-23，复核方只读审查源码、原始结果及最小合成夹具，没有编译新的 ORT、运行候选模型或修改产品。原始完整库 Run 在此之前已完成；本轮不增加其执行计数。

## 实际基线与来源

三份主结果的长度和 SHA 与主报告逐一吻合。按原 JSON 重计：BGE 5、SmartTurn 4+4、Silero 1+400+393、Zipformer 40+40+320，合计 **1,207 次主测试 C API Run**。独立运输核对的 C API / Python 各一次另列。7 个持久 Session 中，Zipformer 三会话有 `ready` 实录；另四个由成功完成驱动的实际构造路径推导，不写作独立 profiler 实测。

Kotlin 前处理保留固定产品原件。两份 KT、两份 C 头、两份随包许可证的长度、SHA 与 Git blob 相符；11 个编译 JAR 加 org.json 的身份与历史编译索引一致。旧结果及其 sourceIdentity 对应的旧源码单独保存，新诊断代码不倒写为历史运行。

独立复核还核过 Silero 的状态摘要续接和静音边界算术、SmartTurn 四个真实窗口、Zipformer 输出与状态形状、贪心缓存/端点/finish 顺序。报告明确了研究脚本和完整产品生命周期、Sherpa 集成、Android 数值之间的边界。

## 构建与输入入口

固定 11 件输入共 234,067,558 B。获取程序先核已有文件，再下载缺失项；大小、SHA-256 和可用的 Git blob 全部相符才发布。`--plan` 以含空格路径实查，只输出真实参数向量，未创建工作目录或调用模型。

构建脚本的两组参数经过原上游参数解析，Bash 语法通过；未进入 CMake 配置或编译。候选所用四份生成注册 / 类型文件的期望 SHA 清单另以源生成器轻量重算过，与旧记录一致。936 的口径仍是生成源码声明数。

构建证据保留 Ninja 规则、完整命令及实际库身份。`record_identity.py` 仅在两侧 `result.txt` 精确为 `SUCCESS\n` 时配对；同一文件或 inode 被拒绝。用两份文本夹具检查身份记录机制，并用 `STARTED` 状态确认拒绝配对。此夹具不是实际 ELF 构建结果。运行入口还核两侧环境 / 配置 / 命令 / 生成清单与库摘要；两份库相同 SHA 会明确标记 `IDENTICAL_ARTIFACT`，不算独立候选对照通过。

## 严格汇总的反例复验

最初 `66c686…` 版本存在可复现的缺项误报：少量错误命名的对照、漏掉 CLS、过少 Silero 调用等仍可能被汇总为成功。该版没有冻结或交作候选运行依据。

最终版使用三份既有单侧结果的真实形状/统计，在内存中构造标明为合成的另一侧。完整样本含 **38 项 Zipformer 输出指标**：encoder 36、decoder 1、joiner 1。完整样本可通过；以下单项破坏分别被拒绝：

- BGE 缺少 `sentence_embedding` 或 CLS 归一化对照不同。
- 只改变一侧 `mixed-doc` 得分、保持文档排序不变。
- 删除 `new_cached_conv2_4` 或减少某项观察次数。
- Silero 场景调用数不足、或把静音场景最后 128 个余样改错。
- 构建身份改为 `IDENTICAL_ARTIFACT`。

首次失败 / 中断也单独检查：模拟 BGE baseline 已写入第 3 次 `RUN_COMPLETED` 后 Ctrl-C，入口返回 1，prepared 标 `FAIL`，该侧仍保留 `completedRuns=3`，后续 speech 与 aggregate 保持 `NOT_RUN`。session 的 `SCOPE_FINISHED` 只表示该组执行完，最终逐位判定另算。原生和驱动错误从限定的 stderr 尾部摘录，不读取原始 tensor 或二进制内容；若摘录不足以定位，执行者应从本机诊断原件补首个相关错误。

新 `ort_client.py` 的张量运输与数值路径保持原有逻辑，新增事件只记录模型 / 侧别的会话及 Run 控制状态。合成夹具检查的是编排与判据，不能被写成六图的真实双库验证。

## 冻结源码身份

| 文件 | SHA-256 |
|---|---|
| run-pair.py | `3bafe30414f5c54fa189411430d43d92eb99de87fa1a55d74dd841e513a7a47b` |
| ort_client.py | `a3b9f3b5001fc4f51eaa08c5a9579e5db9a582f505075f9ee5d4e859afff07ca` |
| build-plan/build-pair.sh | `19ad5c1dbe4bc4ff6f30c4a6923e7d34830d4331239f3582ecdf9ec20d5e41ee` |
| build-plan/record_identity.py | `4fb0cd48d00bb53c8234e2ba1e4af5ffaa838b90b2db4c1bde43cb3f86c3b147` |

**可冻结的是完整库基线证据与下一次实验入口。自编 baseline / candidate 的真实构建、候选 Session / Run、Android 和设备性能仍未执行。** 最终文本包另按明确白名单生成 MANIFEST，并在冻结目录及独立解包目录执行校验。
