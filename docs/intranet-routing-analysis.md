# 内网分流方案（Bettbox + docker-atrust）

> 对象：`Script/mihomoScript.js`（全量版）、`Script/Script.js`（精简版）中的内网配置
> 环境：macOS + Bettbox（纯 TUN）+ `atrust` 容器（OrbStack，`127.0.0.1:1080` socks5）
> 更新：2026-10-20 · 代码 `bfb43fc` · 测试 208/0

本文只记录**当前有效结论**与**踩过的坑**，不保留排查过程的时间线。

---

## 1. 结论

1. 内网访问是「**路由层 → 规则层 → 出口层**」三层串联，任一环断掉都表现为「内网不通」，但修法完全不同。
2. 规则层与出口层一直是对的；历史上唯一的硬故障是 **macOS 路由优先级**：`192.168.0.168` 与本机 LAN 同段，被 `en0` 的 `/24` + `/32 ARP` 路由抢走，包根本没进 mihomo。
3. **macOS 上 `tun.route-address` 是死字段**：Bettbox 会保存但不会转成网络扩展的路由，`tun` 段整体被客户端 `patchClashConfig.tun` 覆盖（见第 5 节）。
4. 最终解法是**把家用网段挪出冲突范围**（`192.168.0.0/24` → `192.168.88.0/24`），冲突面归零，不需要 tunnels、不需要 root 路由、不需要守护进程。
5. 规则层已按段收敛：内网 IPv4 覆盖 **180/193（93.3%）**，剩余 12 条属结构性（整段放行会把本机 LAN 拖进隧道）。

---

## 2. 链路结构

```
应用 / 浏览器（无系统代理，纯 TUN）
   ▼
utun4  198.18.0.1/30  mtu 9000        ← Bettbox 网络扩展
   ▼
mihomo 规则引擎：intranetRules → prefixRules → 功能组 → 兜底
   ├─ 命中「内网」 ──► 内网-aTrust（socks5 127.0.0.1:1080）
   │                     ▼ OrbStack 端口转发 → atrust 容器（独立 netns）
   │                     ▼ aTrust 隧道 10.0.216.116/24 → 公司内网
   └─ 其余 ──► 代理节点 / 直连
```

| 层 | 生效条件 | 对应配置 | 失效表现 |
| --- | --- | --- | --- |
| **L1 路由** | 目的 IP 必须落进 `utunN` | 本机无更精确路由；`route-exclude-address` 不含该段 | 包不进 mihomo，规则形同虚设 |
| **L2 规则** | 命中 `intranetRules`，且排在 `cn_ip` / `private_ip` 之前 | `rules = [...intranetRules, ...prefixRules, ...]` | 命中「直连」→ 走公网出口，超时 |
| **L3 出口** | 「内网」组选中 `内网-aTrust`，容器在线 | `127.0.0.1:1080` | 内网组报错 / 全红 |

> 两条公网 IP（`113.125.201.130/31`、`222.222.216.74/32`）必须前置的真正理由是**防 `cn_ip` 抢走**——它们落在中国大陆公网段，顺序靠后会被判直连。**不要把它们挪到 `prefixRules` 之后。**

---

## 3. 现行规则

```js
// 与家用 LAN 无交集的段：整段放行，公司新增主机不必改代码
const intranet192Segments = ['192.168.5.0/24', '192.168.45.0/24', '192.168.73.0/24'];

// 与家用 LAN 同段过的主机：只能逐台，且需同时进 TUN route-address
const intranetConflictHosts = ['192.168.0.168/32']; // Jenkins

const intranetRules = [
  'DOMAIN,sslvpn.jbysoft.com,直连',   // aTrust 网关必须直连
  'DOMAIN,git.sjgjj.cn,内网',         // 内网 GitLab
  'IP-CIDR,10.0.0.0/8,内网,no-resolve',
  'IP-CIDR,113.125.201.130/31,内网,no-resolve',
  'IP-CIDR,222.222.216.74/32,内网,no-resolve',
  ...intranet192Segments.map((c) => `IP-CIDR,${c},内网,no-resolve`),
  ...intranetConflictHosts.map((c) => `IP-CIDR,${c},内网,no-resolve`),
];
```

`tun` 段：

```js
'route-address': [...intranetConflictHosts],   // 只放 /32，整段会把本机 LAN 拖进隧道
'route-exclude-address': ['127.0.0.0/8','::1/128','169.254.0.0/16','172.16.0.0/12','fe80::/10','fc00::/7'],
```

要点：

- `10.0.0.0/8` 与 `192.168.0.0/16` **不得**出现在排除清单，否则内网流量进不了分流。
- 按段放行不会误伤本机：本机若有该段 connected route（如真在 `192.168.5.0/24` 办公），`/24` 比 TUN 的 `/1` 精确，包不进隧道 —— **路由层永远优先于规则层**。
- 规则顺序、`route-address` 只允许 `/32`、排除清单不含内网段，均有测试断言守护。

---

## 4. 覆盖率

aTrust 共下发 235 条：IPv4 214（其中 21 条是 `198.18.0.0/16` fake-ip 假路由）、IPv6 21。真实 IPv4 目标 **193 条**。

| 分类 | 条数 | 覆盖 | 说明 |
| --- | --- | --- | --- |
| `10.0.0.0/8` 各段 | 149 | 149 | 一条粗规则兜住 |
| `192.168.5.0/24` | 14 | 14 | 整段 |
| `192.168.45.0/24` | 15 | 15 | 整段 |
| `192.168.73.0/24` | 2 | 2 | 整段（端口 8000-9000） |
| `192.168.0.0/24` | 13 | 1 | 逐台（`.168`），结构性缺口 |
| IPv6 `fdff:5341:...` | 21 | 0 | TUN 无 v6 路由，**故意不覆盖** |
| **合计** | **193** | **180** | **93.3%** |

- 剩余 12 条全在 `192.168.0.0/24`：整段放行会把本机 LAN 一起拖进隧道，只能逐台加。
- IPv6 不补规则：实测 `utunN` 上没有任何 IPv6 路由，补 `IP-CIDR6` 只会造出「规则命中却不可达」的假象。
- 复核方式：拿 atrust 项目的 `docs/intranet-routes.csv` 逐条做最长前缀匹配即可。

---

## 5. 关键限制：macOS 上 `tun.route-address` 无效

用脚本 / 客户端注入 / 内核实测三方对比，`tun` 段**每一项**都跟客户端 `patchClashConfig.tun`、零项跟脚本：

| 字段 | 脚本 | `patchClashConfig.tun` | `utun` 实测 |
| --- | --- | --- | --- |
| `auto-route` / `strict-route` / `auto-redirect` | true | false | 只有 `0/0` 八条拆分，无 `0.0.0.0/1`+`128.0.0.0/1` |
| `route-address` | 5 条 `/32` | `[]` | **0 条** |
| `route-exclude-address` | 7 条 | `[]` | 无 |
| `dns-hijack` | `any:53` + `tcp://any:53` | `any:53` | — |
| `mtu` | 未设 | 9000 | 9000 |

结论与推论：

1. `tun` 段被客户端**整段替换**，脚本里那段是死的；历史上「从排除清单移除 `10/8`」的提交其实从未生效，10/8 能通是因为客户端 patch 的排除清单本来就空。
2. 即使把 5 条 `/32` 写进 `patchClashConfig.tun.route-address`（曾用 `scripts/patch-bettbox-tun.py` 实测，该脚本已随问题解决移除），客户端**保留但不消费**：网络扩展的接管范围固定为 `0/0` 八条拆分，而 macOS 按最长前缀匹配，`en0` 的 `/24` connected 与 `/32` ARP 主机路由永远更精确。
3. `192.168.5/45/73` 能通是 `0/0` 拆分的副产品，**不能当作 `route-address` 生效的证据**（这是最容易误判的地方）。
4. macOS 版 Bettbox「内核配置 → Tunnel」页里只有「添加转发」（`tunnels`），**没有任何界面入口能编辑 tun 设备段**。

> 该限制只影响「与本机 LAN 同段」的目标。Windows / Linux 的 mihomo CLI 会加 `/32` 或改 metric，`route-address` 在那里是有效的。

---

## 6. 客户端四个网络开关

`config.json` 的 `networkProps` 控制「设置 → 网络」页，四项都能显著改变行为：

| 字段 | 当前 | 作用 | 备注 |
| --- | --- | --- | --- |
| `systemProxy` | `false` | 系统代理总开关 | 关时 `scutil --proxy` 全为 0，纯 TUN 工作 |
| `bypassDomain` | 26 条 | **系统代理例外列表**（`networksetup -setproxybypassdomains`） | 只在系统代理模式生效 |
| `bypassPrivateRoute` | `false` | 私有网段排除出 TUN（对应 `route-exclude-address`） | ⚠ 打开会断内网，见下 |
| `autoSetSystemDns` | `true` | 连接时改系统 DNS，断开时按 `macos_system_dns_backup.json` 还原 | 与 DNS 覆写是两个东西 |

### `bypassDomain` 是系统代理例外，不是 TUN 排除

- 命中列表的目标不会发给代理端口，而是直连；只在系统代理模式下有意义。
- TUN 是三层路由接管，**没有「绕过域名」的概念**，所以它不影响内网分流。
- 实证（TUN 模式）：`www.jd.com` 解析为 `198.18.0.24`（fake-ip），说明列表未生效；若生效则应返回真实公网 IP。
- 内容分三组：厂商默认的「代理下会异常」站点（`*.jd.com`、`*.360buyimg.com`、`*.zhihu.com`、`*.zhimg.com`）、本机回环与 `*.local`、RFC1918 三个私网段。
- 其中 `10.*` 与 `192.168.*` 正好是公司内网段。**只在系统代理模式下需要留意**；若将来要用系统代理访问内网，建议删掉这两条（保留 `172.*` 给 Docker）。

### ⚠ `bypassPrivateRoute` 不要打开

它的清单是 `127.0.0.0/8`、`::1/128`、`172.16.0.0/12`、`169.254.0.0/16`、`fd00::/8`、`fe80::/10`，而界面勾选「排除私有网段」通常还会叠加 `10/8`、`192.168/16`。一旦打开，内网流量会被排除出 TUN，症状是「公网正常、内网全超时」，极难一眼定位。**保持 `false`。** 脚本里的 `route-exclude-address` 已经是等价且可控的写法。

---

## 7. 备选方案（当前未启用）

| 方案 | 做法 | 代价 | 适用 |
| --- | --- | --- | --- |
| `tunnels` 端口转发 | 内核配置 → Tunnel：`tcp 127.0.0.1:8080 → 192.168.0.168:8080 via 内网` | 占用本地端口，访问地址变成 `127.0.0.1` | 必须保留同段目标时最轻的方案；**不查本机路由**，冲突天然绕开 |
| OS 路由守护 | `sudo route add -host <ip> -interface utunN`，用 LaunchDaemon 每 5s 自愈 | 需 root 常驻 | 必须保持原 IP 访问、且不能改网段 |
| 改本机网段 | 家用 LAN 挪到不重叠段 | 一次改路由器 | **治本**，可消除整段冲突 |

网段改为 `192.168.88.0/24` 后，`192.168.0.0/24` 不再与本机 LAN 重叠，冲突面归零，因此上表三种方案都不需要启用。

此前为「保持原 IP 访问」准备过两样东西，已随问题解决一并移除：

- route guard（`bettbox-route-guard.sh` + LaunchDaemon plist，按接口地址落在 `198.18.0.1/15` 识别 TUN、每 5s 补白名单 `/32`，从未安装）
- `patch-bettbox-tun.py`（把 `intranetConflictHosts` 写进客户端 `tun.route-address`，仅用于诊断）

对应的测试断言（守护脚本 `HOSTS` 与 `tun.route-address` 一致性）也已删除。`tun.route-address` 现在只保留 `192.168.0.168/32` 作为文档性记录，macOS 不消费。

---

## 8. 与 atrust 项目的联动

1. **`198.18` 有两份**：Bettbox 用 `198.18.0.1/15` 做 fake-ip，aTrust 客户端内部用 `198.18.2.53`。现在靠 netns 隔离相安无事，**`atrust` 容器绝不能改 `--net host`**，否则两套 fake-ip 正面冲突。
2. **容器网段**：`192.168.97.0/24`（OrbStack `bridge101`）与公司下发段无交集；若公司将来下发同段，容器路由会被 replace，隧道直接崩。
3. **无自愈**：aTrust 无自动重连（上游 #265），内网组是 `select` 也没有 fallback。容器 down / 掉登录就是硬故障，需人工介入；**不要加 `url-test`**（测速 URL 走不通会自动切直连，故障更隐蔽）。
4. **网关直连双保险**：容器侧的 `extra_hosts` + `pin_gateway_host` 解决 `198.18.2.53` 自环；脚本规则 ① `DOMAIN,sslvpn.jbysoft.com,直连` 是同一问题在代理侧的另一道保险，**两者必须同时存在**。

---

## 9. 待确认

1. **`172.168.0.0/16` 是否该排除**（当前**已从排除清单移除**）。`docs/mihomoScript-analysis.md` 记录 2026-08-29 曾确认「有意绕过代理，保留」，但 `bfb43fc` 按「非 RFC1918、疑似 `172.16/12` 笔误」删除并加了禁止回归的测试。**两处记录冲突，暂按移除执行，待确认。**
2. Jenkins 是否有可解析域名？有则 `DOMAIN,...` 比 IP 规则更稳（fake-ip 天然在 TUN 内）。
3. `192.168.73.49–50:8000-9000` 具体是什么服务。
4. 本机是否还需要跑本地 k8s 或其它 `10.x` 隧道（决定是否要给 `10/8` 开口子）。

---

## 10. 变更记录

| 提交 | 内容 |
| --- | --- |
| `8c28c70` | 规则层与 `route-address` 同源生成；精简版补齐；测试两版共用 |
| `680b4a8` | 新增路由守护脚本（备选，未安装） |
| `2975f92` | 记录 `tunnels` 方案与「客户端不消费 `route-address`」结论 |
| `a7d2dfb` | 记录家用网段迁移（治本） |
| `bfb43fc` | 192.168 规则按段收敛（78.2% → 93.3%）；移除 `172.168.0.0/16`（见第 9 节） |

---

## 附录：诊断命令

```bash
# 谁在接管某个目标（最关键的一条）
route -n get -host 192.168.0.168 | grep -E 'gateway|interface'
netstat -rn -f inet | grep -E '^192\.168|^10\.'

# TUN 与系统代理状态
ifconfig | grep -B1 'inet 198.18'
scutil --proxy | grep -E 'HTTPEnable|SOCKSEnable'

# 两条路径对比：容器 socks5 vs 系统
curl -s -o /dev/null -w '%{http_code}\n' --socks5-hostname 127.0.0.1:1080 http://192.168.0.168:8080/
curl -s --noproxy '*' -o /dev/null -w '%{http_code}\n' http://192.168.0.168:8080/

# 脚本是否真的加载了
ls -l ~/Library/Application\ Support/com.appshub.bettbox/scripts/*.js
diff ~/Library/Application\ Support/com.appshub.bettbox/scripts/*.js Script/mihomoScript.js
```

> 本机 shell 有 `http_proxy=127.0.0.1:63368`（沙箱代理），curl 必须加 `--noproxy '*'`，否则拿到的是 `upstream connect failed` 的 502，极易误判成服务故障。
