import io.github.ccch1mneyyy.dsh_app.companion.CompanionWordPiece
import io.github.ccch1mneyyy.dsh_app.nativemedia.WhisperMel
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

private fun target(directory: String): File {
    val folder = File(directory).absoluteFile
    require(folder.mkdir()) { "Output must be a new directory under an existing parent: $folder" }
    return folder
}

private fun prepareMel(pcmFile: File, end: Int, directory: String) {
    val raw = pcmFile.readBytes()
    require(raw.size % 2 == 0 && end in 0..raw.size / 2)
    val pcm = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
    val ring = ShortArray(WhisperMel.SAMPLES)
    var next = 0
    for (i in 0 until end) {
        ring[next] = pcm.get(i)
        if (++next == ring.size) next = 0
    }
    val count = minOf(end, ring.size)
    var first = (next - count + ring.size) % ring.size
    val snapshot = FloatArray(ring.size)
    for (i in 0 until count) {
        val sample = ring[first]
        check(sample == pcm.get(end - count + i))
        snapshot[snapshot.size - count + i] = sample / 32768f
        if (++first == ring.size) first = 0
    }
    val features = WhisperMel().compute(snapshot)
    check(features.size == 80 * 800 && features.all { it.isFinite() })
    val bytes = ByteBuffer.allocate(features.size * Float.SIZE_BYTES).order(ByteOrder.LITTLE_ENDIAN)
    bytes.asFloatBuffer().put(features)
    val out = target(directory)
    val tensor = File(out, "input_features.f32le")
    tensor.writeBytes(bytes.array())
    File(out, "input.tsv").writeText("input_features\tfloat32\t1,80,800\t${tensor.path}\n")
}

private fun prepareBge(vocab: File, textFile: File, mode: String, directory: String) {
    val text = textFile.readText(Charsets.UTF_8)
    val prefix = when (mode) {
        "query" -> "为这个句子生成表示以用于检索相关文章："
        "document" -> ""
        else -> error("Expected query or document")
    }
    val ids = CompanionWordPiece(vocab.readText(Charsets.UTF_8)).encode(prefix + text)
    val out = target(directory)
    val manifest = buildString {
        fun tensor(name: String, values: LongArray) {
            val bytes = ByteBuffer.allocate(values.size * Long.SIZE_BYTES).order(ByteOrder.LITTLE_ENDIAN)
            bytes.asLongBuffer().put(values)
            val file = File(out, "$name.i64le")
            file.writeBytes(bytes.array())
            append("$name\tint64\t1,${values.size}\t${file.path}\n")
        }
        tensor("input_ids", ids)
        tensor("attention_mask", LongArray(ids.size) { 1L })
        tensor("token_type_ids", LongArray(ids.size))
    }
    File(out, "input.tsv").writeText(manifest)
}

fun main(args: Array<String>) {
    when (args.firstOrNull()) {
        "mel" -> {
            require(args.size == 4) { "mel INPUT.pcm16le END_SAMPLE OUTPUT_DIR" }
            prepareMel(File(args[1]), args[2].toInt(), args[3])
        }
        "bge" -> {
            require(args.size == 5) { "bge tokenizer.json input.txt query|document OUTPUT_DIR" }
            prepareBge(File(args[1]), File(args[2]), args[3], args[4])
        }
        else -> error("Expected mel or bge")
    }
}
