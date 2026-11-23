package io.github.ccch1mneyyy.dsh_app.root

import android.util.Base64
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.InputStream
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * The host side of root mode: every call is one `su -c <command>` process.
 *
 * Magisk, KernelSU and APatch all accept `su -c` with exactly one shell command (the form
 * [io.github.ccch1mneyyy.dsh_app.phone.background.RootCommands] already uses), so there is no
 * long-lived session to frame, re-sync or leak: a command that hangs is killed with its process,
 * and a command that kills the shell cannot strand the next call.
 *
 * Output is merged (`2>&1`) because a caller that asked for one command wants the order the
 * command printed it. A bounded buffer keeps `cat /dev/zero` from filling the phone's memory;
 * the flag travels back with the result so the model can tell a short answer from a cut one.
 */
class RootShell(private val log: (String) -> Unit = {}) {

    data class Result(
        val exit: Int,
        val output: String,
        val truncated: Boolean,
        val timedOut: Boolean,
        val error: String? = null,
    ) {
        fun toMap(): Map<String, Any?> = mapOf(
            "exit" to exit,
            "output" to output,
            "truncated" to truncated,
            "timedOut" to timedOut,
            "error" to error,
        )
    }

    data class Status(
        val available: Boolean,
        val manager: String,
        val version: String,
        val uid: Int,
        val suPath: String,
        val detail: String,
    ) {
        fun toMap(): Map<String, Any?> = mapOf(
            "available" to available,
            "manager" to manager,
            "version" to version,
            "uid" to uid,
            "suPath" to suPath,
            "detail" to detail,
        )
    }

    /**
     * Asks the manager for one `id`. This is the only call that may show the manager's own
     * authorization dialog, and it is only made from an explicit action (the switch, the test
     * button), never from a launch path.
     */
    fun probe(timeoutMs: Long = 30_000): Status {
        val su = suPath()
        if (su == null) {
            return Status(false, "none", "", -1, "", "su_missing")
        }
        val id = exec("id", timeoutMs = timeoutMs)
        val text = id.output
        val uid = Regex("""uid=(\d+)""").find(text)?.groupValues?.get(1)?.toIntOrNull() ?: -1
        if (uid != 0) {
            return Status(
                available = false,
                manager = manager(),
                version = version(su),
                uid = uid,
                suPath = su,
                detail = id.error ?: "not_granted",
            )
        }
        return Status(true, manager(), version(su), 0, su, "")
    }

    /**
     * `su` in the manager's own bin directory, else the one on PATH. Resolved without [exec]:
     * `exec` needs this path, and going through the shell here would recurse.
     */
    fun suPath(): String? {
        SU_PATHS.firstOrNull { File(it).canExecute() }?.let { return it }
        return runCatching {
            val process = ProcessBuilder("/system/bin/sh", "-c", "command -v su")
                .redirectErrorStream(true).start()
            val text = process.inputStream.bufferedReader().readText().trim()
            process.waitFor(4, TimeUnit.SECONDS)
            text
        }.getOrNull()?.lineSequence()?.firstOrNull { it.startsWith("/") }
    }

    private fun manager(): String = when {
        File("/data/adb/ksu").exists() || File("/data/adb/ksud").exists() -> MANAGER_KSU
        File("/data/adb/ap").exists() || File("/data/adb/apd").exists() -> MANAGER_APATCH
        File("/data/adb/magisk").exists() -> MANAGER_MAGISK
        else -> MANAGER_UNKNOWN
    }

    private fun version(su: String): String {
        val candidates = listOf(
            "$su -v",
            "$su --version",
            "/data/adb/ksu/bin/ksud -V",
            "/data/adb/ap/bin/apd -V",
            "/data/adb/magisk/magisk -V",
        )
        for (command in candidates) {
            val result = exec(command, timeoutMs = 4_000)
            val line = result.output.lineSequence().firstOrNull { it.isNotBlank() }?.trim()
            if (result.exit == 0 && !line.isNullOrBlank() && line.length <= 64) return line
        }
        return ""
    }

    /**
     * Runs [command] as root. [maxBytes] bounds the merged output; [timeoutMs] kills the process
     * tree when a command ignores its own limits.
     */
    fun exec(command: String, timeoutMs: Long = DEFAULT_TIMEOUT_MS, maxBytes: Int = DEFAULT_MAX_BYTES): Result {
        if (command.isBlank()) return Result(0, "", false, false)
        val su = suPath() ?: return Result(-1, "", false, false, "su_missing")
        val started = System.nanoTime()
        val process = try {
            ProcessBuilder(su, "-c", command).redirectErrorStream(true).start()
        } catch (e: Exception) {
            return Result(-1, "", false, false, "su_failed: ${e.message}")
        }
        val buffer = ByteArrayOutputStream()
        val truncated = java.util.concurrent.atomic.AtomicBoolean(false)
        val reader = thread(name = "dsh-root-read") {
            try {
                copyBounded(process.inputStream, buffer, maxBytes) { truncated.set(true) }
            } catch (_: Exception) {
            }
        }
        val finished = try {
            process.waitFor(timeoutMs, TimeUnit.MILLISECONDS)
        } catch (_: InterruptedException) {
            false
        }
        if (!finished) {
            runCatching { process.destroyForcibly() }
            runCatching { process.waitFor(2, TimeUnit.SECONDS) }
        }
        runCatching { reader.join(2_000) }
        val exit = runCatching { process.exitValue() }.getOrDefault(if (finished) -1 else 137)
        val text = buffer.toString("UTF-8")
        val result = Result(
            exit = if (finished) exit else 124,
            output = text,
            truncated = truncated.get(),
            timedOut = !finished,
            error = if (!finished) "timeout" else null,
        )
        log("[root] ${command.take(160)} → ${result.exit} in ${(System.nanoTime() - started) / 1_000_000}ms")
        return result
    }

    // ---- file helpers: toybox on the host, so they work on any Android 8+ ----

    fun read(path: String, maxBytes: Int = DEFAULT_MAX_BYTES): Map<String, Any?> {
        val stat = stat(path)
        if (stat["exists"] != true) return mapOf("ok" to false, "error" to "not_found")
        if (stat["type"] != "file") return mapOf("ok" to false, "error" to "not_a_file")
        val size = (stat["size"] as? Long) ?: 0L
        val limit = minOf(size, maxBytes.toLong()).coerceAtLeast(0)
        // `head -c` keeps a huge file from crossing the bridge at all; base64 keeps bytes intact.
        val result = exec("head -c $limit -- ${quote(path)} | base64", maxBytes = (limit * 4 / 3 + 4096).toInt())
        if (result.exit != 0) return mapOf("ok" to false, "error" to result.output.ifBlank { "read_failed" })
        val decoded = try {
            Base64.decode(result.output.filterNot { it.isWhitespace() }, Base64.DEFAULT)
        } catch (e: IllegalArgumentException) {
            return mapOf("ok" to false, "error" to "decode_failed")
        }
        return mapOf(
            "ok" to true,
            "base64" to Base64.encodeToString(decoded, Base64.NO_WRAP),
            "bytes" to decoded.size,
            "truncated" to (size > limit),
            "size" to size,
        )
    }

    fun write(path: String, base64: String, append: Boolean = false): Map<String, Any?> {
        val bytes = try {
            Base64.decode(base64, Base64.DEFAULT)
        } catch (e: IllegalArgumentException) {
            return mapOf("ok" to false, "error" to "decode_failed")
        }
        val dir = path.substringBeforeLast('/', "")
        if (dir.isNotEmpty()) exec("mkdir -p -- ${quote(dir)}")
        val redirect = if (append) ">>" else ">"
        var offset = 0
        var first = true
        while (offset < bytes.size || first) {
            val end = minOf(offset + CHUNK_BYTES, bytes.size)
            val chunk = Base64.encodeToString(bytes.copyOfRange(offset, end), Base64.NO_WRAP)
            val op = if (first) redirect else ">>"
            val result = exec("printf %s ${quote(chunk)} | base64 -d $op ${quote(path)}")
            if (result.exit != 0) return mapOf("ok" to false, "error" to result.output.ifBlank { "write_failed" })
            first = false
            offset = end
            if (bytes.isEmpty()) break
        }
        return mapOf("ok" to true, "bytes" to bytes.size)
    }

    fun stat(path: String): Map<String, Any?> {
        val result = exec("stat -c '%F|%s|%a|%u|%g|%Y' -- ${quote(path)}")
        if (result.exit != 0) return mapOf("exists" to false)
        val parts = result.output.trim().substringBefore('\n').split('|')
        if (parts.size < 6) return mapOf("exists" to false)
        val type = when {
            parts[0].contains("directory") -> "dir"
            parts[0].contains("regular") -> "file"
            parts[0].contains("symbolic") -> "link"
            else -> "other"
        }
        return mapOf(
            "exists" to true,
            "type" to type,
            "size" to (parts[1].toLongOrNull() ?: 0L),
            "mode" to parts[2],
            "uid" to (parts[3].toIntOrNull() ?: -1),
            "gid" to (parts[4].toIntOrNull() ?: -1),
            "mtime" to ((parts[5].toLongOrNull() ?: 0L) * 1000L),
        )
    }

    fun list(path: String): Map<String, Any?> {
        // `find -maxdepth 1` keeps the shell out of name parsing: one `stat` line per entry.
        val result = exec(
            "find ${quote(path)} -mindepth 1 -maxdepth 1 -exec stat -c '%n|%F|%s|%a|%Y' {} + 2>/dev/null | head -2000",
        )
        if (result.exit != 0) return mapOf("ok" to false, "error" to result.output.ifBlank { "list_failed" })
        val entries = result.output.lineSequence().mapNotNull { line ->
            val parts = line.split('|')
            if (parts.size < 5) return@mapNotNull null
            mapOf(
                "name" to parts[0].substringAfterLast('/'),
                "path" to parts[0],
                "type" to when {
                    parts[1].contains("directory") -> "dir"
                    parts[1].contains("symbolic") -> "link"
                    else -> "file"
                },
                "size" to (parts[2].toLongOrNull() ?: 0L),
                "mode" to parts[3],
                "mtime" to ((parts[4].toLongOrNull() ?: 0L) * 1000L),
            )
        }.toList()
        return mapOf("ok" to true, "entries" to entries, "truncated" to result.truncated)
    }

    private fun quote(value: String): String {
        require('\u0000' !in value && '\n' !in value) { "root: invalid path" }
        return "'" + value.replace("'", "'\\''") + "'"
    }

    private fun copyBounded(input: InputStream, out: ByteArrayOutputStream, maxBytes: Int, onTruncate: () -> Unit) {
        val buffer = ByteArray(16 * 1024)
        var total = 0
        while (true) {
            val read = input.read(buffer)
            if (read < 0) return
            val room = maxBytes - total
            if (room <= 0) {
                onTruncate()
                // Keep draining so the child does not block on a full pipe; drop the bytes.
                continue
            }
            val take = minOf(room, read)
            out.write(buffer, 0, take)
            total += take
            if (take < read) onTruncate()
        }
    }

    companion object {
        const val MANAGER_KSU = "kernelsu"
        const val MANAGER_MAGISK = "magisk"
        const val MANAGER_APATCH = "apatch"
        const val MANAGER_UNKNOWN = "unknown"

        const val DEFAULT_TIMEOUT_MS = 120_000L
        const val DEFAULT_MAX_BYTES = 4 * 1024 * 1024
        private const val CHUNK_BYTES = 48 * 1024

        private val SU_PATHS = listOf(
            "/system/bin/su",
            "/system/xbin/su",
            "/debug_ramdisk/su",
            "/sbin/su",
            "/data/adb/ksu/bin/su",
            "/data/adb/ap/bin/su",
        )
    }
}
