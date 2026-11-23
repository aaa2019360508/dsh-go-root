## DSH Go · Root 模式

这一版给 DSH Go 加了 **Root 模式**：在 KernelSU / Magisk / APatch 授权下，引擎里的 AI Agent 可以用手机的真实 root 读写整个 Android 文件系统，包括 `/data`、`/data/data`、`/data/adb`、`/system`。

### 新增

- **设置 → 能力 → Root 模式**：开关、管理器识别（KernelSU / Magisk / APatch 与版本）、`su` 路径、通道状态、本次已执行命令数。
- **访客侧 shim**：引擎里直接 `sudo <命令>`、`su -c "<命令>"`、`dsh-root exec|read|write|list|stat|info`，不需要学新工具。
- **访问范围**：读写 / 只读。只读时，写文件、改权限、装应用这类命令在调用 `su` **之前**就被拒绝。
- **确认方式**：不确认 / 危险操作确认（默认）/ 每次确认。危险操作（`rm -rf /data`、`mkfs`、`dd of=/dev/block`、`mount -o remount`、`pm uninstall`、`settings put`、`reboot`、装模块、`curl | sh` 等）会弹窗，60 秒无响应按拒绝处理。
- **Agent 提示**：开启后 `AGENTS.md` 多一节「Root 模式」，说明能做什么、哪些目录不要碰。
- **记录**：最近 200 条 root 命令（命令、退出码、是否被拒、耗时）留在内存里，设置页可查可清。

### 怎么实现

不把整个引擎跑在 root 下，只提权单条命令：引擎仍是 App uid，`sudo` 走抽象 unix socket 到 App，App 用 `su -c` 执行（Magisk / KernelSU / APatch 同一种写法），超时就杀进程。每次启动随机生成 socket 名与 token，写在 `/var/lib/dsh-app/root/bridge.json`（0600）；引擎停止即关闭通道；安全模式不写 shim、不开通道。

### 安装

1. 手机已 root，并在管理器里给 DSH Go 授权。
2. 下载本页 `dsh-go-*-arm64.apk`（Android 8+，arm64）。
3. 首次启动按原版流程装好本机运行环境（约 1 GB）。
4. 设置 → 能力 → Root 模式 → 读提示 → 开启 → 「检测 root」→ 管理器弹窗选「允许（永久）」。
5. 在 App 终端里 `sudo id`，看到 `uid=0(root)` 即成功。

### 风险

这是真的 root。模型判断失误或被恶意指令误导，可能删掉 `/data`、改系统设置、装模块导致无法开机。请先备份，只在自用设备上开；不要在存着支付/银行信息的设备上关掉确认。

### 与上游

基于 [ccch1mneyyy/dsh-Go](https://github.com/ccch1mneyyy/dsh-Go) v1.3.0 的社区补丁，代码 AGPL-3.0；`sdk/`、`examples/` 为 MIT。名称、标识与 Deepy / 鲸娘形象不在开源授权范围内。本项目不是官方版本，也不代表 DeepSeek。
