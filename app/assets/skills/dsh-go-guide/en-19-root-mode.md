# Root mode

> Android only, and only on a device you own. With this on, the model can read and write `/data`,
> `/system` and other apps' data.

## What it changes

The Linux environment runs under PRoot, where `id` says `uid=0` but the real process is still the
app's uid — so `/data/data` answers `EACCES`. Root mode sends single commands through the
phone's `su` to get real root. Everything else is unchanged.

## Turn it on

1. The phone is rooted: KernelSU, Magisk or APatch.
2. Settings → Abilities → **Root mode** → read the warning → turn it on.
3. Tap “Check root”. Choose “Allow (permanently)” in the manager's prompt; “Allow once” works too
   but the manager asks again on the next start.
4. Verify in the terminal:

```bash
sudo id                    # uid=0(root)
dsh-root info              # channel and policy
sudo ls /data/data | head
```

“No su found” means the manager is missing or not on PATH; “Not granted yet” means the prompt was
denied or timed out.

## Three ways to call it

| Form | Use |
| --- | --- |
| `sudo <command>` | the everyday form |
| `su -c "<command>"` | what older scripts already use |
| `dsh-root read/write/list/stat` | binary-safe access to root-only files, structured listings |

`dsh-root` without arguments prints help. `dsh-root exec -t 600 <command>` raises the timeout to
ten minutes.

## Policy

| Setting | Meaning |
| --- | --- |
| Scope | **Read-write**: everything. **Read-only**: commands that are not read-only are refused before `su` runs (`read_only_scope`). The check looks at the first word of each segment: `ls/cat/grep/find/stat/dumpsys/pm list…` pass; `>`, `-delete`, `rm/mv/cp/chmod`, `su/sh -c/xargs` count as writes. |
| Confirmation | Never: the switch is the only gate. Destructive (default): a prompt when the command matches the destructive list. Always: a prompt for every root command. |
| Timeout | 120 s by default, 10 min maximum; on timeout the process is killed and the call returns `124`. |
| Output | 4 MB per command; the rest is dropped and flagged `truncated`. |

When a prompt is needed and the app is not in the foreground, the command is denied — never
silently allowed.

## Limits

- Do not touch `/data/adb` (the manager itself), `/data/system` (lock screen and accounts) or
  `/data/misc` (keys). The agent is told, but a prompt is not a sandbox.
- SELinux: on some ROMs the `su` domain is restricted and `/data/data` is still refused.
- Work profile: `/data/user/<id>` needs the matching permission; work data may be unreachable.
- OTA: restore `/system` before a system update, or the device may not boot.
- **Safe mode**: no shims, no channel — root mode is unavailable there.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `dsh-root: root mode is off` | The switch is off, or it was off when the engine started (restart the engine after switching). |
| `root_mode_off` | The channel exists but the app-side switch is off. |
| `read_only_scope` | A write command in read-only scope. |
| `denied_by_person` | The prompt was denied or unanswered for 60 s. |
| `su_missing` | No `su` found; check the manager install. |
| `timeout` | The command was killed; raise it with `-t` or change the command. |
