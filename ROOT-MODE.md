# DSH Go · Root 模式

> 让 DSH 里的 AI Agent 直接以手机的真实 root 身份读写整个 Android 文件系统——包括 `/data`、
> `/data/data`、`/data/adb`、`/system`。基于 [ccch1mneyyy/dsh-Go](https://github.com/ccch1mneyyy/dsh-Go)
> 的社区补丁，支持 **KernelSU / Magisk / APatch**。三档访问范围（只读 / 读写 / 完全权限），
> 加一条**不可关闭的支付保护**。

![状态](https://img.shields.io/badge/Android-8%2B-4B67B4) ![许可](https://img.shields.io/badge/许可-AGPL--3.0-4B67B4)

---

## 这是什么

原版 DSH Go 把 Ubuntu 跑在 PRoot 里，引擎看到的是一个**假 root**：`id` 显示 `uid=0`，但真实进程还是
App 的 uid，所以 `/data/data` 一律 `EACCES`。手机存储只能通过「访问手机文件」拿到 `/sdcard`，
其他应用的私有数据、`/data/adb`、系统分区都碰不到。

Root 模式补上了这一段：App 通过手机上的 `su`（KernelSU / Magisk / APatch 提供）拿真实 root，
再把一个**受策略约束的 root 通道**装进访客环境。于是引擎里任何一条命令都可以：

```bash
sudo ls /data/data                       # 其他应用的私有目录
sudo cat /data/data/com.tencent.mm/...   # root 专属文件
dsh-root list /data/adb/modules          # 结构化列目录
echo hello | dsh-root write /data/local/tmp/x   # 二进制安全写入
```

Agent 也会被告知这件事：开启后 `AGENTS.md` 里多一节「Root 模式」，说明能做什么、哪些地方不要碰。

## 为什么不是「整个引擎跑在 root 下」

最省事的做法是 `su -c proot ...` 把整个 PRoot 提权，但那样 rootfs 里所有文件都会被写成 root 所有，
之后关掉 root 模式再启动就全线 `EACCES`，而且引擎、插件、网页版全部拿到了 root，出事没有边界。
所以这里只提权**单条命令**：引擎仍是 App uid，只有你（或模型）明确调用的那条命令走 `su`。
PRoot 的 `-b /data` 也一样不行——proot 是用户态翻译，宿主上的 `open()` 仍然是 App uid，绑进去也读不了。

## 怎么工作

```text
引擎（PRoot, App uid）
  └─ sudo / su / dsh-root           ← 写进 rootfs 的 shim（/usr/local/bin）
        └─ node /opt/dsh-go/root/dsh-root.mjs
              └─ 抽象 unix socket  @dsh-app.root.<random>
                    └─ App 进程 RootBridge（校验 uid + 本次启动的 token）
                          ├─ RootPolicy：只读/读写、确认级别、破坏性命令识别
                          └─ RootShell：su -c "<命令>"（Magisk/KernelSU/APatch 同一种写法）
                                └─ 手机的真实 root
```

- **一条命令一个进程**：`su -c` 有超时，超时就 `destroyForcibly`，不会留下会话、不会串输出。
- **每次启动重新发牌**：socket 名与 token 每次启动随机生成，写在 `/var/lib/dsh-app/root/bridge.json`（0600）；
  引擎停止时通道关闭，shim 保留但连不上。
- **访客可见 ≠ 人可以不管**：同 uid 的代码本来就能连上（和手机操控的威胁模型一致），真正的门是
  策略与确认弹窗，不是 token。
- **不出现在安全模式**：安全模式不写 shim、不开通道。

## 四个开关

| 设置 | 取值 | 作用 |
| --- | --- | --- |
| 开启 Root 模式 | 开 / 关 | 关：不写 shim、通道关闭；开：先 `su -c id` 探测并缓存结果 |
| 访问范围 | 只读 / 读写 / 完全权限 | 只读：非只读命令在**调用 su 之前**就被拒绝（`read_only_scope`）；读写：按确认级别弹窗；完全权限：不再询问。`dsh-root write` 走同一道门，不经过命令行判定也一样被拒 |
| 确认方式 | 不确认 / 危险操作确认（默认）/ 每次确认 | 需要确认时 App 弹窗，60 秒无响应按拒绝处理。完全权限下不生效 |
| 支付保护 | 恒开 | 支付类应用的包名与数据目录一律拒绝，三档范围都一样，没有开关 |

「危险操作」是一张正则表：`rm -rf /`、`rm -rf /data`、`mkfs`、`dd of=/dev/block`、`mount -o remount`、
`pm uninstall`、`settings put`、`reboot`、`flash`、`insmod`、`curl | sh` 等。它只是提示，不是沙箱。

## 完全权限：把方向盘交出去

完全权限（`scope=full`）是给「让它自己跑完」的场景准备的：模型执行任何 root 命令都不再弹窗，
`rm -rf`、`settings put`、装模块都直接生效。确认判定被整条短路，`approval` 那一项在这一档下不起作用，
命令仍然逐条进记录。

为什么还要留着前两档：**不确认和只读解决的是两个不同的问题**。只读是「让它查，但别改」，
完全权限是「改也行，别烦我」。多数人多数时候要的是前者；后者适合一次性任务、测试机、或者你已经
把要它做的事写死在提示词里。

打开它要过一道单独的确认弹窗（不是列表里点一下就算），因为它撤销的是后面所有命令的最后一道人工闸门。

## 支付保护：唯一不受范围影响的一条

`PaymentGuard` 是硬编码名单，没有开关、不从网络更新——一份可以关掉的名单等于没有名单。判定三件事：

1. **包名**：支付宝、微信、QQ（QQ 钱包）、云闪付、数字人民币、京东金融、度小满、PayPal、
   Google 钱包、Samsung Pay、小米钱包、华为钱包，以及工行/建行/中行/农行/交行/邮储/招行/中信/
   民生/兴业/平安/光大/广发/华夏/浦发等银行客户端（含 `com.icbc.` 这类前缀，覆盖信用卡与企业版）。
   命令或路径里出现这些包名就拒（`payment_guard:<包名>`），`pm` / `am` / `cmd` 一样。
2. **路径**：`/data/data/<包>`、`/data/user/0/<包>`、`/data/user_de/0/<包>`、`/data/app/<包>-*`、
   `/sdcard/Android/data/<包>` 落在名单里就拒。文件通道的 read / write / list / stat 共用这道门。
3. **整棵读取**：`cp -r /data/data`、`tar ... /data/data`、`grep -r ... /data/data`、
   `cat /data/data/*/...`、`find /data/data -exec cat` 这类「把整棵树搬走」的命令一律拒
   （`payment_guard_bulk`），因为通配符会把支付应用一起带走。只看元数据的 `ls`、`du`、`stat`、
   `find -maxdepth 1` 不受影响，否则日常排查都没法做。

微信整包在列，不按插件拆：微信支付、收款码、账单都在同一个 `/data/data/com.tencent.mm` 下，按目录
分不开。这条会连带挡住聊天数据，是刻意的取舍——少读一份聊天记录，比多读一份账单便宜。

**它不是沙箱**。它拦的是模型递过来的命令，不是内核里的访问控制：一个能自己写 C 程序、自己调
`openat` 的 Agent 仍然绕得过去（虽然它得先编译再执行，而且每条命令都会进记录）。要真正的硬隔离，
得给 root 进程单独一个 SELinux 域并写 neverallow，那是另一个量级的工程。这里的目标是「正常使用
路径上碰不到」，不是「理论上不可能」。

## 装与用

1. 手机已 root（KernelSU / Magisk / APatch 任一），并在管理器里给 DSH Go 授权。
2. 安装本仓库 Release 里的 APK（arm64），首次启动按原版流程装好本机运行环境。
3. 设置 → 能力 → **Root 模式** → 读风险提示 → 开启 → 「检测 root」。
   管理器弹授权时选「允许（永久）」。
4. 回聊天里让 Agent 干活，例如：*「用 root 看看 /data/data 下哪些应用占空间最大」*。

命令行自查（在 App 的终端里）：

```bash
dsh-root info                 # 策略与通道状态
sudo id                       # uid=0(root) 即成功
dsh-root list /data/data | head
```

## 边界与风险

- **这是真的 root**。模型判断失误、被网页或文件里的恶意指令误导，都可能删掉 `/data`、改系统设置、
  装模块导致无法开机。请先备份，只在自用设备上开。完全权限下没有确认弹窗，风险全部前移到你按下
  「开启」的那一刻。
- **支付保护是闸门，不是沙箱**：它挡住的是命令与路径，不是内核权限。别把它当成「可以放心让模型
  随便跑」的理由。
- **不要碰**：`/data/adb`（root 管理器自身）、`/data/system`（锁屏与账户）、`/data/misc`（密钥）。
  文档里已写进 Agent 的提示，但提示不是强制。
- **SELinux**：部分 ROM 上 `su` 域受限，`/data/data` 仍可能被拒；报错就是被拒，不是 App 的 bug。
- **多用户/工作资料**：`/data/user/<id>` 需要对应权限，工作资料的数据不一定可达。
- **确认弹窗依赖 App 在前台**：后台任务遇到需要确认的命令会直接被拒绝（不会静默放行）。

## 和 Operit 的关系

思路参考 [Operit](https://github.com/AAswordman/Operit)：它把 root 终端直接交给 AI。这里保留了同样的
「一条命令一个 `su`」的模型，但加了四件 Operit 没有的东西——**访客侧 shim（Agent 无需学新工具，`sudo` 就行）**、
**三档访问范围**、**破坏性命令确认**、**不可关闭的支付保护**，并且完全复用 DSH Go 自己的启动、日志与安全模式。

## 许可

代码沿用上游 **AGPL-3.0**（`sdk/`、`examples/` 为 MIT）。DSH Go 的名称、标识与 Deepy / 鲸娘形象不在
开源授权范围内，本仓库是社区补丁，不是官方版本，也不代表 DeepSeek。
