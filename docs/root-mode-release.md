## DSH Go · Root 模式 1.4.0

跟上游 **v1.4.0** 同步，并给 Root 模式加了第二档和第二道门：**完全权限**（把 root 直接交给 Agent，不再逐条确认）和**支付保护**（支付类应用一律拒绝，无法关闭）。

### 同步上游 1.4.0

- 伙伴小屋完整模式、手机操控悬浮岛与手机技能、OpenAI 官方渠道、酒馆 1.19 预设、iOS 实时活动等上游新功能全部包含。
- Root 模式的补丁已重做到 `v1.4.0` 上，不再基于 1.3.0 的 `5a3e95d`。

### 新增：完全权限模式

访问范围从两档变三档：

| 档位 | 行为 |
|---|---|
| 只读 | 非只读命令在调用 `su` 之前就被拒（`read_only_scope`），文件通道的写也一样 |
| 读写 | 全部放行，危险命令按「确认方式」弹窗 |
| **完全权限** | **不再询问，命令直接执行**；确认方式那一项不再起作用，命令照旧逐条进记录 |

打开完全权限要过一次单独的确认弹窗——它撤销的是之后每条命令的最后一道人工检查。适合一次性任务、测试机、或提示词里已经把要做的事写死的场景。

### 新增：支付保护（硬性）

`PaymentGuard`：一份内置名单，**不受访问范围影响，没有开关**。

- **点名支付应用就拒**：`pm clear com.tencent.mm`、`am start -n com.eg.android.AlipayGphone/...` → `payment_guard:<包名>`。
- **数据目录就拒**：`/data/data/<包>`、`/data/user/0/<包>`、`/data/user_de/0/<包>`、`/data/app/<包>-*`、`/sdcard/Android/data/<包>`；`dsh-root read/write/list/stat` 共用这道门。
- **整棵读取就拒**：`cp -r /data/data …`、`tar … /data/data`、`grep -r … /data/data`、`cat /data/data/*/x`、`find /data/data -exec cat` → `payment_guard_bulk`。通配符会把支付应用一起带走，所以按「可能读到」处理；只看元数据的 `ls`、`du`、`stat`、`find -maxdepth 1` 不受影响。

覆盖支付宝、微信、QQ、云闪付、数字人民币、京东金融、度小满、PayPal、Google 钱包、Samsung Pay、小米/华为钱包，以及工行、建行、中行、农行、交行、邮储、招行、中信、民生、兴业、平安、光大、广发、华夏、浦发等银行客户端（含 `com.icbc.` 一类前缀，覆盖信用卡与企业版）。

**它是闸门，不是沙箱**：挡的是模型递过来的命令，不是内核里的访问控制。真正的硬隔离要靠 SELinux 域，那是另一个量级的工程。

### 沿用 root.2 的修复

- 只读范围漏了文件通道：`dsh-root write` 现在和 `exec` 走同一道门，只读时回 `read_only_scope`，不调 `su`。
- `dsh-root read` 的 `maxBytes` 夹在 4 MB 以内。

### 怎么实现

不把整个引擎跑在 root 下，只提权单条命令：引擎仍是 App uid，`sudo` 走抽象 unix socket 到 App，App 用 `su -c` 执行（Magisk / KernelSU / APatch 同一种写法），超时就杀进程。每次启动随机生成 socket 名与 token，写在 `/var/lib/dsh-app/root/bridge.json`（0600）；引擎停止即关闭通道；安全模式不写 shim、不开通道。

### 源码

| 文件 | 内容 |
|---|---|
| `root-mode.patch` | 相对上游 `v1.4.0` 的完整补丁，含 golden 基线，`git apply` 一次到位 |
| `ROOT-MODE.md` | 设计与取舍 |
| `root-mode-guide-zh.md` · `root-mode-guide-en.md` | 使用指南（中 / 英） |
| `SHA256SUMS` | 以上附件与 APK 的 SHA-256 |

```bash
git clone https://github.com/ccch1mneyyy/dsh-Go.git && cd dsh-Go
git checkout v1.4.0
git apply root-mode.patch
```

### 安装

1. 手机已 root（KernelSU / Magisk / APatch），并在管理器里给 DSH Go 授权。
2. 下载本页 `dsh-go-root-*-arm64.apk`（Android 8+，arm64）。本包用 debug 签名：装过官方版的手机要先卸载官方版，数据不会自动迁移。
3. 首次启动按原版流程装好本机运行环境（约 1 GB）。
4. 设置 → 能力 → Root 模式 → 读提示 → 开启 → 「检测 root」→ 管理器弹窗选「允许（永久）」。
5. 在 App 终端里 `sudo id`，看到 `uid=0(root)` 即成功。

### 风险

这是真的 root。模型判断失误或被恶意指令误导，可能删掉 `/data`、改系统设置、装模块导致无法开机。请先备份，只在自用设备上开。完全权限下没有确认弹窗，风险全部前移到按下「开启」的那一刻；支付保护挡得住正常的读写路径，挡不住一个自己编译程序去 `openat` 的 Agent。

### 与上游

本仓库：[aaa2019360508/dsh-go-root](https://github.com/aaa2019360508/dsh-go-root)，基于 [ccch1mneyyy/dsh-Go](https://github.com/ccch1mneyyy/dsh-Go) **v1.4.0** 的社区补丁，代码 AGPL-3.0；`sdk/`、`examples/` 为 MIT。名称、标识与 Deepy / 鲸娘形象不在开源授权范围内。本项目不是官方版本，也不代表 DeepSeek。
