package io.github.ccch1mneyyy.dsh_app.root

import android.net.LocalServerSocket
import android.net.LocalSocket
import android.os.Process
import android.system.Os
import android.system.OsConstants
import io.github.ccch1mneyyy.dsh_app.phone.Json
import java.io.ByteArrayOutputStream
import java.io.Closeable
import java.io.InputStream
import java.io.OutputStream
import java.security.SecureRandom
import java.util.Collections
import java.util.concurrent.Executors
import java.util.concurrent.Semaphore
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/**
 * The guest side of root mode: an abstract-namespace unix socket that `/usr/local/bin/dsh-root`
 * (and the `su` / `sudo` shims) connect to from inside PRoot. proot passes abstract addresses
 * through untranslated, so the same socket works for the guest and for the app.
 *
 * Trust model, the same one the phone bridge states: the connection must come from this app's uid
 * and carry this launch's token, but anything inside the rootfs runs as that uid — so the token is
 * not a boundary between the model and the person, it only keeps other apps out. The real gate is
 * [RootPolicy] and the confirmation the person sees.
 *
 * One request per connection: `dsh-root exec ...` is one process, so there is no session to
 * multiplex, and a hung request cannot block the next one.
 */
class RootBridge(
    private val policy: RootPolicy,
    private val shell: RootShell,
    private val log: (String) -> Unit,
    /** Returns true when the person allowed this command; called off the main thread. */
    private val confirm: (command: String, reason: String) -> Boolean,
) {
    data class Endpoint(val abstractName: String, val token: String)

    @Volatile private var running = false
    private var server: LocalServerSocket? = null
    private val open = Collections.synchronizedSet(HashSet<Closeable>())
    private val workers = Executors.newFixedThreadPool(MAX_CONCURRENCY) { r ->
        Thread(r, "dsh-root-call").apply { isDaemon = true }
    }
    private val slots = Semaphore(MAX_CONNECTIONS)
    private val served = AtomicInteger()

    @Volatile var endpoint: Endpoint? = null
        private set

    val listening: Boolean get() = running
    val requests: Int get() = served.get()

    @Synchronized
    fun start(): Endpoint {
        stop()
        val token = hex(32)
        var name: String? = null
        var lastError: Exception? = null
        for (attempt in 0 until 3) {
            val candidate = "dsh-app.root." + hex(8)
            try {
                server = LocalServerSocket(candidate)
                name = candidate
                break
            } catch (e: Exception) {
                lastError = e
            }
        }
        if (name == null) throw IllegalStateException("root bridge: cannot bind (${lastError?.message})")
        running = true
        val ep = Endpoint(name, token)
        endpoint = ep
        server?.let { s -> thread(name = "dsh-root-accept", isDaemon = true) { accept(s, token) } }
        log("[dsh-app] root bridge listening on @$name")
        return ep
    }

    @Synchronized
    fun stop() {
        running = false
        endpoint = null
        server?.let { s ->
            runCatching { Os.shutdown(s.fileDescriptor, OsConstants.SHUT_RDWR) }
            runCatching { s.close() }
        }
        server = null
        synchronized(open) {
            open.forEach { runCatching { it.close() } }
            open.clear()
        }
    }

    private fun current(token: String) = running && endpoint?.token == token

    private fun accept(s: LocalServerSocket, token: String) {
        while (current(token)) {
            val socket: LocalSocket = try {
                s.accept()
            } catch (e: Exception) {
                if (current(token)) log("[dsh-app] root bridge: accept failed: ${e.message}")
                return
            }
            if (!current(token)) {
                runCatching { socket.close() }
                return
            }
            val uid = try {
                socket.peerCredentials.uid
            } catch (_: Exception) {
                -1
            }
            if (uid != Process.myUid()) {
                log("[dsh-app] root bridge: refused a connection from uid $uid")
                runCatching { socket.close() }
                continue
            }
            if (!slots.tryAcquire()) {
                runCatching { socket.close() }
                continue
            }
            synchronized(open) { open += socket }
            workers.execute { serve(socket, token) }
        }
    }

    private fun serve(socket: LocalSocket, token: String) {
        try {
            socket.soTimeout = READ_TIMEOUT_MS
            val input = java.io.BufferedInputStream(socket.inputStream)
            val output = socket.outputStream
            val line = readLine(input, MAX_LINE) ?: return
            val request = try {
                Json.parse(line) as? Map<*, *>
            } catch (_: Exception) {
                null
            }
            if (request == null || request["token"] != token) {
                log("[dsh-app] root bridge: bad token, connection closed")
                return
            }
            if (!current(token)) return
            if (!policy.enabled) {
                reply(output, mapOf("end" to true, "ok" to false, "error" to "root_mode_off"))
                return
            }
            served.incrementAndGet()
            when (val op = request["op"] as? String) {
                "exec" -> handleExec(output, request)
                "read" -> end(
                    output,
                    shell.read(
                        str(request["path"]) ?: "",
                        (int(request["maxBytes"]) ?: RootShell.DEFAULT_MAX_BYTES)
                            .coerceIn(1, RootShell.DEFAULT_MAX_BYTES),
                    ),
                )
                "write" -> handleWrite(output, request)
                "list" -> end(output, shell.list(str(request["path"]) ?: "/"))
                "stat" -> end(output, shell.stat(str(request["path"]) ?: "/"))
                "info" -> end(output, statusMap())
                else -> reply(output, mapOf("end" to true, "ok" to false, "error" to "unknown_op: $op"))
            }
        } catch (e: Exception) {
            log("[dsh-app] root bridge: ${e.javaClass.simpleName}: ${e.message}")
        } finally {
            open -= socket
            runCatching { socket.close() }
            slots.release()
        }
    }

    private fun handleExec(output: OutputStream, request: Map<*, *>) {
        val command = str(request["cmd"])?.trim().orEmpty()
        if (command.isEmpty()) {
            reply(output, mapOf("end" to true, "ok" to false, "error" to "empty_command"))
            return
        }
        val started = System.nanoTime()
        if (!policy.writeAccess && !RootPolicy.isReadOnly(command)) {
            RootPolicy.record(RootPolicy.Entry(System.currentTimeMillis(), command, -1, "read_only", 0))
            reply(output, mapOf("end" to true, "ok" to false, "exit" to -1, "error" to "read_only_scope"))
            return
        }
        policy.confirmReason(command)?.let { reason ->
            val allowed = try {
                confirm(command, reason)
            } catch (_: Exception) {
                false
            }
            if (!allowed) {
                RootPolicy.record(RootPolicy.Entry(System.currentTimeMillis(), command, -1, "denied", 0))
                reply(output, mapOf("end" to true, "ok" to false, "exit" to -1, "error" to "denied_by_person"))
                return
            }
        }
        val timeout = (int(request["timeoutMs"]) ?: RootShell.DEFAULT_TIMEOUT_MS.toInt())
            .coerceIn(1_000, MAX_TIMEOUT_MS.toInt()).toLong()
        val maxBytes = (int(request["maxBytes"]) ?: RootShell.DEFAULT_MAX_BYTES).coerceIn(4_096, RootShell.DEFAULT_MAX_BYTES)
        val result = shell.runCommand(command, timeout, maxBytes)
        RootPolicy.record(
            RootPolicy.Entry(
                System.currentTimeMillis(), command, result.exit, result.error,
                (System.nanoTime() - started) / 1_000_000,
            ),
        )
        // Chunked so a 4 MB answer does not become one line the reader has to buffer whole.
        var offset = 0
        while (offset < result.output.length) {
            val end = minOf(offset + CHUNK_CHARS, result.output.length)
            reply(output, mapOf("out" to result.output.substring(offset, end)))
            offset = end
        }
        reply(
            output,
            mapOf(
                "end" to true,
                "ok" to (result.error == null),
                "exit" to result.exit,
                "truncated" to result.truncated,
                "timedOut" to result.timedOut,
                "error" to result.error,
            ),
        )
    }

    /**
     * `dsh-root write` never goes through [RootPolicy.isReadOnly], so the read-only scope and the
     * confirmation level have to be applied here — otherwise the switch would only stop the
     * commands that look like writes, and the file channel would write anyway.
     */
    private fun handleWrite(output: OutputStream, request: Map<*, *>) {
        val path = str(request["path"]).orEmpty()
        if (path.isBlank()) {
            reply(output, mapOf("end" to true, "ok" to false, "error" to "empty_path"))
            return
        }
        RootPolicy.scopeRefusal("write", policy.writeAccess)?.let { refusal ->
            RootPolicy.record(RootPolicy.Entry(System.currentTimeMillis(), "dsh-root write $path", -1, "read_only", 0))
            reply(output, mapOf("end" to true, "ok" to false, "error" to refusal))
            return
        }
        val probe = "dsh-root write $path"
        policy.confirmReason(probe)?.let { reason ->
            val allowed = try {
                confirm(probe, reason)
            } catch (_: Exception) {
                false
            }
            if (!allowed) {
                RootPolicy.record(RootPolicy.Entry(System.currentTimeMillis(), probe, -1, "denied", 0))
                reply(output, mapOf("end" to true, "ok" to false, "error" to "denied_by_person"))
                return
            }
        }
        val started = System.nanoTime()
        val result = shell.write(path, str(request["base64"]) ?: "", request["append"] == true)
        RootPolicy.record(
            RootPolicy.Entry(
                System.currentTimeMillis(), probe,
                if (result["ok"] == true) 0 else -1,
                result["error"] as? String,
                (System.nanoTime() - started) / 1_000_000,
            ),
        )
        end(output, result)
    }

    fun statusMap(): Map<String, Any?> = mapOf(
        "enabled" to policy.enabled,
        "writeAccess" to policy.writeAccess,
        "approval" to policy.approval,
        "listening" to listening,
        "requests" to served.get(),
    )

    private fun end(output: OutputStream, result: Map<String, Any?>) =
        reply(output, result + mapOf("end" to true))

    private fun reply(output: OutputStream, value: Map<String, Any?>) {
        synchronized(output) {
            output.write((Json.write(value) + "\n").toByteArray(Charsets.UTF_8))
            output.flush()
        }
    }

    private fun str(value: Any?): String? = value as? String
    private fun int(value: Any?): Int? = (value as? Number)?.toInt()

    private fun readLine(input: InputStream, limit: Int): String? {
        val buffer = ByteArrayOutputStream()
        while (true) {
            val b = input.read()
            if (b < 0) return if (buffer.size() == 0) null else buffer.toString("UTF-8")
            if (b == '\n'.code) return buffer.toString("UTF-8")
            if (buffer.size() >= limit) return null
            buffer.write(b)
        }
    }

    private fun hex(bytes: Int): String {
        val random = SecureRandom()
        val data = ByteArray(bytes)
        random.nextBytes(data)
        return data.joinToString("") { "%02x".format(it) }
    }

    companion object {
        const val MAX_CONNECTIONS = 8
        const val MAX_CONCURRENCY = 4
        const val MAX_TIMEOUT_MS = 10 * 60 * 1000L
        private const val READ_TIMEOUT_MS = 15_000
        private const val MAX_LINE = 8 * 1024 * 1024
        private const val CHUNK_CHARS = 64 * 1024
    }
}
