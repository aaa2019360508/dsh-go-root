# 公共语音样本的四个 SmartTurn 输入

`public_wav_cases.py` 用 Python 标准库 wave 解开已固定 SHA-256 的 `1.wav`（8bfb42c963e623ebab31b81ff4404867d07d3102507c87ac14577c4c61663b8c）。核实 16,000 Hz、单声道、16 位小端、81,600 个样本、无压缩。第一条输入流使用原始 5.1 秒音频。第二条按原音频、41,600 个零样本、同一完整原音频的次序拼成 12.8 秒受控信号，供检查窗口边界；没有模拟真人在麦克风前的停顿时序。

| 用例 | 排他终点（样本） | 实际送入 128,000 个采样位的内容 |
|---|---:|---|
| spoken-1s | 16,000 | 左补 112,000 个零，接原音开头 16,000 个样本 |
| spoken-5p1s | 81,600 | 左补 46,400 个零，接全部原音 |
| joined-full-8s | 128,000 | 81,600 个原音、41,600 个零、重复原音的前 4,800 个样本 |
| joined-wrap-9s | 144,000 | 拼接流的 [16,000, 144,000)，即余下 65,600 个原音、41,600 个零、重复原音的前 20,800 个样本 |

复用同目录 README 中已编译的 `PrepareInputsKt` 与 `cp_run`。入口逐个核对环中保留样本与原 PCM 对应位置，再执行固定产品 WhisperMel。四个输出均为 [1,80,800] 的 finite float32、小端、256,000 B，彼此 SHA-256 不同。取样时点为本次受控输入约定；设备上实际提交 SmartTurn 的时点由 NeuralGate 决定。

```bash
python3 "$research/public_wav_cases.py" "$cp_run" "$pinned_wav" \
  "$private_work/new-real-cases" > "$private_work/public-wav-summary.json"
```

`public-wav-summary.json` 只含格式、采样范围、形状、摘要和极值。程序将 PCM、tensor 与供本地 runner 读取的 input.tsv 写入新建的私有目录。
