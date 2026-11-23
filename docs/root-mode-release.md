## DSH Go · Root 模式

这一版给 DSH Go 加了 **Root 模式**：在 KernelSU / Magisk / APatch 授权下，引擎里的 AI Agent 可以用手机的真实 root 读写整个 Android 文件系统，包括 `/data`、`/data/data`、`/data/adb`、`/system`。

### 新增

- **设置 → 能力 → Root 模式**：开关、管理器识别（KernelSU / Magisk / APatch 与版本）、`su` 路径、通道状态、本次已执行命令数。
- **访客侧 shim**：引擎里直接 `sudo <命令>`、`su -c "<命令>"`、`dsh-root exec|read|write|list|stat|info`，不需要学新工具。
- **访问范围**：读写 / 只读。只读时，写文件、改权限、装应用这类命令在调用 `su` **之前**就被拒绝。
- **确认方式**：不确认 / 危险操作确认（默认）/ 每次确认。危险操作（`rm -rf /data`、`mkfs`、`dd of=/dev/block`、`mount -o remount`、`pm uninstall`、`settings put`、`reboot`、装模块、`curl | sh` 等）会弹窗，60 秒无响应按拒绝处理。
- **Agent 提示**：开启后 `AGENTS.md` 多一节「Root 模式」，说明能做什么、哪些目录不要碰。
- **记录**：最近 200 条 root 命令（命令、退出码、是否被拒、耗时）留在内存里，设置页可查可清。

### root.2 修复

- **只读范围漏了文件通道**：`dsh-root write` 不是一条命令行，走不到 `isReadOnly` 的判断，之前无论访问范围设成什么都照写不误，也不弹确认。现在它和 `exec` 走同一道门：只读时直接回 `read_only_scope`（不调 `su`），「每次确认」时照样弹窗，被拒记进命令记录。
- `dsh-root read` 的 `maxBytes` 现在夹在 4 MB 以内，客户端传多大的数都不会把整个大文件读进内存。

### 怎么实现

不把整个引擎跑在 root 下，只提权单条命令：引擎仍是 App uid，`sudo` 走抽象 unix socket 到 App，App 用 `su -c` 执行（Magisk / KernelSU / APatch 同一种写法），超时就杀进程。每次启动随机生成 socket 名与 token，写在 `/var/lib/dsh-app/root/bridge.json`（0600）；引擎停止即关闭通道；安全模式不写 shim、不开通道。

### 源码

| 文件 | 内容 |
|---|---|
| `root-mode.patch` | 相对上游 `5a3e95d` 的完整补丁：54 个文件 / +3571 行，含 17 张 golden 基线，`git apply` 一次到位 |
| `ROOT-MODE.md` | 设计与取舍 |
| `root-mode-guide-zh.md` · `root-mode-guide-en.md` | 使用指南（中 / 英） |
| `SHA256SUMS` | 以上附件与 APK 的 SHA-256 |

```bash
git clone https://github.com/ccch1mneyyy/dsh-Go.git && cd dsh-Go
git checkout 5a3e95d
git apply root-mode.patch
```

### 安装

1. 手机已 root，并在管理器里给 DSH Go 授权。
2. 下载本页 `dsh-go-root-*-arm64.apk`（Android 8+，arm64）。本包用 debug 签名：装过官方版的手机要先卸载官方版，数据不会自动迁移。
3. 首次启动按原版流程装好本机运行环境（约 1 GB）。
4. 设置 → 能力 → Root 模式 → 读提示 → 开启 → 「检测 root」→ 管理器弹窗选「允许（永久）」。
5. 在 App 终端里 `sudo id`，看到 `uid=0(root)` 即成功。

### 风险

这是真的 root。模型判断失误或被恶意指令误导，可能删掉 `/data`、改系统设置、装模块导致无法开机。请先备份，只在自用设备上开；不要在存着支付/银行信息的设备上关掉确认。

### 与上游

本仓库：[aaa2019360508/dsh-go-root](https://github.com/aaa2019360508/dsh-go-root)，基于 [ccch1mneyyy/dsh-Go](https://github.com/ccch1mneyyy/dsh-Go) v1.3.0 的社区补丁（已合入上游 2026-11-23 的 `5a3e95d`），代码 AGPL-3.0；`sdk/`、`examples/` 为 MIT。名称、标识与 Deepy / 鲸娘形象不在开源授权范围内。本项目不是官方版本，也不代表 DeepSeek。
