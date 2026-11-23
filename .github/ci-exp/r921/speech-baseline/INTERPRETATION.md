# 此次原始记录的静音口径

result.json 保留了实际运行时的原字段 `resetOnEachMutedFrame: true`。它描述研究脚本对 VadState 的动作，不表示产品每个静音帧均执行 OrtSilero.reset。

固定 567 的 CallCapture 在每个完整 mute 帧调用 gate.reset 并跳过 consume；NeuralGate.reset 在 size==0 时立即返回。第一次确实清掉 size 后，后续连续静音帧不会再次调用 vad.reset。研究脚本在无推理、无重新填入样本的这十帧内，重复将已经全零的 input/state 和 used/probability 清零。对本次模型输入，重复动作与首次清空后保持零一致；不用于比较生产调用次数、分配量或耗时，也没有模拟完整 NeuralGate 的话轮与异步端点。

源码及所引程序原样保存在 source/，与原 JSON 的 sourceIdentity 对应。后续通用脚本仅将该元数据键改为 `harnessResetOnEachMutedFrame`，没有重跑本组模型。原始 JSON 的数值和 SHA 未改。其 400/393 次 Run、静音时舍弃的 256 个未满窗样本及末尾 128 个样本，均由原始记录与独审闭合。
