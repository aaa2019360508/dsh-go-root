// 设置 › Root 模式: the switch that lets the engine run the phone's own `su`.
//
// The page states the risk before the switch, shows what the manager answered, and keeps the
// scope (read-only / read-write) and the confirmation level next to the switch — a person who
// turns this on is changing what every later tool call may touch, so none of it hides behind a
// submenu.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../l10n/l10n.dart';
import '../../root/root_channel.dart';
import '../../state/root_state.dart';
import '../shell/page_frame.dart';
import '../theme/app_icons.dart';
import 'settings_widgets.dart';

class RootModePage extends ConsumerStatefulWidget {
  const RootModePage({super.key});

  @override
  ConsumerState<RootModePage> createState() => _RootModePageState();
}

class _RootModePageState extends ConsumerState<RootModePage> {
  final _command = TextEditingController();

  @override
  void dispose() {
    _command.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final state = ref.watch(rootModeProvider);
    final controller = ref.read(rootModeProvider.notifier);
    final status = state.status;

    // A guest command is waiting: the app's worker is blocked until this answers.
    ref.listen(rootModeProvider.select((value) => value.pending), (previous, next) {
      if (next == null || previous?.id == next.id) return;
      unawaited(_askConfirm(next));
    });

    return AppPage.list(
      title: l10n.rootModeTitle,
      subtitle: Text(l10n.rootModeSubtitle),
      children: [
        if (!status.acknowledged)
          Padding(
            padding: kSettingsGroupMargin,
            child: _WarningCard(
              text: l10n.rootModeWarning,
              action: l10n.rootModeWarningAccept,
              onAccept: () => unawaited(controller.acknowledge()),
            ),
          ),
        SettingsSection(
          title: l10n.rootModeStatus,
          children: [
            SettingsSwitchTile(
              icon: AppIcons.systemAccess,
              spot: Spots.rootSwitch,
              title: l10n.rootModeSwitch,
              subtitle: status.enabled ? l10n.rootModeSwitchOn : l10n.rootModeSwitchOff,
              value: status.enabled,
              onChanged: state.loading ? null : (value) => unawaited(controller.setEnabled(value)),
            ),
            SettingsTile(
              icon: AppIcons.search,
              spot: Spots.rootRefresh,
              title: l10n.rootModeRefresh,
              subtitle: _detailText(l10n, status),
              trailing: state.loading
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : null,
              onTap: state.loading ? null : () => unawaited(controller.refresh()),
            ),
            InfoRow(label: l10n.rootModeManager, value: _managerText(status)),
            InfoRow(label: l10n.rootModeVersion, value: status.version.isEmpty ? '—' : status.version),
            InfoRow(label: l10n.rootModeSuPath, value: status.suPath.isEmpty ? '—' : status.suPath, mono: true),
            InfoRow(
              label: l10n.rootModeBridge,
              value: status.listening ? l10n.rootModeBridgeOn : l10n.rootModeBridgeOff,
            ),
            InfoRow(label: l10n.rootModeRequests, value: '${status.requests}'),
          ],
        ),
        SettingsSection(
          title: l10n.rootModePolicy,
          footer: Text(_scopeHint(l10n, status.scope)),
          children: [
            SettingsSegmentTile<RootScope>(
              icon: AppIcons.fileAccess,
              spot: Spots.rootScope,
              title: l10n.rootModeScope,
              segments: [
                PillSegment(RootScope.read, l10n.rootModeScopeRead),
                PillSegment(RootScope.write, l10n.rootModeScopeWrite),
                PillSegment(RootScope.full, l10n.rootModeScopeFull),
              ],
              selected: status.scope,
              onChanged: (value) => unawaited(_selectScope(controller, value)),
            ),
            SettingsSegmentTile<RootApproval>(
              icon: AppIcons.approval,
              spot: Spots.rootApproval,
              title: l10n.rootModeApproval,
              subtitle: status.scope == RootScope.full ? l10n.rootModeApprovalMuted : null,
              segments: [
                PillSegment(RootApproval.off, l10n.rootModeApprovalOff),
                PillSegment(RootApproval.danger, l10n.rootModeApprovalDanger),
                PillSegment(RootApproval.always, l10n.rootModeApprovalAlways),
              ],
              selected: status.approval,
              onChanged: status.scope == RootScope.full
                  ? (_) {}
                  : (value) => unawaited(controller.setPolicy(approval: value)),
            ),
          ],
        ),
        SettingsSection(
          title: l10n.rootModePayment,
          footer: Text(l10n.rootModePaymentHint),
          children: [
            SettingsTile(
              icon: AppIcons.permissionRisky,
              spot: Spots.rootPayment,
              title: l10n.rootModePaymentHard,
              subtitle: l10n.rootModePaymentCount(status.paymentGuard),
              trailing: Text(l10n.rootModePaymentFixed, style: Theme.of(context).textTheme.labelSmall),
            ),
          ],
        ),
        SettingsSection(
          title: l10n.rootModeTest,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
              child: TextField(
                controller: _command,
                decoration: InputDecoration(
                  hintText: l10n.rootModeTestHint,
                  border: const OutlineInputBorder(),
                  isDense: true,
                ),
                style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
                textInputAction: TextInputAction.done,
                onSubmitted: (value) => unawaited(controller.exec(value)),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
              child: Row(
                children: [
                  FilledButton.tonal(
                    onPressed: state.testing ? null : () => unawaited(controller.exec(_command.text)),
                    child: Text(l10n.rootModeRun),
                  ),
                  const SizedBox(width: 12),
                  if (state.testing) const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
                ],
              ),
            ),
            if (state.testOutput case final result?)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                child: _OutputBox(text: _formatOutput(l10n, result)),
              ),
          ],
        ),
        SettingsSection(
          title: l10n.rootModeLog,
          children: [
            if (status.logs.isEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                child: Text(l10n.rootModeLogEmpty, style: Theme.of(context).textTheme.bodySmall),
              )
            else
              for (final entry in status.logs.take(20))
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 6, 16, 6),
                  child: _LogRow(entry: entry),
                ),
            if (status.logs.isNotEmpty)
              SettingsTile(
                icon: AppIcons.delete,
                spot: Spots.rootClear,
                title: l10n.rootModeClear,
                onTap: () => unawaited(controller.clearLog()),
              ),
          ],
        ),
        if (state.error case final error?)
          Padding(
            padding: kSettingsGroupMargin,
            child: Text(error, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ),
      ],
    );
  }

  /// 完全权限是这一页唯一一个「点一下就到」的危险档位，所以先问一句再落盘。
  Future<void> _selectScope(RootModeController controller, RootScope value) async {
    if (value == ref.read(rootModeProvider).status.scope) return;
    if (value == RootScope.full) {
      final l10n = context.l10n;
      final ok = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(l10n.rootModeFullTitle),
          content: Text(l10n.rootModeFullBody),
          actions: [
            TextButton(onPressed: () => Navigator.of(context).pop(false), child: Text(l10n.rootModeFullCancel)),
            FilledButton(onPressed: () => Navigator.of(context).pop(true), child: Text(l10n.rootModeFullAccept)),
          ],
        ),
      );
      if (ok != true) return;
    }
    await controller.setPolicy(scope: value);
  }

  String _scopeHint(L10n l10n, RootScope scope) => switch (scope) {
    RootScope.read => l10n.rootModeScopeHint,
    RootScope.write => l10n.rootModeScopeHintWrite,
    RootScope.full => l10n.rootModeScopeHintFull,
  };

  Future<void> _askConfirm(RootConfirmRequest request) async {
    final l10n = context.l10n;
    final allow = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: Text(l10n.rootModeConfirmTitle),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _OutputBox(text: request.command, maxLines: 6),
            const SizedBox(height: 12),
            Text(request.reason == 'always' ? l10n.rootModeApprovalAlways : l10n.rootModeApprovalDanger),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: Text(l10n.rootModeConfirmDeny)),
          FilledButton(onPressed: () => Navigator.of(context).pop(true), child: Text(l10n.rootModeConfirmAllow)),
        ],
      ),
    );
    await ref.read(rootModeProvider.notifier).approve(request.id, allow ?? false);
  }

  String _managerText(RootStatus status) => switch (status.manager) {
    'kernelsu' => 'KernelSU',
    'magisk' => 'Magisk',
    'apatch' => 'APatch',
    _ => status.available ? 'root' : '—',
  };

  String _detailText(L10n l10n, RootStatus status) {
    if (status.available) return l10n.rootModeGranted;
    return switch (status.detail) {
      'su_missing' => l10n.rootModeMissing,
      'not_granted' => l10n.rootModeNotGranted,
      'timeout' => l10n.rootModeTimeout,
      _ => l10n.rootModeUnknown,
    };
  }

  String _formatOutput(L10n l10n, RootExecResult result) {
    final buffer = StringBuffer();
    if (result.output.isNotEmpty) buffer.writeln(result.output);
    if (result.truncated) buffer.writeln(l10n.rootModeOutputTruncated);
    if (result.timedOut) buffer.writeln(l10n.rootModeTimeout);
    if (result.error case final error?) buffer.writeln(error);
    buffer.write('exit ${result.exit}');
    return buffer.toString();
  }
}

class _WarningCard extends StatelessWidget {
  const _WarningCard({required this.text, required this.action, required this.onAccept});

  final String text;
  final String action;
  final VoidCallback onAccept;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
      decoration: BoxDecoration(
        color: scheme.errorContainer.withValues(alpha: 0.6),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(AppIcons.warning, size: 18, color: scheme.onErrorContainer),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  text,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(color: scheme.onErrorContainer),
                ),
              ),
            ],
          ),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(onPressed: onAccept, child: Text(action)),
          ),
        ],
      ),
    );
  }
}

class _OutputBox extends StatelessWidget {
  const _OutputBox({required this.text, this.maxLines = 14});

  final String text;
  final int maxLines;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: scheme.surfaceContainerHighest, borderRadius: BorderRadius.circular(12)),
      child: SelectableText(
        text,
        maxLines: maxLines,
        style: const TextStyle(fontFamily: 'monospace', fontSize: 12, height: 1.35),
      ),
    );
  }
}

class _LogRow extends StatelessWidget {
  const _LogRow({required this.entry});

  final RootLogEntry entry;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final denied = entry.denied != null;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 40,
          child: Text(
            denied ? '—' : '${entry.exit}',
            style: TextStyle(
              fontFamily: 'monospace',
              fontSize: 12,
              color: denied || entry.exit != 0 ? scheme.error : scheme.onSurfaceVariant,
            ),
          ),
        ),
        Expanded(
          child: Text(
            entry.command,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontFamily: 'monospace', fontSize: 12, height: 1.3),
          ),
        ),
        const SizedBox(width: 8),
        Text('${entry.durationMs}ms', style: Theme.of(context).textTheme.labelSmall),
      ],
    );
  }
}
