# Root 模式

> 只在 Android、只在你自己的设备上使用（HarmonyOS 与 iOS 没有这一页）。开启后模型能读写 `/data`、`/system` 和其他应用的数据。

## 它解决什么

原版 DSH Go 的 Linux 环境跑在 PRoot 里，`id` 显示 `uid=0` 只是 PRoot 的假象：真实进程仍是 App 的 uid，所以 `/data/data` 一律 `EACCES`。Root 模式让单条命令通过手机的 `su` 拿到真实 root，其他部分照旧。

## 开启

1. 手机已 root：KernelSU、Magisk 或 APatch。
2. 设置 → 能力 → Root 模式 → 读风险提示 → 开启。
3. 点「检测 root」。管理器弹授权时选「允许（永久）」；选一次也行，但每次启动会再问。
4. 回到聊天或终端验证：

```bash
sudo id                    # uid=0(root)
dsh-root info              # 通道与策略状态
sudo ls /data/data | head
```

如果 `检测 root` 显示「没有找到 su」，说明管理器没装或不在 PATH；显示「管理器没有授权」说明授权被拒或超时。

## 三种用法

| 写法 | 用途 |
| --- | --- |
| `sudo <命令>` | 最顺手：任何命令前加 `sudo` |
| `su -c "<命令>"` | 兼容脚本里的老写法 |
| `dsh-root read/write/list/stat` | 二进制安全地读写 root 专属文件、结构化列目录 |

`dsh-root` 不带参数会打印帮助。`dsh-root exec -t 600 <命令>` 把超时放宽到 10 分钟。

## 策略

| 设置 | 说明 |
| --- | --- |
| 访问范围 | **只读**：非只读命令在调用 `su` 之前被拒（`read_only_scope`）。只读判定按命令首词：`ls/cat/grep/find/stat/dumpsys/pm list…` 放行；含 `>`、`-delete`、`rm/mv/cp/chmod`、`su/sh -c/xargs` 一律算写；`dsh-root write` 不经过这套判定，但同样被拒。**读写**：全部放行，危险命令按确认方式弹窗。**完全权限**：不再询问，命令直接执行。 |
| 确认方式 | **不确认**：开关即授权。**危险操作确认**（默认）：命中破坏性命令时弹窗。**每次确认**：每条 root 命令都弹窗。完全权限下这一项不起作用。 |
| 支付保护 | 恒开，无法关闭：支付类应用的包名与数据目录一律拒绝（`payment_guard`），整棵读取 `/data/data` 也被拒（`payment_guard_bulk`）。三档访问范围都一样。 |
| 超时 | 命令默认 120 秒，最长 10 分钟；超时杀进程，返回 `124`。 |
| 输出 | 单条命令最多 4 MB，超出截断并标记 `truncated`。 |

需要确认而 App 不在前台时，命令直接被拒绝（不会静默放行）。

## 完全权限模式

把访问范围切到**完全权限**，模型拿到的就是没有人工闸门的 root：删目录、改系统设置、装模块都直接生效，不再弹窗。切过去时会单独弹一次确认——它撤销的是之后所有命令的最后一道人工检查。

适合：一次性任务、测试机、或者你已经把要做的事在提示词里写死。不适合：主力机、存着支付与银行信息的机器。

完全权限不会解除支付保护：那一层和访问范围无关。

## 支付保护

以下访问一律被拒，三档范围都一样：

| 类型 | 例子 | 错误码 |
| --- | --- | --- |
| 点名支付应用的命令 | `pm clear com.tencent.mm`、`am start -n com.eg.android.AlipayGphone/...` | `payment_guard:com.tencent.mm` |
| 支付应用的数据目录 | `/data/data/com.tencent.mm/...`、`/data/user/0/com.eg.android.AlipayGphone/...`、`/data/app/<包>-*` | `payment_guard:<包名>` |
| 整棵读取 `/data/data` | `cp -r /data/data /sdcard/b`、`tar ... /data/data`、`grep -r ... /data/data`、`cat /data/data/*/x` | `payment_guard_bulk` |

覆盖支付宝、微信、QQ、云闪付、数字人民币、京东金融、度小满、PayPal、Google 钱包、Samsung Pay、小米/华为钱包，以及工行、建行、中行、农行、交行、邮储、招行、中信、民生、兴业、平安、光大、广发、华夏、浦发等银行客户端。名单是内置的，不联网更新，也没有开关。

`ls`、`du`、`stat`、`find -maxdepth 1` 这类只看元数据的命令不受影响，否则日常排查没法做。

被拒时：告诉用户，换任务，不要改写命令绕过——绕过本身也是一条会被记录的行为。

## 边界

- 不要碰：`/data/adb`（管理器自身）、`/data/system`（锁屏与账户）、`/data/misc`（密钥）。Agent 的提示里写了，但提示不是强制。
- SELinux：部分 ROM 的 `su` 域受限，`/data/data` 仍可能被拒；报错就是被拒。
- 工作资料：`/data/user/<id>` 需要对应权限，工作资料的数据不一定可达。
- 系统更新：改过 `/system` 的设备做 OTA 前先还原，否则可能无法开机。
- **安全模式**：安全模式不写 shim、不开通道，root 模式整体不可用。

## 排查

| 现象 | 原因 |
| --- | --- |
| `dsh-root: root mode is off` | 开关没开，或引擎启动时开关是关的（开关后重启引擎即可） |
| `root_mode_off` | 通道在，但 App 侧开关被关掉 |
| `read_only_scope` | 只读范围下执行了写命令 |
| `denied_by_person` | 弹窗被拒绝或 60 秒没响应 |
| `su_missing` | 找不到 `su`，检查管理器安装 |
| `timeout` | 命令超时被杀；用 `-t` 放宽或改命令 |
