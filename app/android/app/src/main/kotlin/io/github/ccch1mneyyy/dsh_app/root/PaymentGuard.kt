package io.github.ccch1mneyyy.dsh_app.root

/**
 * 支付保护：root 模式下唯一一条**不受访问范围影响**的规则。
 *
 * 只读、读写、完全权限都拦在这里，因为「不要碰钱」不是风险偏好问题，而是不能讨价还价的一条线：
 * 模型读一遍支付 App 的数据库就能拿到账单、卡号后四位、收款码；改一次 `pm clear` 就能让支付
 * 凭据失效；点一下 `am start` 就能拉起付款页。这些后果都不该由一次模型调用决定。
 *
 * 名单是硬编码的，没有开关，也不从网络更新 —— 一份可以关掉的名单等于没有名单。判定只看两件事：
 *
 *  1. 命令或路径里出现了受保护的包名（`/data/data/com.tencent.mm/...`、`pm clear com.eg...`）；
 *  2. 命令试图整棵读取 `/data/data`、`/data/user/0` 这类根目录 —— 通配符会把支付 App 一起带走，
 *     这时按「可能读到」处理，宁可拒绝。`ls`、`du`、`stat` 这种只看元数据的命令不在其中。
 *
 * 这是一道闸门，不是沙箱：它拦的是模型递过来的命令，不是内核里的访问控制。要真正做到硬隔离，
 * 得靠 SELinux 域，那是另一个量级的工程。文档里也是这么写的。
 */
object PaymentGuard {

    /** 拒绝时回给访客的错误码；冒号后面是命中的包名。 */
    const val REFUSED = "payment_guard"

    /** 整棵目录被带走时回的错误码。 */
    const val BULK = "payment_guard_bulk"

    /**
     * 精确包名。钱包、支付通道、以及「支付就住在里面」的超级 App。
     *
     * 微信（`com.tencent.mm`）整包在列，不按插件拆：微信支付、收款码、账单都在同一个
     * `/data/data/com.tencent.mm` 下，按目录分不开。这条会连带挡住聊天数据，是刻意的取舍 ——
     * 少读一个聊天记录，比多读一份账单便宜。
     */
    private val EXACT = setOf(
        // 支付通道与钱包
        "com.eg.android.AlipayGphone",
        "com.eg.android.AlipayGphoneRC",
        "com.alipay.android.app",
        "com.tencent.mm",
        "com.tencent.mobileqq", // QQ 钱包与 QQ 支付
        "com.unionpay",
        "com.unionpay.mobilepay",
        "cn.gov.pbc.dcep", // 数字人民币
        "com.antfortune.wealth", // 蚂蚁财富
        "com.jd.jrapp", // 京东金融
        "com.duxiaoman.wallet", // 度小满钱包
        "com.paypal.android.p2pmobile",
        "com.google.android.apps.walletnfcrel", // Google 钱包
        "com.samsung.android.spay",
        "com.samsung.android.spayfw",
        "com.miui.wallet",
        "com.huawei.wallet",
        "com.huawei.android.hwpay",
        "com.tenpay.android",
        // 银行客户端
        "cmb.pb", // 招商银行
        "com.android.bankabc", // 农业银行
        "com.bankcomm.Bankcomm", // 交通银行
        "com.chinamworld.main", // 建设银行
        "com.chinamworld.bocmbci", // 中国银行
        "com.yitong.mbank.psbc", // 邮储银行
        "com.ecitic.bank.mobile", // 中信银行
        "com.cmbc.cc.mbank", // 民生银行
        "com.cib.xyk", // 兴业银行
        "com.pingan.paces.ccms", // 平安银行
        "com.cebbank.mobile.cemb", // 光大银行
        "com.cgbchina.xpt", // 广发银行
        "com.hxb.mobile.client", // 华夏银行
        "com.spdbccc.app", // 浦发银行
    )

    /**
     * 包名前缀：同一家银行常有好几个客户端（信用卡、企业版、境外版），逐个列会漏。
     * 每个都以 `.` 结尾，避免 `com.icbc` 这种前缀把 `com.icbcx` 也算进来。
     */
    private val PREFIX = listOf(
        "com.tencent.mm.",
        "com.eg.android.AlipayGphone.",
        "com.unionpay.",
        "com.icbc.", // 工商银行
        "com.chinamworld.",
        "com.bankcomm.",
        "com.spdbccc.",
        "com.ecitic.",
        "com.cmbc.",
        "com.cib.",
        "com.pingan.paces.",
        "com.cebbank.",
        "com.cgbchina.",
        "com.hxb.",
        "com.yitong.mbank.",
        "com.antfortune.",
        "com.jd.jr",
        "com.paypal.",
        "com.samsung.android.spay.",
    )

    /** 受保护的包名总数，状态页拿它显示「覆盖了多少个」。 */
    val size: Int get() = EXACT.size + PREFIX.size

    fun isProtected(pkg: String): Boolean {
        if (pkg.isEmpty()) return false
        if (pkg in EXACT) return true
        return PREFIX.any { pkg.startsWith(it) }
    }

    /** 包名形状的 token：至少一个点，字母开头。`/data/data/com.tencent.mm/x` 里也能认出来。 */
    private val TOKEN = Regex("""[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+""")

    /** 命令里出现的受保护包名，去重后返回。 */
    fun packagesIn(text: String): List<String> =
        TOKEN.findAll(text).map { it.value }.filter { isProtected(it) }.map { it.trimEnd('.') }.distinct().toList()

    /** 各应用私有数据所在的目录：路径前缀 -> 去掉前缀后第一个路径段就是包名。 */
    private val DATA_PREFIXES = listOf(
        "/data/data/",
        "/data/user/0/",
        "/data/user_de/0/",
        "/data/user/999/",
        "/data/app/",
        "/data/misc/profiles/cur/0/",
        "/data/misc/profiles/ref/0/",
        "/sdcard/Android/data/",
        "/storage/emulated/0/Android/data/",
        "/storage/self/primary/Android/data/",
    )

    /** 只看元数据、不看内容的命令：整棵目录上允许。 */
    private val METADATA_ONLY = Regex("(^|[\\s;&|(])(ls|ll|du|df|stat|find|tree)\\b")

    /** 会把内容整片搬走的命令。 */
    private val BULK_TOOL = Regex(
        "(^|[\\s;&|(])(tar|zip|unzip|cp|rsync|scp|dd|grep|rg|strings|sqlite3|base64|xxd|od|cat|less|more|split|pull)\\b",
    )

    /** `/data/data` 本身，或者它下面的通配符：整棵树都在射程内。 */
    private val TREE = Regex("/data/(data|user/0|user_de/0)(/\\*[^\\s]*)?(\\s|\$|[\"';|&)])")

    /** `find -exec` / `-delete`：命令里套命令，元数据的豁免就不成立了。 */
    private val EXEC = Regex("\\s-(exec|execdir|ok|delete)\\b")

    private fun normalize(path: String): String {
        var p = path.trim().trim('\'', '"')
        while (p.contains("//")) p = p.replace("//", "/")
        if (p.length > 1) p = p.trimEnd('/')
        return p
    }

    /** 路径落在某个受保护应用的数据目录里时返回拒绝码。 */
    fun pathRefusal(path: String): String? {
        val p = normalize(path)
        if (p.isEmpty()) return null
        for (prefix in DATA_PREFIXES) {
            if (!p.startsWith(prefix)) continue
            // `/data/app/com.foo-1/base.apk`：包名后面跟着 `-<随机后缀>`。
            val pkg = p.removePrefix(prefix).substringBefore('/').substringBefore('-')
            if (isProtected(pkg)) return "$REFUSED:$pkg"
        }
        return null
    }

    /**
     * 命令层面的判定：先看有没有点名受保护的包，再看是不是要整棵搬走。
     * 命中就返回拒绝码，`null` 表示放行。
     */
    fun commandRefusal(command: String): String? {
        val text = command.replace('\n', ' ')
        packagesIn(text).firstOrNull()?.let { return "$REFUSED:$it" }
        // `find ... -exec cat` 看着像只看元数据，其实把内容读出来了，所以 -exec 一出现就不再豁免。
        val metadataOnly = METADATA_ONLY.containsMatchIn(text) && !EXEC.containsMatchIn(text)
        if (TREE.containsMatchIn(text) && BULK_TOOL.containsMatchIn(text) && !metadataOnly) {
            return BULK
        }
        return null
    }

    /** 拒绝码给人看的一句话；页面和日志都用它。 */
    fun explain(code: String): String = when {
        code == BULK -> "整棵 /data/data 会被一起读走，其中包含支付应用"
        code.startsWith("$REFUSED:") -> "支付保护：${code.removePrefix("$REFUSED:")} 不允许访问"
        else -> code
    }
}
