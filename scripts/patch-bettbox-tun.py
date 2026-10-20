#!/usr/bin/env python3
"""
把 intranet192Hosts 写进 Bettbox 的 patchClashConfig.tun.route-address。

背景
    Bettbox（macOS / NetworkExtension）不消费覆写脚本里的 tun 段，但它的
    「内核配置」页同样没有暴露 tun 设备的输入框；patchClashConfig.tun 存在
    配置文件里，是这个客户端唯一「自己维护」的路由来源。写进去后由 NE 在
    连接时添加、断开时回收，比外部注入 OS 路由更干净。

用法
    必须先完全退出 Bettbox（应用运行中改文件会被内存状态覆盖）：
        python3 scripts/patch-bettbox-tun.py            # 预演，只打印
        python3 scripts/patch-bettbox-tun.py --apply    # 写入（自动备份）

实测结论（2026-10-20）
    写入后客户端**不会重置**该字段，但 macOS 网络扩展**也不消费**它：
    值留在 config.json 里，路由表始终没有对应的 /32（与宿主同网段的
    192.168.0.168 仍被 en0 的 ARP 主机路由抢走）。因此本脚本当前只作为
    验证客户端行为的诊断工具保留，实际方案见 docs 第十二节（tunnels）。

回滚
    备份文件为 config.json.bak.<时间戳>，直接覆盖回去即可。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

CFG = os.path.expanduser("~/Library/Application Support/com.appshub.bettbox/config.json")
SCRIPT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Script", "mihomoScript.js")
)


def hosts_from_script():
    """从覆写脚本解析 intranet192Hosts，避免这里再抄一份主机清单"""
    with open(SCRIPT, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"const intranet192Hosts\s*=\s*\[(.*?)\]", src, re.S)
    if not m:
        sys.exit("未能在 mihomoScript.js 中定位 intranet192Hosts")
    return re.findall(r"'([^']+)'", m.group(1))


def bettbox_running():
    out = subprocess.run(
        ["/usr/bin/pgrep", "-f", "Bettbox"], capture_output=True, text=True
    ).stdout.strip()
    return bool(out)


def main():
    apply = "--apply" in sys.argv
    cidrs = hosts_from_script()
    if not cidrs:
        sys.exit("intranet192Hosts 为空，拒绝写入")

    with open(CFG, encoding="utf-8") as f:
        cfg = json.load(f)
    tun = cfg.setdefault("patchClashConfig", {}).setdefault("tun", {})
    before = list(tun.get("route-address") or [])

    print(f"来源  : {SCRIPT}")
    print(f"目标  : {CFG}")
    print(f"现状  : {before}")
    print(f"目标值: {cidrs}")

    if before == cidrs:
        print("\n已是目标值，无需修改")
        return
    if not apply:
        print("\n预演模式，未写入。加 --apply 执行。")
        return
    if bettbox_running():
        sys.exit("\nBettbox 仍在运行，请先完全退出（Cmd+Q），否则写入会被内存状态覆盖")

    bak = f"{CFG}.bak.{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(CFG, bak)
    tun["route-address"] = cidrs
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n已写入，备份: {bak}")


if __name__ == "__main__":
    main()
