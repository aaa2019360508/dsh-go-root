package io.github.ccch1mneyyy.dsh_app.root

import android.content.Context
import android.content.SharedPreferences
import java.util.Collections

/**
 * What the person allowed root mode to do.
 *
 * Root mode hands the engine a real `su` on the host, so the switch alone is not a policy: the
 * scope ([writeAccess]) and the confirmation level ([approval]) are stored next to it and are
 * read on every call, never cached in the bridge.
 */
class RootPolicy private constructor(private val prefs: SharedPreferences) {

    /** One audited command; [denied] carries why the app refused instead of running it. */
    data class Entry(val at: Long, val command: String, val exit: Int, val denied: String?, val durationMs: Long)

    /** Root mode on: the guest gets `su` / `sudo` / `dsh-root` and the bridge listens. */
    var enabled: Boolean
        get() = prefs.getBoolean(K_ENABLED, false)
        set(value) = prefs.edit().putBoolean(K_ENABLED, value).apply()

    /** Off: read-only commands run, anything that writes is refused before `su` is called. */
    var writeAccess: Boolean
        get() = prefs.getBoolean(K_WRITE, true)
        set(value) = prefs.edit().putBoolean(K_WRITE, value).apply()

    /** [APPROVAL_OFF] (never ask), [APPROVAL_DANGER] (ask for destructive commands), [APPROVAL_ALWAYS]. */
    var approval: String
        get() = prefs.getString(K_APPROVAL, APPROVAL_DANGER) ?: APPROVAL_DANGER
        set(value) = prefs.edit().putString(K_APPROVAL, value).apply()

    /** The person already saw the warning once; the page does not open on it again. */
    var acknowledged: Boolean
        get() = prefs.getBoolean(K_ACK, false)
        set(value) = prefs.edit().putBoolean(K_ACK, value).apply()

    /** Why [command] needs a tap, or null when the policy lets it through unasked. */
    fun confirmReason(command: String): String? = when (approval) {
        APPROVAL_OFF -> null
        APPROVAL_ALWAYS -> "always"
        else -> if (isDestructive(command)) "destructive" else null
    }

    companion object {
        const val APPROVAL_OFF = "off"
        const val APPROVAL_DANGER = "danger"
        const val APPROVAL_ALWAYS = "always"

        private const val FILE = "dsh_root_mode"
        private const val K_ENABLED = "enabled"
        private const val K_WRITE = "write"
        private const val K_APPROVAL = "approval"
        private const val K_ACK = "acknowledged"

        private var instance: RootPolicy? = null

        fun get(context: Context): RootPolicy = synchronized(this) {
            instance ?: RootPolicy(context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE))
                .also { instance = it }
        }

        /**
         * Commands whose blast radius is not visible in their output: partitioning, wiping a
         * package, rewriting a system setting, remounting, loading a module. This is a hint for the
         * confirmation prompt, not a sandbox — [RootShell] runs whatever it is given.
         */
        private val DESTRUCTIVE = listOf(
            Regex("""\bmkfs(\.\w+)?\b"""),
            Regex("""\bdd\b[^|;&]*\bof=/dev/(block|sd|mmcblk)"""),
            Regex(""">\s*/dev/block/"""),
            Regex("""\bmount\s+-o\s+(re)?mount"""),
            Regex("""\bumount\s+/(data|system|vendor)\b"""),
            Regex("""\bpm\s+(uninstall|clear)\b"""),
            Regex("""\bcmd\s+package\s+(uninstall|clear)\b"""),
            Regex("""\bsettings\s+(put|delete)\b"""),
            Regex("""\b(chmod|chown)\s+(-[a-zA-Z]+\s+)*[0-7]{3,4}\s+(-[a-zA-Z]+\s+)*/(data|system)\s*$"""),
            Regex("""\bwipe\b|\breboot\b|\bpoweroff\b|\bhalt\b"""),
            Regex("""\bflash\b|\bfastboot\b|\bedl\b"""),
            Regex("""\binsmod\b|\brmmod\b|\bmagisk\s+(--remove-modules|--install-module)"""),
            Regex("""\bksud\b|\bmagisk\b.*\bmodule\b"""),
            Regex("""\b(curl|wget)\b[^|]*\|\s*(sh|bash|su)\b"""),
            Regex("""\bshred\b|\btruncate\s+-s\s*0\b"""),
        )

        /** Paths a delete must not touch: system trees and every app's private data. */
        private val SENSITIVE_ROOTS = setOf("/", "/data", "/system", "/sdcard", "/storage", "/vendor", "/product", "/metadata")
        private val SENSITIVE_PREFIXES = listOf(
            "/data/data", "/data/system", "/data/adb", "/data/misc", "/data/user", "/data/app",
            "/data/vendor", "/data/property", "/data/dalvik-cache", "/system/", "/vendor/", "/product/",
        )

        /** Scratch and shared storage: an agent may clean these up without asking. */
        private val ROUTINE_PREFIXES = listOf("/data/local/tmp", "/data/media", "/sdcard/Download/DSH-Go", "/sdcard/Download/DSH-")

        private fun isSensitivePath(raw: String): Boolean {
            val trimmed = raw.trim().trim('\'', '"')
            // A bare "/" is the worst target there is; trimming its slash would make it empty.
            val path = if (trimmed.length > 1) trimmed.trimEnd('/') else trimmed
            if (path.isEmpty()) return false
            if (ROUTINE_PREFIXES.any { path == it || path.startsWith("$it/") }) return false
            if (path in SENSITIVE_ROOTS) return true
            if (path == "/data/*" || path == "/system/*" || path == "/sdcard/*") return true
            return SENSITIVE_PREFIXES.any { path == it.trimEnd('/') || path.startsWith(it) }
        }

        /** The targets of every `rm` in [text], across `;`, `&&` and pipelines. */
        private fun rmTargets(text: String): List<String> = text
            .split(Regex("""\|\||&&|[;|]"""))
            .map { it.trim().removePrefix("sudo ").trim() }
            .filter { it.startsWith("rm ") || it == "rm" }
            .flatMap { segment -> segment.split(' ').drop(1).filterNot { it.startsWith("-") } }

        fun isDestructive(command: String): Boolean {
            val text = command.replace('\n', ' ')
            if (DESTRUCTIVE.any { it.containsMatchIn(text) }) return true
            return rmTargets(text).any { isSensitivePath(it) }
        }

        /** Read-only commands that stay allowed when the person turned write access off. */
        private val READ_ONLY = setOf(
            "ls", "ll", "cat", "head", "tail", "grep", "rg", "find", "stat", "file", "du", "df",
            "wc", "sort", "uniq", "cut", "tr", "sed", "awk", "strings", "md5sum", "sha256sum",
            "sha1sum", "base64", "id", "whoami", "uname", "getprop", "ps", "top", "free", "uptime",
            "date", "echo", "printf", "pwd", "readlink", "realpath", "which", "type", "env", "mount",
            "dumpsys", "logcat", "cmd", "pm", "am", "test", "[", "true", "false", "sleep", "cmp",
            "diff", "tree", "zipinfo", "unzip", "tar", "gzip", "zcat", "xxd", "od", "hexdump",
        )

        /**
         * Whether [command] only reads. A command that writes, redirects, chains into a writer or
         * starts a shell counts as a write; the answer errs towards "write" because the cost of a
         * false negative is a silent modification of /data.
         */
        fun isReadOnly(command: String): Boolean {
            val text = command.trim()
            if (text.isEmpty()) return true
            if (Regex("""[>]{1,2}\s*[^&\s]""").containsMatchIn(text)) return false
            if (Regex("""(^|\s)(-delete|-exec|-execdir)\b""").containsMatchIn(text)) return false
            if (Regex("""\b(touch|mkdir|rmdir|mv|cp|ln|install|tee|dd|chmod|chown|truncate|sed\s+-i|git\s+)\b""")
                    .containsMatchIn(text)
            ) return false
            // Split on shell separators; every segment has to start with a reader.
            val segments = text.split(Regex("""\|\||&&|[;|]""")).map { it.trim() }.filter { it.isNotEmpty() }
            if (segments.isEmpty()) return true
            return segments.all { segment ->
                val head = segment.trimStart('(', ' ').substringBefore(' ').substringAfterLast('/')
                // `su`, `sh -c`, `bash -c`, `xargs`, `find -exec`: a writer we cannot see into.
                if (head in setOf("su", "sh", "bash", "xargs", "eval", "exec", "env", "nohup", "watch")) false
                else head in READ_ONLY
            }
        }

        /**
         * The scope gate for the file channel. [isReadOnly] answers for shell command lines;
         * `dsh-root write` is an operation rather than a command line, so it is decided here —
         * otherwise the read-only switch would stop `echo > file` but not the file channel.
         */
        fun scopeRefusal(op: String, writeAccess: Boolean): String? =
            if (op == "write" && !writeAccess) "read_only_scope" else null

        /** Newest-first audit trail, in memory only: it is a debugging aid, not a log file. */
        private const val LOG_LIMIT = 200
        private val log = Collections.synchronizedList(ArrayList<Entry>())

        fun record(entry: Entry) {
            log.add(0, entry)
            while (log.size > LOG_LIMIT) log.removeAt(log.size - 1)
        }

        fun entries(limit: Int = 50): List<Map<String, Any?>> = synchronized(log) {
            log.take(limit).map {
                mapOf(
                    "at" to it.at,
                    "command" to it.command,
                    "exit" to it.exit,
                    "denied" to it.denied,
                    "durationMs" to it.durationMs,
                )
            }
        }

        fun clearLog() = log.clear()
    }
}
