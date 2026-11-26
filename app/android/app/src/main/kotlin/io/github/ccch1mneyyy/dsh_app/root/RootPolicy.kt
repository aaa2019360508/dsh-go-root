package io.github.ccch1mneyyy.dsh_app.root

import android.content.Context
import android.content.SharedPreferences
import java.util.Collections

/**
 * What the person allowed root mode to do.
 *
 * Root mode hands the engine a real `su` on the host, so the switch alone is not a policy: the
 * scope ([scope]: read / write / full), the confirmation level ([approval]) and — always — the
 * payment guard are read on every call, never cached in the bridge.
 */
class RootPolicy private constructor(private val prefs: SharedPreferences) {

    /** One audited command; [denied] carries why the app refused instead of running it. */
    data class Entry(val at: Long, val command: String, val exit: Int, val denied: String?, val durationMs: Long)

    /** Root mode on: the guest gets `su` / `sudo` / `dsh-root` and the bridge listens. */
    var enabled: Boolean
        get() = prefs.getBoolean(K_ENABLED, false)
        set(value) = prefs.edit().putBoolean(K_ENABLED, value).apply()

    /**
     * 三档访问范围：
     *  - [SCOPE_READ] 只读：写操作在调用 `su` 之前就被拒；
     *  - [SCOPE_WRITE] 读写：按 [approval] 确认危险命令；
     *  - [SCOPE_FULL] 完全权限：不再询问，命令直接执行（支付保护照旧生效）。
     */
    var scope: String
        get() = prefs.getString(K_SCOPE, null)
            ?: if (prefs.getBoolean(K_WRITE, true)) SCOPE_WRITE else SCOPE_READ
        set(value) = prefs.edit().putString(K_SCOPE, normalizeScope(value)).apply()

    /** 写操作是否放行（读写与完全权限都放行）。 */
    val writeAccess: Boolean get() = scope != SCOPE_READ

    /** 完全权限：不做确认，模型直接拿 root。 */
    val fullAccess: Boolean get() = scope == SCOPE_FULL

    /** [APPROVAL_OFF] (never ask), [APPROVAL_DANGER] (ask for destructive commands), [APPROVAL_ALWAYS]. */
    var approval: String
        get() = prefs.getString(K_APPROVAL, APPROVAL_DANGER) ?: APPROVAL_DANGER
        set(value) = prefs.edit().putString(K_APPROVAL, value).apply()

    /** The person already saw the warning once; the page does not open on it again. */
    var acknowledged: Boolean
        get() = prefs.getBoolean(K_ACK, false)
        set(value) = prefs.edit().putBoolean(K_ACK, value).apply()

    /**
     * Why [command] needs a tap, or null when the policy lets it through unasked.
     * 完全权限下永远是 null：那一档买的就是「不问」。
     */
    fun confirmReason(command: String): String? = confirmReasonFor(scope, approval, command)

    /** 只读档的命令行闸门：不是纯读就拒。 */
    fun execRefusal(command: String): String? = execRefusalFor(scope, command)

    companion object {
        const val APPROVAL_OFF = "off"
        const val APPROVAL_DANGER = "danger"
        const val APPROVAL_ALWAYS = "always"

        const val SCOPE_READ = "read"
        const val SCOPE_WRITE = "write"
        const val SCOPE_FULL = "full"

        private const val FILE = "dsh_root_mode"
        private const val K_ENABLED = "enabled"
        private const val K_WRITE = "write"
        private const val K_SCOPE = "scope"
        private const val K_APPROVAL = "approval"
        private const val K_ACK = "acknowledged"

        private var instance: RootPolicy? = null

        /** 确认判定本身是纯函数，放在这里才测得动（实例要 SharedPreferences）。 */
        fun confirmReasonFor(scope: String, approval: String, command: String): String? = when {
            normalizeScope(scope) == SCOPE_FULL -> null
            approval == APPROVAL_OFF -> null
            approval == APPROVAL_ALWAYS -> "always"
            else -> if (isDestructive(command)) "destructive" else null
        }

        fun execRefusalFor(scope: String, command: String): String? =
            if (normalizeScope(scope) == SCOPE_READ && !isReadOnly(command)) "read_only_scope" else null

        /** 未知值一律退回读写档：宁可多问一句，也不要意外放开。 */
        fun normalizeScope(value: String?): String = when (value) {
            SCOPE_READ, SCOPE_WRITE, SCOPE_FULL -> value
            else -> SCOPE_WRITE
        }

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
         * 完全权限下这里也放行，唯一还拦着的是 [PaymentGuard]。
         */
        fun scopeRefusal(op: String, scope: String): String? =
            if (op == "write" && normalizeScope(scope) == SCOPE_READ) "read_only_scope" else null

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
