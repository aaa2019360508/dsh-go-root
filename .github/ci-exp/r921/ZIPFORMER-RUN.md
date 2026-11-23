# 固定语音连续通过 Zipformer 三图

**完整 ORT 1.27.0 的 Linux x64 基线已运行成功。** 三个持久 C API 会话分别执行 40 次 encoder、40 次 decoder 和 320 次 joiner。320 个贪心决策中有 282 个 blank、38 个实际非 blank/非 unk 发射，另有 38 个 encoder 块直接复用上个块的 decoder 输出。每块 35 个 encoder 状态供下一块使用。没有执行裁减候选或 Android 设备。

| 基线观测 | 数值 |
|---|---:|
| 第一个固定公开录音、静音、第二次相同录音 | 5.1 s、2.6 s、5.1 s |
| 实时投喂的 20 ms 帧 | 640 |
| 实时解码块 / finish 后新增解码块 | 39 / 1 |
| 自然端点 | 第 325 个 PCM 帧，位于中间静音段 |
| 端点判据 | rule2，640 个已处理特征帧，连续 32 个空白输出帧 |
| 第一段端点累计 / 第二段直至 finish 累计的发射数 | 18 / 20 |
| 320 次 joiner 最大与次大 raw logit 的最小差 | 0.058086395263671875 |

两次使用同一段公开 WAV 是为了跨越一次真实端点，在保持 encoder 状态的情况下观察下一段。前端按 16 kHz PCM16 单声道每 320 个采样除 32768 建立 fbank；lib/voice/streaming_asr.dart 的 finish 分支追加 4,800 个零样本，随后 inputFinished 并排空可读块。实时路径每个 feed 结束检查端点，finish 最后不再作端点判定。rule1、rule3、unk、非 finalize 取消及设备权限均不在本次观测范围。转写覆盖以 token 决策与其时点计，未重建界面文字、规范化文本或运行 Sherpa 本身。

## 用相同小输入复算

需要 Linux x86_64、CPython 3.12、NumPy 和同目录 C API 编译入口、未经修改的三份固定图。小输入 `zipformer-inputs.json` 含固定 WAV、tokens 以及 knf wheel 的可下载 URL、长度和 SHA-256，原件留在私有目录。脚本对这三件和三图逐件核 SHA。每次只解开已核 SHA 的 knf wheel 到临时目录，直接调用它的 OnlineFbank。宿主本次 NumPy 为 2.3.5，intra/inter 均为 2，顺序执行，CPU EP，ORT_ENABLE_ALL。`ORT_LOAD_CONFIG_FROM_MODEL=0`。完整库 SHA、runner SHA、输出签名、所有三图输出的逐调用累积 SHA 与决策结果在 zipformer-baseline/result.json。

在工作区根目录执行，输出设为新的目录。换环境时提供同结构的私有输入路径。

```sh
p=recovery/native9-replies/model-run-567
assets=recovery/native8-ci/private/zipformer-probe
models=recovery/native8-ci/private/source-config-inputs
full=recovery/native8-ci/private/ort-host-127/site/onnxruntime/capi/libonnxruntime.so.1.27.0
python3.12 "$p/zipformer_probe.py" \
  --runner "$p/ort_runner" --library "$full" --models "$models" \
  --wav "$assets/1.wav" --tokens "$assets/tokens.txt" --wheel "$assets/"*.whl \
  --out "$p/zipformer-recheck"
```

成对模式另外传 `--candidate /absolute/path/to/libonnxruntime.so`。每侧独立持有三会话、35 个状态、端点计数和 decoder 缓存。相同录音和同一个 fbank 跨端点连续推进。在同一 encoder 块内，按模型角色和时间帧匹配两侧调用；逐一核所有命名输入的 dtype、shape 和原始字节。每侧独有的 decoder 调用单列；分叉后遇到不同输入的输出差异另计，`inputExceptions` 标明块、帧和有差异的输入名。在没有差异时仅记录观察次数；有差异时记录按模型和输出名聚合的最大数值误差及第一处摘要。未设新的浮点容差。用小数组验证过成对汇总器的同输入异输出、不同输入和单侧调用分类，本轮没有候选库实跑。

## 固定来源

- 生产固定 5b 至 567 的字幕入口及模型锁文件未变。Flutter 的输入、结束语义与发布包身份见 neural-frame-5b/DART-SOURCE-INDEX.json。官方 WAV 的固定 Git blob 为 22d84d23a4c3b7d4589aac0198e156becbda9f0e，56317 B 的词表给出 blank=0、unk=2。
- 特征配置沿用 Sherpa 142807252687d81b40d6315f23470a1512a00de3 的 sherpa-onnx/csrc/features.h:17–62、features.cc:287–305；固定 v1.22.3 的 kaldi-native-fbank Git commit 为 b09e686fe2084732ddd30d1ef80acfc0f13eaf01。明确设置低/高截止 20/−400 Hz、80 个 mel bins、25 ms/10 ms、Povey、0 dither、非 snip、去直流、0.97 预加重、FFT 长度取二次幂。
- 同一 Sherpa 提交的 online-zipformer-transducer-model.cc:387–525 提供状态形状和输入输出顺序；online-recognizer-transducer-impl.h:248–250、288–321、374–438 与 online-stream.cc:46–53 给出严格就绪条件、39/32 的窗/步长、端点及重置；online-transducer-greedy-search-decoder.cc:54–71、92–171 提供 [-1,0] 初始上下文、首最大项选取、blank/unk、decoder 缓存。使用模型真实输出决定是否更新 decoder。记录的 token 决策覆盖这一个固定语音样本，不能据此推定其他输入、ABI 或执行提供程序上的内核适配。
