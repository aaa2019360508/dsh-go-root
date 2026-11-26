package io.github.ccch1mneyyy.dsh_app.root

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 支付保护是 root 模式里唯一不随访问范围变化的规则，所以它值得单独一组用例：
 * 命中要稳（点名了就必须拒），放行也要稳（普通应用、普通目录不能被误伤）。
 */
class PaymentGuardTest {

    @Test fun paymentPackagesAreRecognised() {
        for (pkg in listOf(
            "com.tencent.mm",
            "com.eg.android.AlipayGphone",
            "com.unionpay",
            "com.icbc.mobile", // 前缀：工行信用卡、企业版都算
            "cmb.pb",
            "com.paypal.android.p2pmobile",
        )) {
            assertTrue(pkg, PaymentGuard.isProtected(pkg))
        }
    }

    @Test fun ordinaryPackagesAreNot() {
        for (pkg in listOf(
            "com.android.settings",
            "com.tencent.tmgp.sgame", // 腾讯游戏，不是支付
            "com.icbcx", // 前缀只认 `com.icbc.`，不能把它带进来
            "org.telegram.messenger",
            "",
        )) {
            assertTrue(pkg, !PaymentGuard.isProtected(pkg))
        }
    }

    @Test fun pathsIntoPaymentAppsAreRefused() {
        assertEquals(
            "payment_guard:com.tencent.mm",
            PaymentGuard.pathRefusal("/data/data/com.tencent.mm/MicroMsg/x.db"),
        )
        assertEquals(
            "payment_guard:com.eg.android.AlipayGphone",
            PaymentGuard.pathRefusal("/data/user/0/com.eg.android.AlipayGphone/files/a"),
        )
        assertEquals(
            "payment_guard:com.tencent.mm",
            PaymentGuard.pathRefusal("/data/app/com.tencent.mm-1/base.apk"),
        )
        assertNull(PaymentGuard.pathRefusal("/data/data/com.android.settings/shared_prefs/x.xml"))
        assertNull(PaymentGuard.pathRefusal("/sdcard/Download/a.txt"))
    }

    @Test fun commandsThatNameAPaymentAppAreRefused() {
        for (command in listOf(
            "pm clear com.tencent.mm",
            "am start -n com.eg.android.AlipayGphone/.Main",
            "cat /data/data/com.tencent.mm/MicroMsg/x.db",
            "cp -r /data/data/com.unionpay /sdcard/u",
            "sqlite3 /data/data/com.jd.jrapp/databases/a.db .dump",
        )) {
            val refusal = PaymentGuard.commandRefusal(command)
            assertTrue(command, refusal != null && refusal.startsWith(PaymentGuard.REFUSED))
        }
    }

    /**
     * 通配符会把支付应用一起带走，所以在整棵 /data/data 上做内容读取一律按「可能读到」处理。
     * 只看元数据的命令（ls / du / stat / find）不受影响 —— 否则连 `du -sh` 配通配符都跑不了。
     */
    @Test fun bulkReadsOfTheWholeTreeAreRefused() {
        for (command in listOf(
            "cp -r /data/data /sdcard/backup",
            "tar -czf /sdcard/x.tgz /data/data",
            "grep -r needle /data/data",
            "cat /data/data/*/shared_prefs/x.xml",
            "find /data/data -name '*.db' -exec cat {} +",
        )) {
            assertEquals(command, PaymentGuard.BULK, PaymentGuard.commandRefusal(command))
        }
    }

    @Test fun metadataAndSingleAppReadsStayAllowed() {
        for (command in listOf(
            "ls /data/data",
            "du -sh /data/data/*",
            "stat /data/data",
            "find /data/data -maxdepth 1",
            "grep -r needle /data/data/com.android.settings",
            "cat /data/data/com.android.settings/shared_prefs/x.xml",
            "pm list packages -3",
        )) {
            assertNull(command, PaymentGuard.commandRefusal(command))
        }
    }
}
