# 模型 Run 输入预处理

固定产品提交 `567390d1f943777ac8f8e9c3abbbbe346821e5d1`。本目录是主机研究入口。Kotlin 2.4.0 在同一模块中编译产品原件 `WhisperMel.kt` 与 `CompanionWordPiece.kt`，研究入口只负责读取文件、建立窗口/张量并写出 little-endian 载荷。文件清单每行按 tab 分隔四列，依次为输入名、float32/int64、逗号分隔的 shape、绝对文件路径。当前固定 BGE 图有三个输入。产品实现另允许只有两个输入的模型，此入口按已审图产生三个输入文件。

## 固定源码与工具

将上述提交的源码、受信任的 Kotlin 2.4.0 K2JVMCompiler 依赖、org.json:json:20240303、已核摘要的 tokenizer.json 放在本机。产品类路径如下。

- `app/android/app/src/main/kotlin/io/github/ccch1mneyyy/dsh_app/nativemedia/WhisperMel.kt`
- `app/android/app/src/main/kotlin/io/github/ccch1mneyyy/dsh_app/companion/CompanionWordPiece.kt`

`source-identity.json` 记录源码 Git blob / SHA、语义参考源、词表及本次主机运行工具身份。词表来自产品所用固定 tokenizer，构造时实际验证 21,128 个唯一 ID 及固定特殊标记。query 前缀、全 1 的 mask 与全 0 的 type 依据 `CompanionEmbeddingPlugin.kt:172–181`。

以下命令使用调用者指定的绝对目录。`ktjars` 指向编译器及其依赖 JAR，`private_work` 为私有临时目录，`research` 是本目录，`product` 是上述包目录（以 dsh_app 结尾）。所给示例使用 Linux/JDK 21。

```bash
mkdir -p "$private_work/classes"
stdlib="$ktjars/kotlin-stdlib-2.4.0.jar"
java -cp "$ktjars/*" org.jetbrains.kotlin.cli.jvm.K2JVMCompiler \
  -no-stdlib -no-reflect -classpath "$stdlib:$json_jar" \
  -d "$private_work/classes" "$product/nativemedia/WhisperMel.kt" \
  "$product/companion/CompanionWordPiece.kt" "$research/PrepareInputs.kt"
cp_run="$private_work/classes:$stdlib:$json_jar"
python3 "$research/fixture_cases.py" "$cp_run" "$vocab" \
  "$private_work/new-cases" > "$private_work/fixture-summary.json"
```

## 输入与已核对的边界

`mel` 读无头、单声道、16 kHz PCM16LE；采样率和声道是文件提供者的合同。第二个参数是从开头计的排他样本位置。研究入口将样本写入 128,000-short 环，保留最近 8 秒，较短段左侧填 0，按有符号 PCM16 / 32768f 归一化。每个保留样本都与原 PCM 对应下标核对，再调用产品 WhisperMel。此构造关注已给定时点的输入形状及窗口顺序；真实 NeuralGate 有话轮起点、预录音裁剪与 200 ms 静音触发等额外状态。研究脚本没有模拟真实会话何时提交端点。

```bash
java -cp "$cp_run" PrepareInputsKt mel "$pcm16le" "$end_sample_exclusive" "$private_work/new-mel"
java -cp "$cp_run" PrepareInputsKt bge "$vocab" "$utf8_file" query "$private_work/new-query"
```

`fixture-summary.json` 记录一次实际运行的输出摘要。1 秒全零、1 秒合成 PCM、完整 8 秒合成 PCM、9 秒合成 PCM 取末 8 秒均产生 [1,80,800]×float32，共 256,000 B；静音特征一致为 -1.5，四份摘要互异。BGE 空文档、同句文档/查询、混合中英文及标点/未知字符/五种特殊标记、512 个“中”分别得到长度 2、10、29、14、512，含头尾分隔符。混合文本内部的 [PAD] 仍遵循生产实现生成 1 的 mask；长文仅保留 510 个正文 token。摘要不包含完整 tensor。所有结果属于本次 JDK/Kotlin 主机预处理，模型推理与 Android 浮点/Unicode 实现均未在此步骤验证。
