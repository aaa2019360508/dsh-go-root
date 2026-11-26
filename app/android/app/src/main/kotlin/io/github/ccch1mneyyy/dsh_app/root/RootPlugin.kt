package io.github.ccch1mneyyy.dsh_app.root

import android.os.Handler
import android.os.Looper
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Flutter bridge for root mode: MethodChannel `dsh/root`, EventChannel `dsh/root/events`.
 *
 * The event stream carries two things: a confirmation request (the bridge worker is blocked until
 * the page answers with `approve`) and status snapshots after every change. `su` itself is slow and
 * may show the manager's dialog, so [refresh] and [exec] run off the platform thread.
 */
class RootPlugin : FlutterPlugin, MethodChannel.MethodCallHandler, EventChannel.StreamHandler, RootControl.Listener {

    private lateinit var methods: MethodChannel
    private lateinit var events: EventChannel
    private lateinit var control: RootControl
    private var sink: EventChannel.EventSink? = null
    private val main = Handler(Looper.getMainLooper())
    private val worker: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "dsh-root-ui").apply { isDaemon = true }
    }

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        control = RootControl.get(binding.applicationContext)
        methods = MethodChannel(binding.binaryMessenger, "dsh/root").also { it.setMethodCallHandler(this) }
        events = EventChannel(binding.binaryMessenger, "dsh/root/events").also { it.setStreamHandler(this) }
        control.attach(this)
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        control.detach(this)
        methods.setMethodCallHandler(null)
        events.setStreamHandler(null)
        sink = null
    }

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        sink = events
        events?.success(mapOf("type" to "status") + control.status())
    }

    override fun onCancel(arguments: Any?) {
        sink = null
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "status" -> result.success(control.status())
            "refresh" -> worker.execute { reply(result) { control.refresh() } }
            "setEnabled" -> {
                val enabled = call.argument<Any?>("enabled") == true
                worker.execute { reply(result) { control.setEnabled(enabled) } }
            }
            "setPolicy" -> {
                val scope = call.argument<String>("scope")
                val approval = call.argument<String>("approval")
                result.success(control.setPolicy(scope, approval))
            }
            "acknowledge" -> {
                control.acknowledge()
                result.success(control.status())
            }
            "exec" -> {
                val command = call.argument<String>("command") ?: ""
                val timeout = (call.argument<Number>("timeoutMs")?.toLong() ?: RootShell.DEFAULT_TIMEOUT_MS)
                worker.execute { reply(result) { control.runCommand(command, timeout) } }
            }
            "approve" -> {
                val id = call.argument<String>("id")
                val allow = call.argument<Any?>("allow") == true
                if (id == null) result.error("bad_args", "id is required", null)
                else {
                    control.approve(id, allow)
                    result.success(null)
                }
            }
            "clearLog" -> {
                control.clearLog()
                result.success(control.status())
            }
            else -> result.notImplemented()
        }
    }

    private inline fun reply(result: MethodChannel.Result, block: () -> Any?) {
        try {
            val value = block()
            main.post { result.success(value) }
        } catch (e: Exception) {
            main.post { result.error("root_failed", e.message ?: e.javaClass.simpleName, null) }
        }
    }

    // RootControl.Listener, always off the platform thread.

    override fun onConfirm(confirm: RootControl.Confirm) {
        main.post {
            sink?.success(
                mapOf(
                    "type" to "confirm",
                    "id" to confirm.id,
                    "command" to confirm.command,
                    "reason" to confirm.reason,
                ),
            )
        }
    }

    override fun onStatus(status: Map<String, Any?>) {
        main.post { sink?.success(mapOf("type" to "status") + status) }
    }
}
