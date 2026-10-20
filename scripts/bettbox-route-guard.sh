#!/bin/bash
#
# bettbox-route-guard.sh
#
# 背景
#   Bettbox（macOS / NetworkExtension）不消费 mihomo 的 tun.route-address：
#   它用内置的 patchClashConfig.tun 整段替换脚本的 tun 段（auto-route=false、
#   route-address=[]）。因此与宿主同网段的内网主机（如 Jenkins 192.168.0.168）
#   会被 en0 的 connected 路由与 ARP 主机路由抢先，流量根本进不了隧道。
#
# 作用
#   TUN 接口出现后，为白名单主机补一条指向该接口的 /32 路由；接口消失后
#   清理残留。每 5 秒由 LaunchDaemon 触发一次，天然支持断线重连（utun 编号变化）。
#
# 约束
#   1) 只操作白名单里的具体主机，绝不触碰 192.168.0.0/24 的 connected 路由，
#      以免把本机局域网（打印机、NAS、路由器）一起劫持；
#   2) 主机清单必须与 Script/mihomoScript.js 的 intranetConflictHosts 保持一致，
#      Test/suites/integration.js 有断言守护，改一处漏另一处会测试失败。
#
# 现状（2026-10-20 之后）
#   家用网段已改为 192.168.88.0/24，与公司 192.168.0.0/24 不再重叠，冲突面为 0，
#   本脚本**不需要安装**，仅作为「临时接入 192.168.0.0/24 的 Wi-Fi 时」的备用手段保留。
#
# 安装 / 卸载见 docs/intranet-routing-analysis.md 第十一节
#
set -u
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH

# 由 intranetConflictHosts 展开而来（当前只有 Jenkins 一台；整段段不需要 OS 路由，走 0/0 拆分即可）
HOSTS="192.168.0.168"

STATE=/var/run/bettbox-route-guard.state
LOG=/var/log/bettbox-route-guard.log
FAKE_PREFIX="198.18."
MAX_LOG_LINES=500

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"
}

# Bettbox 的 TUN 接口地址必落在 fake-ip 段（198.18.0.1/15），据此识别，
# 不依赖 utun 编号，重连后编号变化也能跟上。
find_tun() {
  for i in $(ifconfig -l 2>/dev/null); do
    case "$i" in
      utun*)
        if ifconfig "$i" 2>/dev/null | grep -q "inet ${FAKE_PREFIX}"; then
          printf '%s\n' "$i"
          return 0
        fi
        ;;
    esac
  done
  return 1
}

iface_of() {
  route -n get -host "$1" 2>/dev/null | awk '/^[[:space:]]*interface:/{print $2; exit}'
}

# 已存在指向别的接口的路由时用 change，不存在时用 add；输出单字符标记便于记日志
apply_route() {
  host=$1
  tun=$2
  if route -n change -host "$host" -interface "$tun" >/dev/null 2>&1; then
    printf '~'
    return 0
  fi
  if route -n add -host "$host" -interface "$tun" >/dev/null 2>&1; then
    printf '+'
    return 0
  fi
  printf '!'
  return 1
}

TUN=$(find_tun) || TUN=""
CHANGES=""

if [ -n "$TUN" ]; then
  for h in $HOSTS; do
    cur=$(iface_of "$h")
    [ "$cur" = "$TUN" ] && continue
    CHANGES="${CHANGES}$(apply_route "$h" "$TUN")$h "
  done
else
  # 未连接时清理指向已消失接口的残留，避免黑洞路由
  for h in $HOSTS; do
    cur=$(iface_of "$h")
    case "$cur" in
      utun*)
        if ! ifconfig "$cur" >/dev/null 2>&1; then
          route -n delete -host "$h" >/dev/null 2>&1 && CHANGES="${CHANGES}-$h "
        fi
        ;;
    esac
  done
fi

SIG="${TUN:-none}|${CHANGES:-}"
if [ "$SIG" != "$(cat "$STATE" 2>/dev/null)" ]; then
  log "tun=${TUN:-none} changes=${CHANGES:-none}"
  printf '%s\n' "$SIG" > "$STATE"
fi

if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" | tr -d ' ')" -gt "$MAX_LOG_LINES" ]; then
  tail -n 300 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

exit 0
