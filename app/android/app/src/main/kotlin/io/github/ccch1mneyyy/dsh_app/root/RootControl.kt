package io.github.ccch1mneyyy.dsh_app.root

import android.content.Context
import java.io.File
import java.util.UUID
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

/**
 * Root mode, one owner for the whole app: the switch, the bridge the guest talks to, the shell
 * that runs `su`, and the queue of commands waiting for a tap.
 *
 * [RuntimeController] calls [prepareLaunch] before the engine starts and [onEngineStopped] when it
 * goes away, so the guest only ever sees shims while an engine is running under a listening
 * bridge. Nothing here runs `su` on its own: [refresh] is the only probe, and only the page or the
 * switch asks for it, because that call can show the manager's own authorization dialog.
 */
class RootControl private constructor(private val app: Context) {

    data class Confirm(val id: String, val command: String, val reason: String)

    interface Listener {
        /** Asked on a bridge worker; [approve] has to be called for the worker to continue. */
        fun onConfirm(confirm: Confirm)
        fun onStatus(status: Map<String, Any?>)
    }

    private val policy = RootPolicy.get(app)
    private val shell = RootShell { line -> log(line) }
    private val bridge = RootBridge(policy, shell, ::log, ::confirm)
    private val pending = ConcurrentHashMap<String, ArrayBlockingQueue<Boolean>>()

    @Volatile private var listener: Listener? = null
    @Volatile private var lastStatus: RootShell.Status? = null
    @Volatile private var rootfs: File? = null
    private val lines = ArrayList<String>()

    fun attach(listener: Listener) { this.listener = listener }

    fun detach(listener: Listener) {
        if (this.listener === listener) this.listener = null
    }

    /** Called by the engine launcher with the rootfs it is about to use. */
    fun prepareLaunch(rootfs: File): Boolean {
        this.rootfs = rootfs
        if (!policy.enabled) {
            RootGuest.prepare(rootfs, null, false)
            bridge.stop()
            return false
        }
        val endpoint = try {
            if (bridge.listening) bridge.endpoint else bridge.start()
        } catch (e: Exception) {
            log("[dsh-app] root mode: bridge failed: ${e.message}")
            return false
        }
        val ok = RootGuest.prepare(rootfs, endpoint, true)
        if (!ok) log("[dsh-app] root mode: guest files not written; the engine runs without su")
        return ok
    }

    fun onEngineStopped() {
        bridge.stop()
    }

    // ---- page / switch ----

    fun status(): Map<String, Any?> = buildMap {
        put("enabled", policy.enabled)
        put("writeAccess", policy.writeAccess)
        put("approval", policy.approval)
        put("acknowledged", policy.acknowledged)
        put("listening", bridge.listening)
        put("requests", bridge.requests)
        lastStatus?.let { status ->
            put("available", status.available)
            put("manager", status.manager)
            put("version", status.version)
            put("uid", status.uid)
            put("suPath", status.suPath)
            put("detail", status.detail)
        }
        put("logs", RootPolicy.entries())
        put("messages", logs())
    }

    /** Runs `su -c id` and remembers the answer; the manager may show its own dialog here. */
    fun refresh(): Map<String, Any?> {
        val status = shell.probe()
        lastStatus = status
        publish()
        return status.toMap()
    }

    fun setEnabled(enabled: Boolean): Map<String, Any?> {
        policy.enabled = enabled
        if (enabled) {
            policy.acknowledged = true
            val status = shell.probe()
            lastStatus = status
            val target = rootfs ?: runCatching {
                io.github.ccch1mneyyy.dsh_app.runtime.RuntimeController.get(app).rootfsForRootMode()
            }.getOrNull()
            if (target != null) prepareLaunch(target)
        } else {
            bridge.stop()
            pending.keys.toList().forEach { id -> pending.remove(id)?.offer(false) }
            rootfs?.let { RootGuest.prepare(it, null, false) }
        }
        publish()
        return status()
    }

    fun setPolicy(writeAccess: Boolean? = null, approval: String? = null): Map<String, Any?> {
        writeAccess?.let { policy.writeAccess = it }
        approval?.let { if (it in setOf(RootPolicy.APPROVAL_OFF, RootPolicy.APPROVAL_DANGER, RootPolicy.APPROVAL_ALWAYS)) policy.approval = it }
        publish()
        return status()
    }

    fun acknowledge() {
        policy.acknowledged = true
        publish()
    }

    fun approve(id: String, allow: Boolean) {
        pending.remove(id)?.offer(allow)
    }

    fun clearLog() {
        RootPolicy.clearLog()
        publish()
    }

    /** A command typed by the person on the page: no confirmation, but the scope still applies. */
    fun runCommand(command: String, timeoutMs: Long = RootShell.DEFAULT_TIMEOUT_MS): Map<String, Any?> {
        if (command.isBlank()) return mapOf("exit" to -1, "output" to "", "error" to "empty_command")
        if (!policy.writeAccess && !RootPolicy.isReadOnly(command)) {
            return mapOf("exit" to -1, "output" to "", "error" to "read_only_scope")
        }
        val result = shell.runCommand(command, timeoutMs)
        publish()
        return result.toMap()
    }

    private fun confirm(command: String, reason: String): Boolean {
        val target = listener ?: return false
        val id = UUID.randomUUID().toString()
        val queue = ArrayBlockingQueue<Boolean>(1)
        pending[id] = queue
        try {
            target.onConfirm(Confirm(id, command, reason))
            return queue.poll(CONFIRM_TIMEOUT_MS, TimeUnit.MILLISECONDS) ?: false
        } catch (_: InterruptedException) {
            return false
        } finally {
            pending.remove(id)
        }
    }

    private fun publish() {
        listener?.onStatus(status())
    }

    private fun log(line: String) {
        android.util.Log.i("dsh-root", line)
        synchronized(lines) {
            lines.add(0, line)
            while (lines.size > 200) lines.removeAt(lines.size - 1)
        }
    }

    /** Newest first; the page shows these, and the engine log keeps its own copy. */
    fun logs(limit: Int = 100): List<String> = synchronized(lines) { lines.take(limit) }

    companion object {
        private const val CONFIRM_TIMEOUT_MS = 60_000L

        @Volatile private var instance: RootControl? = null

        fun get(context: Context): RootControl = synchronized(this) {
            instance ?: RootControl(context.applicationContext).also { instance = it }
        }

        /** True when the guest should be told root mode is on at this launch. */
        fun enabled(context: Context): Boolean = get(context).policy.enabled
    }
}
