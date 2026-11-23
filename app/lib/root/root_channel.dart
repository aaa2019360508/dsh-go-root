// Root mode (Android): the app runs `su` on the phone and hands the guest a `sudo` / `su` shim.
// This file is the only place that knows the channel's shape; the page and the state above it
// deal in [RootStatus] and [RootExecResult].

import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';

/// What the phone's root manager answered the last time we asked.
class RootStatus {
  const RootStatus({
    this.enabled = false,
    this.available = false,
    this.manager = 'unknown',
    this.version = '',
    this.uid = -1,
    this.suPath = '',
    this.detail = '',
    this.writeAccess = true,
    this.approval = RootApproval.danger,
    this.acknowledged = false,
    this.listening = false,
    this.requests = 0,
    this.logs = const [],
    this.messages = const [],
  });

  /// The person turned the switch on.
  final bool enabled;

  /// `su -c id` came back as uid 0.
  final bool available;

  /// `kernelsu`, `magisk`, `apatch` or `unknown`.
  final String manager;
  final String version;
  final int uid;
  final String suPath;

  /// `su_missing`, `not_granted`, `timeout`, or empty.
  final String detail;

  /// Off: commands that write are refused before `su` runs.
  final bool writeAccess;
  final RootApproval approval;
  final bool acknowledged;

  /// The bridge the guest talks to is listening.
  final bool listening;

  /// Commands served to the guest since the engine started.
  final int requests;

  /// Audit trail: command, exit code, whether it was refused.
  final List<RootLogEntry> logs;

  /// Bridge and shell messages for the diagnostics card.
  final List<String> messages;

  static RootStatus fromMap(Map<Object?, Object?> map) {
    T? pick<T>(String key) => map[key] is T ? map[key] as T : null;
    final logs = <RootLogEntry>[];
    final raw = map['logs'];
    if (raw is List) {
      for (final item in raw) {
        if (item is Map) logs.add(RootLogEntry.fromMap(item));
      }
    }
    final messages = <String>[];
    final rawMessages = map['messages'];
    if (rawMessages is List) {
      for (final item in rawMessages) {
        if (item is String) messages.add(item);
      }
    }
    return RootStatus(
      enabled: pick<bool>('enabled') ?? false,
      available: pick<bool>('available') ?? false,
      manager: pick<String>('manager') ?? 'unknown',
      version: pick<String>('version') ?? '',
      uid: pick<int>('uid') ?? -1,
      suPath: pick<String>('suPath') ?? '',
      detail: pick<String>('detail') ?? '',
      writeAccess: pick<bool>('writeAccess') ?? true,
      approval: RootApproval.parse(pick<String>('approval')),
      acknowledged: pick<bool>('acknowledged') ?? false,
      listening: pick<bool>('listening') ?? false,
      requests: pick<int>('requests') ?? 0,
      logs: logs,
      messages: messages,
    );
  }
}

enum RootApproval {
  /// Never ask; the switch is the only gate.
  off('off'),

  /// Ask for commands whose blast radius the app can see (deleting /data, flashing, wiping).
  danger('danger'),

  /// Ask for every root command.
  always('always');

  const RootApproval(this.wire);

  final String wire;

  static RootApproval parse(String? value) =>
      RootApproval.values.firstWhere((item) => item.wire == value, orElse: () => RootApproval.danger);
}

class RootLogEntry {
  const RootLogEntry({required this.at, required this.command, required this.exit, this.denied, this.durationMs = 0});

  final DateTime at;
  final String command;
  final int exit;

  /// `read_only_scope`, `denied`, `timeout`… when the app refused instead of running it.
  final String? denied;
  final int durationMs;

  static RootLogEntry fromMap(Map<Object?, Object?> map) {
    final millis = map['at'] is int ? map['at'] as int : 0;
    return RootLogEntry(
      at: DateTime.fromMillisecondsSinceEpoch(millis),
      command: map['command'] is String ? map['command'] as String : '',
      exit: map['exit'] is int ? map['exit'] as int : -1,
      denied: map['denied'] is String ? map['denied'] as String : null,
      durationMs: map['durationMs'] is int ? map['durationMs'] as int : 0,
    );
  }
}

class RootExecResult {
  const RootExecResult({this.exit = -1, this.output = '', this.truncated = false, this.timedOut = false, this.error});

  final int exit;
  final String output;
  final bool truncated;
  final bool timedOut;
  final String? error;

  bool get ok => error == null && exit == 0;

  static RootExecResult fromMap(Map<Object?, Object?> map) => RootExecResult(
    exit: map['exit'] is int ? map['exit'] as int : -1,
    output: map['output'] is String ? map['output'] as String : '',
    truncated: map['truncated'] == true,
    timedOut: map['timedOut'] == true,
    error: map['error'] is String ? map['error'] as String : null,
  );
}

/// A command waiting for the person's tap; the app is blocked until [RootChannel.approve] runs.
class RootConfirmRequest {
  const RootConfirmRequest({required this.id, required this.command, required this.reason});

  final String id;
  final String command;

  /// `danger` (matches the destructive list) or `always`.
  final String reason;
}

class RootChannel {
  static const _methods = MethodChannel('dsh/root');
  static const _events = EventChannel('dsh/root/events');

  bool get supported => Platform.isAndroid;

  Future<RootStatus> status() async {
    final map = await _methods.invokeMethod<Map<Object?, Object?>>('status');
    return RootStatus.fromMap(map ?? const {});
  }

  /// Runs `su -c id`: this is the call that makes the manager show its own dialog.
  Future<RootStatus> refresh() async {
    await _methods.invokeMethod<Map<Object?, Object?>>('refresh');
    return status();
  }

  Future<RootStatus> setEnabled(bool enabled) async {
    await _methods.invokeMethod<Map<Object?, Object?>>('setEnabled', {'enabled': enabled});
    return status();
  }

  Future<RootStatus> setPolicy({bool? writeAccess, RootApproval? approval}) async {
    await _methods.invokeMethod<Map<Object?, Object?>>('setPolicy', {
      'writeAccess': writeAccess,
      'approval': approval?.wire,
    });
    return status();
  }

  Future<void> acknowledge() => _methods.invokeMethod<void>('acknowledge');

  Future<RootExecResult> exec(String command, {int? timeoutMs}) async {
    final map = await _methods.invokeMethod<Map<Object?, Object?>>('exec', {
      'command': command,
      'timeoutMs': timeoutMs,
    });
    return RootExecResult.fromMap(map ?? const {});
  }

  Future<void> approve(String id, bool allow) => _methods.invokeMethod<void>('approve', {'id': id, 'allow': allow});

  Future<void> clearLog() => _methods.invokeMethod<void>('clearLog');

  /// Status snapshots and confirmation requests, as the app sends them.
  Stream<Map<Object?, Object?>> events() => _events.receiveBroadcastStream().where((event) => event is Map).cast();
}
