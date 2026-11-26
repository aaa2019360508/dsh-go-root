# Root mode

> Android only, and only on a device you own (HarmonyOS and iOS have no such page). With this on,
> the model can read and write `/data`, `/system` and other apps' data.

## What it changes

The Linux environment runs under PRoot, where `id` says `uid=0` but the real process is still the
app's uid — so `/data/data` answers `EACCES`. Root mode sends single commands through the
phone's `su` to get real root. Everything else is unchanged.

## Turn it on

1. The phone is rooted: KernelSU, Magisk or APatch.
2. Settings → Abilities → Root mode → read the warning → turn it on.
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
| Scope | **Read-only**: commands that are not read-only are refused before `su` runs (`read_only_scope`). The check looks at the first word of each segment: `ls/cat/grep/find/stat/dumpsys/pm list…` pass; `>`, `-delete`, `rm/mv/cp/chmod`, `su/sh -c/xargs` count as writes; `dsh-root write` skips that check but is refused all the same. **Read-write**: everything runs, destructive commands ask first. **Full**: nothing asks; commands run immediately. |
| Confirmation | Never: the switch is the only gate. Destructive (default): a prompt when the command matches the destructive list. Always: a prompt for every root command. No effect under full access. |
| Payment guard | Always on, no switch: payment apps' packages and data directories are refused (`payment_guard`), and reading `/data/data` as a whole tree is refused too (`payment_guard_bulk`). Same at every scope. |
| Timeout | 120 s by default, 10 min maximum; on timeout the process is killed and the call returns `124`. |
| Output | 4 MB per command; the rest is dropped and flagged `truncated`. |

When a prompt is needed and the app is not in the foreground, the command is denied — never
silently allowed.

## Full access

Switch the scope to **Full** and the model gets root with no human gate: deleting directories,
changing system settings and installing modules all take effect at once. Turning it on asks once, on
its own dialog — it revokes the last manual check for every command after it.

Good for one-off tasks, test devices, or prompts where you already spelled out what should happen.
Not for your daily driver, or a phone that holds payment and banking data.

Full access does not lift the payment guard; that layer does not depend on scope.

## Payment guard

Refused at every scope:

| Kind | Example | Error |
| --- | --- | --- |
| A command that names a payment app | `pm clear com.tencent.mm`, `am start -n com.eg.android.AlipayGphone/...` | `payment_guard:com.tencent.mm` |
| A payment app's data directory | `/data/data/com.tencent.mm/...`, `/data/user/0/com.eg.android.AlipayGphone/...`, `/data/app/<pkg>-*` | `payment_guard:<pkg>` |
| Reading the whole tree | `cp -r /data/data /sdcard/b`, `tar ... /data/data`, `grep -r ... /data/data`, `cat /data/data/*/x` | `payment_guard_bulk` |

Covered: Alipay, WeChat, QQ, UnionPay, e-CNY, JD Finance, Du Xiaoman, PayPal, Google Wallet,
Samsung Pay, Xiaomi and Huawei wallets, plus the mobile apps of ICBC, CCB, BOC, ABC, BoCom, PSBC,
CMB, CITIC, CMBC, CIB, Ping An, CEB, CGB, Huaxia and SPDB. The list is built in, never updated over
the network, and has no switch.

Metadata-only commands (`ls`, `du`, `stat`, `find -maxdepth 1`) are unaffected — otherwise routine
diagnosis would be impossible.

If you are refused: tell the person, change the task, and **do not reword the command to get
through** — routing around the guard is itself a behaviour that gets recorded.

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
