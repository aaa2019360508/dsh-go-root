// Root mode state: the switch, the scope, the confirmation level, and whatever the last
// `su -c id` said. The bridge is owned by the app process; this only mirrors it for the UI.

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../root/root_channel.dart';

final rootChannelProvider = Provider<RootChannel>((ref) => RootChannel());

class RootModeState {
  const RootModeState({
    this.status = const RootStatus(),
    this.loading = false,
    this.error,
    this.pending,
    this.testOutput,
    this.testing = false,
  });

  final RootStatus status;

  /// A probe or switch change is in flight.
  final bool loading;
  final String? error;

  /// A guest command waiting for a tap.
  final RootConfirmRequest? pending;

  /// The last command run from the page's test field.
  final RootExecResult? testOutput;
  final bool testing;

  RootModeState copyWith({
    RootStatus? status,
    bool? loading,
    String? error,
    RootConfirmRequest? pending,
    bool clearPending = false,
    RootExecResult? testOutput,
    bool clearTest = false,
    bool? testing,
  }) => RootModeState(
    status: status ?? this.status,
    loading: loading ?? this.loading,
    error: error,
    pending: clearPending ? null : (pending ?? this.pending),
    testOutput: clearTest ? null : (testOutput ?? this.testOutput),
    testing: testing ?? this.testing,
  );
}

class RootModeController extends Notifier<RootModeState> {
  StreamSubscription<Map<Object?, Object?>>? _events;

  @override
  RootModeState build() {
    final channel = ref.watch(rootChannelProvider);
    if (channel.supported) {
      _events = channel.events().listen(_onEvent, onError: (_) {});
      ref.onDispose(() => _events?.cancel());
      unawaited(_load());
    }
    return const RootModeState();
  }

  void _onEvent(Map<Object?, Object?> event) {
    final type = event['type'];
    if (type == 'confirm') {
      state = state.copyWith(
        pending: RootConfirmRequest(
          id: event['id'] as String? ?? '',
          command: event['command'] as String? ?? '',
          reason: event['reason'] as String? ?? 'danger',
        ),
      );
      return;
    }
    if (type == 'status') {
      final merged = Map<Object?, Object?>.from(event)..remove('type');
      state = state.copyWith(status: RootStatus.fromMap(merged));
    }
  }

  Future<void> _load() async {
    try {
      final status = await ref.read(rootChannelProvider).status();
      state = state.copyWith(status: status);
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  /// Asks the manager for one `id`; this is the call that shows its authorization dialog.
  Future<void> refresh() async {
    if (!ref.read(rootChannelProvider).supported) return;
    state = state.copyWith(loading: true, error: null);
    try {
      final status = await ref.read(rootChannelProvider).refresh();
      state = state.copyWith(status: status, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
    }
  }

  Future<void> setEnabled(bool enabled) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final status = await ref.read(rootChannelProvider).setEnabled(enabled);
      state = state.copyWith(status: status, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
    }
  }

  Future<void> setPolicy({bool? writeAccess, RootApproval? approval}) async {
    try {
      final status = await ref.read(rootChannelProvider).setPolicy(writeAccess: writeAccess, approval: approval);
      state = state.copyWith(status: status);
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  Future<void> acknowledge() async {
    try {
      await ref.read(rootChannelProvider).acknowledge();
      state = state.copyWith(status: state.status);
    } catch (_) {}
  }

  Future<void> exec(String command) async {
    if (command.trim().isEmpty) return;
    state = state.copyWith(testing: true, clearTest: true);
    try {
      final result = await ref.read(rootChannelProvider).exec(command);
      final status = await ref.read(rootChannelProvider).status();
      state = state.copyWith(testing: false, testOutput: result, status: status);
    } catch (e) {
      state = state.copyWith(testing: false, error: e.toString());
    }
  }

  Future<void> approve(String id, bool allow) async {
    try {
      await ref.read(rootChannelProvider).approve(id, allow);
    } catch (_) {}
    state = state.copyWith(clearPending: true);
  }

  Future<void> clearLog() async {
    try {
      await ref.read(rootChannelProvider).clearLog();
      await _load();
    } catch (_) {}
  }
}

final rootModeProvider = NotifierProvider<RootModeController, RootModeState>(RootModeController.new);
