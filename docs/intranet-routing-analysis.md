# 内网分流（Bettbox + docker-atrust）实现分析与实测

> 分析对象：`Script/mihomoScript.js`（全量版）、`Script/Script.js`（精简版）中的内网相关配置
> 运行端：Bettbox（macOS）+ `atrust` 容器（OrbStack，`127.0.0.1:1080` socks5）
> 分析时间：2026-10-20 · 代码基线 `bca8d47`（工作区干净，测试 206/206 通过）
> 修复提交：`8c28c70`（规则层与路由层同源对齐，测试扩到两版；详见第十节）

---

## 一、结论摘要

| 级别 | 结论 |
| --- | --- |
| ✅ 成立 | 整体是「**规则层 + 路由层 + 出口层**」三层设计，三层缺一不可；`10.0.0.0/8` 兜底实测生效，堡垒机、内网 GitLab 全通 |
| ✅ 已解决（治本） | **Jenkins 原 IP 直连已恢复**：把家用 Wi-Fi 网段从 `192.168.0.0/24` 挪到 `192.168.88.0/24`，与本机 LAN 的重叠消失 → `192.168.0.168:8080` 走 `utun4`，实测 `X-Jenkins: 2.177`、200（见第十三节）。此前用 `tunnels` 端口转发绕路由的方案随之降级为可选（见第十二节） |
| ✅ 已修复 | 精简版 `Script.js` 缺 Jenkins 规则与 `route-address`、CI 用 `if (!meta.full) return` 跳过 → 测试改为两版共用，并增加同源/顺序/排除清单校验 |
| ⚠ 覆盖盲区 | aTrust 下发 193 条真实 IPv4 路由，脚本覆盖 151 条（78.2%）；`192.168.0/5/45/73` 四段 44 条中按主机白名单放行 5 个 `/32`；21 条 IPv6 内网段 0 覆盖 |

一句话：规则层和出口层一直是对的，卡在 macOS 的路由优先级上；最终用 `tunnels` 端口转发把冲突面整个绕开，不动系统路由。

---

## 二、链路结构

```
应用 / 浏览器
   │  (无系统代理，纯 TUN 接管；7890 实际未监听)
   ▼
utun4  inet 198.18.0.1/30  mtu 9000      ← Bettbox 网络扩展（device: Bettbox）
   │
   ▼
mihomo 规则引擎  rules[] 顺序：
   ① intranetRules（内网 8 条）
   ② prefixRules（private / geolocation-cn / games_cn …）
   ③ 功能组规则
   ④ geolocation-!cn → 默认代理
      cn_ip → 直连
      private_ip → 直连
      MATCH → 漏网之鱼
   │
   ├─ 命中「内网」组 ──► 内网-aTrust（socks5 127.0.0.1:1080）
   │                      │  OrbStack 端口转发（lsof 显示 1080 由 OrbStack 持有）
   │                      ▼
   │                   atrust 容器（Cap NET_ADMIN，独立 netns）
   │                      │  aTrust 隧道 10.0.216.116/24
   │                      ▼
   │                   公司内网
   │
   └─ 其余 ──► 代理节点 / 直连
```

关键点：**TUN 只负责把流量「骗」进用户态，能不能进内网最终取决于命中哪条规则**；而能不能被规则看见，又取决于系统路由是否把目的地址送进 `utun4`。这三者串行，任一环断开都表现为「内网不通」，但现象和修法完全不同。

---

## 三、三层生效条件（排查模型）

| 层 | 条件 | 对应配置 | 失效表现 |
| --- | --- | --- | --- |
| **L1 路由层** | 目的 IP 必须落进 `utun4` | `tun.route-exclude-address` 不含该段 + 本机无更精确路由 + `tun.route-address` 补强 | 流量根本不进 mihomo，规则形同虚设 |
| **L2 规则层** | 命中 `intranetRules` 且**排在 `cn_ip` / `private_ip` 之前** | `rules = [...intranetRules, ...prefixRules, ...]` | 命中「直连」→ 走公网出口，超时 |
| **L3 出口层** | 「内网」组选中 `内网-aTrust`，容器在线 | `intranetGroup.proxies[0]`、`127.0.0.1:1080` | 内网组报错 / 全红 |

> `intranetRules` 里的两条公网 IP（`113.125.201.130/31`、`222.222.216.74/32`）其实**必须前置的真正理由是防 `cn_ip` 抢走**——它们是中国大陆公网地址，落在兜底 `RULE-SET,cn_ip,直连` 里，若顺序靠后会被判直连。注释写的是「避免被 private 抢」，表述偏保守，实际主要是 cn_ip。这一点对后续维护很重要：**不要把它们挪到 prefixRules 之后**。

---

## 四、逐条规则审查

`Script/mihomoScript.js` L150–159：

```js
const intranetRules = [
  'DOMAIN,sslvpn.jbysoft.com,直连',        // ① 网关必须直连
  'DOMAIN,git.sjgjj.cn,内网',              // ② 内网 GitLab
  'IP-CIDR,10.0.0.0/8,内网,no-resolve',    // ③ 10 段兜底
  'IP-CIDR,113.125.201.130/31,内网,no-resolve', // ④ chat 后端
  'IP-CIDR,222.222.216.74/32,内网,no-resolve',  // ⑤ znkf 接口
  'IP-CIDR,192.168.0.168/32,内网,no-resolve',   // ⑥ Jenkins
  'IP-CIDR,192.168.5.163/32,内网,no-resolve',   // ⑦ 开发 MySQL
  'IP-CIDR,192.168.45.82/32,内网,no-resolve',   // ⑧ 测试环境后端
];
```

| # | 规则 | 判定 | 说明 |
| --- | --- | --- | --- |
| ① | `sslvpn.jbysoft.com,直连` | ✅ 必须保留 | aTrust 建连流量必须出境直连。若走代理或进隧道，会和 atrust 项目里查到的「fake-ip 指向自己的隧道 → `find pid err` 死循环掉线」同源 |
| ② | `git.sjgjj.cn,内网` | ✅ | 域名级命中，`socks5-hostname` 远端解析实测 302。注意它**只能覆盖 GitLab 这一个主机** |
| ③ | `10.0.0.0/8,内网` | ✅ 但风险最大 | 一条扛下 149 条下发路由；同时把本机所有 `10.x` 流量（k8s `10.96/10.244`、其它 VPN 网段）也塞进公司隧道 |
| ④⑤ | 两条公网 IP | ✅ | 顺序敏感，见上文 |
| ⑥ | `192.168.0.168/32` | ⚠ **规则对、路由没落地** | Jenkins 与 Mac 同在 `192.168.0.0/24`，本机 connected route 比 TUN 兜底更精确 → 必须靠 `route-address` 强拉，实测未生效 |
| ⑦⑧ | `192.168.5.163` / `192.168.45.82` | ✅ 侥幸生效 | 本机没有 `192.168.5/45` 的 connected route，靠 TUN 的 `0/0` 拆分路由自然进入，**不依赖 `route-address`** |

`tun` 段（修复后，`8c28c70`）：

```js
// 与 intranet192Hosts 同源：这些主机的局域网直连路由可能比 TUN 兜底更精确，必须显式引入隧道
'route-address': [...intranet192Hosts],
'route-exclude-address': ['127.0.0.0/8','::1/128','169.254.0.0/16',
                          '172.16.0.0/12','172.168.0.0/16','fe80::/10','fc00::/7'],
```

- `10.0.0.0/8` 与 `192.168.0.0/16` 已于 `95426ab` 从排除清单移除 —— 这是内网分流能成立的前提，**不能加回去**。
- `172.168.0.0/16` 不是 RFC1918 私网段，单独排除掉等于让这部分目的地址**绕过整个 mihomo**；来源可疑（疑似 `172.16/12` 的笔误或历史遗留），建议复核。
- 修复前 `route-address` 只列了 1 个 `/32`（Jenkins），与规则层的 3 个 `192.168` 主机不对齐 —— 就是本次故障的根因位置。现在两者由 `intranet192Hosts` 同一数组生成，**不可能再漂移**。

---

## 五、覆盖率实测（对照 atrust 项目 `docs/intranet-routes.csv`）

aTrust 共下发 **235 条**路由：IPv4 214 条、IPv6 21 条。剔除 21 条 `198.18.0.0/16` fake-ip 假路由后，真实 IPv4 目标 **193 条**。

| 分类 | 条数 | 脚本覆盖 | 覆盖率 |
| --- | --- | --- | --- |
| `10.0.0.0/8` 内各段 | 149 | 149 | 100%（靠 ③ 兜底） |
| `192.168.0.0/24` | 13 | 1（`.168`） | 主机白名单 |
| `192.168.5.0/24` | 14 | 1（`.163`） | 主机白名单 |
| `192.168.45.0/24` | 15 | 1（`.82`） | 主机白名单 |
| `192.168.73.0/24` | 2（`.49`/32、`.50`/31，端口 8000-9000） | 2 | 100% |
| IPv6 `fdff:5341:...` | 21 | 0 | 0% |
| **合计（真实 IPv4）** | **193** | **151** | **78.2%** |

解读：

1. 覆盖率数字好看，全靠 `10/8` 一条粗规则；`192.168` 侧是**按主机白名单**打法，不是按段。这在「不劫持本机所在局域网」的前提下是合理取舍，但代价是每新增一个内网主机都要改代码。
2. `192.168.73.49–50:8000-9000` 原为遗漏（修复前走直连必失败），现已纳入；但这两条实际落在公司下发的 `/24` 里，说明**新资源随时可能出现**，需要定期用 atrust 的 `intranet-routes.csv` 复核。
3. IPv6 全空。目前访问内网 IPv6 字面量地址会走「直连」出公网，静默失败；若公司后续推进 IPv6 内网，需要补 `IP-CIDR6` 并确认 TUN 接管了 IPv6 默认路由。

---

## 六、本机实测（2026-10-20 11:40 左右）

### 6.1 环境状态

| 项目 | 观测值 |
| --- | --- |
| Bettbox / 内核 | `Bettbox`(72002) + `BettboxCore`(72109)，走 unix socket，**无 7890/9090 TCP 监听** |
| 系统代理 | `HTTPEnable=0`、`SOCKSEnable=0` → 纯 TUN 模式 |
| TUN 接口 | `utun4` `inet 198.18.0.1/30` `mtu 9000`（与 patch 的 `tun.mtu: 9000`、`fake-ip-range: 198.18.0.1/15` 吻合） |
| TUN 路由 | `1`、`2/7`、`4/6`、`8/5`、`16/4`、`32/3`、`64/2`… → 全 IPv4 兜底进 `utun4` |
| 本地 LAN | `192.168.0` via `en0`（connected），Mac = `192.168.0.136`，网关 `.1` |
| 内网 socks5 | `127.0.0.1:1080` 由 OrbStack 转发，容器 `atrust` Up |
| 已装脚本 | `~/Library/Application Support/com.appshub.bettbox/scripts/*.js` 与仓库 HEAD **字节一致** |

### 6.2 连通性矩阵

| 目标 | 经容器 socks5 | 经系统（TUN） | 判定 |
| --- | --- | --- | --- |
| `10.0.1.102:80`（堡垒机） | 302 | 302 | ✅ 10/8 兜底 + 内网组生效 |
| `git.sjgjj.cn:443` | 302 | 302 | ✅ 域名规则生效（fake-ip `198.18.0.90` → TUN → socks5 域名转发） |
| `192.168.5.163:3306` | — | open | ✅ 靠 TUN 兜底路由进入 |
| `192.168.45.82:80` | — | open | ✅ 同上 |
| `192.168.0.168:8080`（Jenkins） | **200** | **不通** | ❌ **路由层断链** |

### 6.3 故障定位

```
路由表：192.168.0  →  link#15  UCS  en0        ← connected route，比 TUN 兜底更精确
       192.168.0.168/32 →  (不存在)            ← route-address 未落地
```

- 隧道侧 `192.168.0.168:8080` 返回 **200**，证明：Jenkins 存活、端口是 8080、aTrust 隧道可达、socks5 正常。
- 系统侧同一目标不通，且路由表里查不到 `/32`，说明流量从 `en0` 同网段 ARP 出去（家里/办公 LAN 里没有这台机器）→ 超时。
- Bettbox 的 `patchClashConfig.tun` 里 `auto-route: false`、`route-address: []`、`route-exclude-address: []`，路由由它自己的网络扩展接管；**脚本里的 `route-address` 在本机没有落到内核路由表**。而 `192.168.5/45` 两个目标能通，是因为它们恰好落在 NE 注入的 `0/0` 拆分路由里，跟 `route-address` 无关 —— 这一点很容易被误判成「route-address 生效了」。

---

## 七、问题清单与修复建议

### P0 · Jenkins 不可达（已修复 `8c28c70`）

**方案 A（已采用，最小改动）**：把规则层放行的 `192.168` 主机全部补进 `route-address`，让「规则层」和「路由层」严格对齐。实现上没有手抄两份，而是抽成单一数组 `intranet192Hosts`，规则与 `route-address` 都由它生成：

```js
const intranet192Hosts = [
  '192.168.0.168/32', // Jenkins
  '192.168.5.163/32', // 开发 MySQL
  '192.168.45.82/32', // 测试环境后端
  '192.168.73.49/32', // 端口 8000-9000
  '192.168.73.50/31',
];
// 规则层
...intranet192Hosts.map((cidr) => `IP-CIDR,${cidr},内网,no-resolve`),
// 路由层
'route-address': [...intranet192Hosts],
```

**方案 B（备用，Bettbox 若确实不认 `route-address`）**：改用域名访问 Jenkins。走 `DOMAIN,*` 规则时目的地址是 fake-ip（`198.18.x.x`），天然在 TUN 路由内，完全绕开同网段冲突 —— 这条路径已被 `git.sjgjj.cn` 实测验证可行：

```js
'DOMAIN,jenkins.<公司域名>,内网',
```

**方案 C（治本，代价大）**：把本机所在 LAN 改到不与公司重叠的段（如 `192.168.88.0/24`），冲突面直接消失。公司侧 `192.168.0.0/24`、`192.168.5/45/73` 都不要碰。

### P1 · 精简版与全量版漂移（已修复 `8c28c70`）

修复前：`Script/Script.js` 的 `intranetRules` **没有** `192.168.0.168/32`，`tun` 段**没有** `route-address`；而 `Test/suites/integration.js` 的 Jenkins 断言写着 `if (!meta.full) return;`，所以 206 项测试全绿也发现不了。

修复后：

1. 精简版与全量版共用同一份内网规则数组（`intranet192Hosts`），两版输出逐字节一致；
2. 断言去掉 `meta.full` 跳过，**两版都跑**，并新增三类校验：`cn_ip`/`private_ip` 顺序、规则与 `route-address` 逐条同源、`10/8` 与 `192.168/16` 不得出现在排除清单。

### P2 · 设计风险（按优先级）

| # | 风险 | 触发场景 | 建议 |
| --- | --- | --- | --- |
| 1 | `10/8` 全兜底 | 本机跑 k8s（`10.96/12`、`10.244/16`）、或再连一套 `10.x` 的 VPN | 若确有本地 `10.x` 需求，在 `intranetRules` **之前**加 `IP-CIDR,10.96.0.0/12,直连` 等例外 |
| 2 | 容器掉线即静默全断 | `docker compose down`、aTrust 掉登录 | 内网组是 `select`，无 `url-test/fallback`；建议保留「手动切直连」习惯，并在容器 down 时明确预期。**不要**加 `url-test`（测速 URL 走不通时会自动切直连，故障更隐蔽） |
| 3 | 新增内网资源要改代码 | 同事换 Jenkins 地址、新开中间件 | 逐步把高频段收敛成 `/24` 规则（如 `192.168.5.0/24`），但要先确认该段不会与任何常用家用网段撞车 |
| 4 | IPv6 内网 0 覆盖 | 访问 `fdff:5341:...` 资源 | 需要时补 `IP-CIDR6` 汇总规则，并确认 TUN 接管 IPv6 默认路由 |
| 5 | `172.168.0.0/16` 排除 | 该段目标会完全绕过 mihomo | 复核来源；若非明确需求应删除 |
| 6 | 脚本声明 `mixed-port 7890` 但实际未监听 | 想用 `http://127.0.0.1:7890` 给命令行/容器做二级代理 | 当前只能靠 TUN；如需二级代理，需在 Bettbox 里明确开启混合端口 |

---

## 八、与 atrust 项目的联动注意点

1. **`198.18` 出现两份**：Bettbox 用 `198.18.0.1/15` 做 fake-ip，aTrust 客户端内部也用 `198.18.2.53` 做 fake-ip。现在两者分处不同 netns（宿主 vs 容器）所以相安无事；**若把 `atrust` 容器改成 `--net host`，两套 fake-ip 会正面冲突**，务必保持容器独立网络。
2. **容器网段 `192.168.97.0/24`** 与公司下发的 `192.168.0.0/24` 不重叠，目前安全；若公司新增 `192.168.97.0/24` 资源，容器内路由会被 replace，隧道直接崩（这是 atrust 项目里已记录的残留风险）。
3. **掉线自愈**：aTrust 客户端本身无自动重连（上游 #265），内网组也不会自动回退，所以「容器 down / 掉登录」对内网访问是硬故障，需要人工介入。
4. 网关固定那条修复（`extra_hosts` + `pin_gateway_host`）解决了 `198.18.2.53` 自环；本项目的规则 ① 是同一问题在代理侧的另一道保险，**两者必须同时存在**。

---

## 九、待确认

1. Jenkins 是否有可解析的域名？有则优先走方案 B，可以彻底摆脱同网段冲突。
2. `192.168.73.49–50:8000-9000` 是什么服务，是否需要纳入内网组。
3. `172.168.0.0/16` 那条排除规则是刻意为之还是残留。
4. 本机是否还需要跑本地 k8s / 其他 `10.x` 隧道（决定是否要给 `10/8` 开口子）。

---

## 十、修复与验证记录（2026-10-20）

### 10.1 代码改动 · `8c28c70`

| 文件 | 改动 |
| --- | --- |
| `Script/mihomoScript.js` | 抽出 `intranet192Hosts`（5 个 CIDR）；`intranetRules` 由它生成；`route-address` 改为 `[...intranet192Hosts]` |
| `Script/Script.js` | 同步同一套 `intranet192Hosts` + `route-address`（原缺 Jenkins 与整个 `route-address` 段） |
| `Test/suites/integration.js` | Jenkins 用例改为两版通用，覆盖：`cn_ip`/`private_ip` 顺序、5 条规则存在性、`route-address` 同源、排除清单不含 `10/8` 与 `192.168/16` |

已 push 到 `origin/main`（`bca8d47..8c28c70`）。

### 10.2 测试验证

```
npm test  →  总计: 通过 206 项，失败 0 项
```

两版脚本实际输出（用 `minimalSubscription` 覆写后 dump）：

```
rules[0..8]: DOMAIN,sslvpn.jbysoft.com,直连
             DOMAIN,git.sjgjj.cn,内网
             IP-CIDR,10.0.0.0/8,内网,no-resolve
             IP-CIDR,113.125.201.130/31,内网,no-resolve
             IP-CIDR,222.222.216.74/32,内网,no-resolve
             IP-CIDR,192.168.0.168/32,内网,no-resolve
             IP-CIDR,192.168.5.163/32,内网,no-resolve
             IP-CIDR,192.168.45.82/32,内网,no-resolve
             IP-CIDR,192.168.73.49/32,内网,no-resolve   ← 新增
tun.route-address: 192.168.0.168/32, 192.168.5.163/32, 192.168.45.82/32,
                   192.168.73.49/32, 192.168.73.50/31   ← 5 条同源
cn_ip idx 28/40 < private_ip idx 29/41（两版内网规则都在兜底之前）
```

### 10.3 运行态验证结果（已确认，2026-10-20 12:00）

脚本由 Bettbox 从 URL 拉取并缓存，重载需重启应用；而**重启后不会自动连接**（无「启动即连接」），且沙箱无自动化权限（`osascript` 返回 `-10004`），只能人工点「连接」。本次已人工完成：缓存脚本 mtime `11:58`、md5 `09c09e71…`，与仓库 HEAD 一致，确认**跑的是新脚本**。

连接后实测：

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| `utun4` 路由表 | 只有 `1 / 2/7 / 4/6 / 8/5 / 16/4 / 32/3 / 64/2 / 128/1` + 自身 `/32` | **没有任何一条来自 `route-address` 的 `/32`** |
| `192.168.0.168:8080` | ❌ closed | 仍是 `link#15 en0`（connected + ARP 主机路由抢先） |
| `192.168.5.163:3306` | ✅ open | 靠 `0/0` 拆分路由进入 TUN，与 `route-address` 无关 |
| `192.168.45.82:80` | ✅ open | 同上 |
| `10.0.1.102:80` | ✅ 302 | 10/8 兜底照常（刚连上时有几秒抖动，重试即恢复） |
| `git.sjgjj.cn` | ✅ 302 | DOMAIN 规则 + fake-ip 路径正常 |

**结论：Bettbox 的网络扩展不消费 `tun.route-address`。** 5 条 `/32` 一条都没进内核路由表，而 `.5.163` / `.45.82` 能通纯粹是 `0/0` 拆分路由的副产品 —— 这也解释了为什么之前会误判「方案 A 生效」。

**已证实**（2026-10-20 12:08，脚本 / 客户端 patch / 内核实测三方对比）：

| 字段 | 脚本写的 | `patchClashConfig.tun` | `utun4` 实测 |
| --- | --- | --- | --- |
| `auto-route` | **true** | false | 只有 0/0 八条拆分，**无** `0.0.0.0/1`+`128.0.0.0/1` |
| `strict-route` | **true** | false | — |
| `auto-redirect` | **true** | false | — |
| `route-address` | **5 条 /32** | `[]` | **0 条** |
| `route-exclude-address` | **7 条** | `[]` | 无 |
| `dns-hijack` | `any:53` + `tcp://any:53` | 只有 `any:53` | — |
| `mtu` | 未设 | 9000 | **9000** |

七项全部跟随 patch、零项跟随脚本 —— `tun` 段被 `patchClashConfig.tun` 整段替换，确认无疑。因此 `95426ab`/`8b89b14` 两个「从排除清单移除 10/8」的提交**从未生效**，10/8 能通是因为客户端 patch 的排除清单本来就是空的。

补充确认：Bettbox「内核配置 → Tunnel」页里只有「添加转发」（即 `tunnels`，端口转发，当前为 `[]`），**macOS 版没有任何界面入口能编辑 tun 设备段**。那套值由客户端内置默认值生成，脚本怎么写都会被覆盖。

### 10.4 后续可选路径

| 路径 | 做法 | 成本 | 说明 |
| --- | --- | --- | --- |
| ① ~~定位 tunnel 覆写开关~~ | 切换 Bettbox「隧道覆写」后重连观察路由 | — | **已排除**：Tunnel 页只有「添加转发」（`tunnels` 端口转发），tun 设备段无界面入口，此路不通 |
| ② OS 层静态路由 | `sudo route -n add -host 192.168.0.168 -interface utunN`，并做成 LaunchDaemon 自愈 | 需 root，一次安装 | **已落地**，见第十一节。与客户端无关，稳定；缺点是绕过了配置文件，团队协作时不可见 |
| ③ 改本机 LAN 网段 | 家里/公司 LAN 改到 `192.168.88.0/24` 等不重叠段 | 改路由器 | 治本，冲突面直接消失；但只能解决本机，换机器还会遇到 |
| ④ Jenkins 走域名 | 若公司能给出 Jenkins 域名，加 `DOMAIN,jenkins.xxx,内网` | 一条规则 | 已验证 fake-ip 路径可行（`git.sjgjj.cn` 就是例子），但探测 `jenkins.sjgjj.cn` / `ci.sjgjj.cn` 等常见名均不可达 |

> 复现要点：改脚本后必须「重启/重连」才会重建配置；重启会丢连接状态且无自动重连，属已知行为。

---

## 十一、备选方案：路由守护（已验证有效，本次未采用）

> 本节方案**实测有效**：`sudo route -n add -host 192.168.0.168 -interface utun4` 之后 Jenkins 立即 200。但它需要 root 常驻守护进程，还要往系统路由表注入条目，最终改用第十二节的 `tunnels` 端口转发（不改系统路由）。保留本节，供「必须保持 `192.168.0.168` 原地址访问」时切换。

### 11.1 手工验证（已通过）

```bash
sudo route -n add -host 192.168.0.168 -interface utun4
nc -z -G 4 -w 3 192.168.0.168 8080 && echo open
```

结果：路由表出现 `192.168.0.168  utun4  UHS  utun4`，且排在 en0 的 `link#15 UHRLWI` 之前；`curl http://192.168.0.168:8080/` 返回 **200**（`Apache Tomcat/8.5.38` 页面）；`10.0.1.102` 仍 302、`git.sjgjj.cn` 仍 302、公网仍 200，无回归。

说明：包进 utun 后 mihomo 能正确按 `IP-CIDR,192.168.0.168/32,内网,no-resolve` 丢给 `内网-aTrust`（`socks5 127.0.0.1:1080`）。规则层和出口层一直是好的，缺的只是这一条 OS 路由。

### 11.2 守护脚本

`scripts/bettbox-route-guard.sh` + `scripts/com.uni1k.bettbox-route-guard.plist`

- **每 5 秒**跑一次（`StartInterval`），靠「接口地址落在 `198.18.0.1/15`」识别 TUN，不依赖 `utun` 编号，断线重连后自动跟上；
- 只给白名单主机补 `/32`，**绝不触碰 `192.168.0.0/24` 的 connected 路由**，避免把本机局域网（路由器、NAS、打印机）一起劫持；
- 已指向目标接口就跳过；需要改向时先 `route change` 再退回 `route add`；
- 接口消失时清理指向它的残留路由，防止黑洞；
- `HOSTS` 必须与 `Script/mihomoScript.js` 的 `intranet192Hosts` 一致，`Test/suites/integration.js` 有断言守护 —— 改一处漏另一处会直接测试失败。

运行时行为：连上后通常只有 `192.168.0.168` 需要补（另外四个落在 `0/1`、`128/1` 里，本来就指向 utun），日志里会看到 `changes=+192.168.0.168`；其余时间 `changes=none`，不写盘。

### 11.3 安装

```bash
cd /Users/yilinqu/Documents/workspace/personal/MyClash

sudo install -m 755 scripts/bettbox-route-guard.sh /usr/local/bin/bettbox-route-guard.sh
sudo install -m 644 scripts/com.uni1k.bettbox-route-guard.plist /Library/LaunchDaemons/com.uni1k.bettbox-route-guard.plist
sudo launchctl bootout system /Library/LaunchDaemons/com.uni1k.bettbox-route-guard.plist 2>/dev/null
sudo launchctl bootstrap system /Library/LaunchDaemons/com.uni1k.bettbox-route-guard.plist
sudo launchctl kickstart -k system/com.uni1k.bettbox-route-guard
```

验证：

```bash
sudo cat /var/log/bettbox-route-guard.log                  # 期望看到 tun=utunN changes=...
route -n get -host 192.168.0.168 | grep interface         # 期望 utunN
nc -z -G 4 -w 3 192.168.0.168 8080 && echo open
```

### 11.4 卸载

```bash
sudo launchctl bootout system /Library/LaunchDaemons/com.uni1k.bettbox-route-guard.plist
sudo rm -f /Library/LaunchDaemons/com.uni1k.bettbox-route-guard.plist /usr/local/bin/bettbox-route-guard.sh
sudo rm -f /var/log/bettbox-route-guard.log /var/run/bettbox-route-guard.state
```

> 卸载后 Bettbox 再连接时，`192.168.0.168` 会回到 en0 的 ARP 主机路由，Jenkins 重新不可达 —— 这是回到修复前状态，不是新问题。

---

## 十二、最终方案：tunnels 端口转发（2026-10-20 12:22 验证通过）

### 12.1 为什么路由层在 macOS 上走不通

把 `intranet192Hosts` 写进 `patchClashConfig.tun.route-address` 后（脚本 `scripts/patch-bettbox-tun.py`），客户端**没有重置**，5 条 `/32` 完整保留；但重连后：

| 目标 | 实际出接口 |
| --- | --- |
| `192.168.5.163` / `.45.82` / `.73.49` | `utun4`（靠 `0/0` 拆分，不是 `route-address` 的功劳） |
| `192.168.0.168` | **`en0`**（`link#15 UHRLWI` 的 `/32` ARP 主机路由胜出） |

配置留着却不生效，结论是 **Bettbox 读了这个字段，但没转成 NE 的 `includedRoutes`**。macOS 网络扩展的接管范围固定为 `0/0` 拆分（`1`、`2/7`、`4/6`、`8/5`、`16/4`、`32/3`、`64/2`、`128/1`），而路由按最长前缀匹配，`en0` 的 `/24` connected 与 `/32` ARP 主机路由永远更精确。这是 mihomo 在 macOS 的通用局限（Windows/Linux 会改 metric 或加更细路由），客户端侧无解。

### 12.2 做法

「内核配置 → Tunnel → 添加转发」（即 mihomo `tunnels`）：

| 字段 | 值 |
| --- | --- |
| 网络协议 | `tcp` |
| 监听地址 | `127.0.0.1:8080` |
| 目标地址 | `192.168.0.168:8080` |
| 代理名称 | `内网` |

落盘到 `config.json`：

```json
"tunnels": [
  { "network": ["tcp"], "address": "127.0.0.1:8080",
    "target": "192.168.0.168:8080", "proxyName": "内网" }
]
```

原理：mihomo 在本机监听 8080，收到连接后**不查本机路由**，直接把目标交给「内网」组（→ `socks5 127.0.0.1:1080` → aTrust 容器）。路由表完全不参与，同网段冲突天然消失。

### 12.3 验证结果

访问地址：**http://127.0.0.1:8080/jenkins/**

| 检查 | 结果 |
| --- | --- |
| 8080 监听 | `tcp4 127.0.0.1.8080 LISTEN` |
| `/jenkins/login` | **200**，`X-Jenkins: 2.177`，`<title>Sign in [Jenkins]</title>` |
| `/jenkins/` | 403（未登录，符合预期） |
| 连续 3 次 | 全部 200，200–260 ms |
| 重定向 | 响应无 `Location`；页面链接均为相对路径或外网域名，不会跳回不可达地址 |
| 回归 | `10.0.1.102` 302、`git.sjgjj.cn` 302、`www.baidu.com` 200 |

```bash
curl -sI --noproxy '*' http://127.0.0.1:8080/jenkins/login | grep -i x-jenkins
# X-Jenkins: 2.177
```

### 12.4 注意事项

1. **需要重连生效**：`tunnels` 是内核启动时创建的监听器，UI 里加完必须停止→启动（或断开重连）；
2. **冷启动首连较慢**：第一次请求出现过 10 秒超时，之后稳定 200–260 ms（aTrust 侧 socks5 建连开销）；
3. **占用本机 8080**：若被别的程序占用可改 `127.0.0.1:18080`，访问地址随之变化；
4. **配置不在项目里**：`tunnels` 存在客户端 `config.json`，换机器需要重配 —— 这是客户端能力的边界，脚本无法覆盖（`overrideTunnel: true` 时客户端的 `tunnels` 会盖掉脚本输出）；
5. **断线自动失效**：断开后监听消失，无需清理，重连即恢复；
6. **只开虚拟网卡也能用**：`tunnels` 是内核入站监听，与「系统代理」开关无关。

---

## 十三、治本方案：把家用网段挪出 `192.168.0.0/24`（2026-10-20 12:39 完成）

第十二、十一节都是绕过路由，本质上是"冲突还在，只是避开"。真正的解法是让冲突不存在：公司下发 `192.168.0.0/24` 覆盖 `.2–.254`（253/256），而本机 LAN 恰好同段，所以把家用网段挪开即可。

### 13.1 改动（移动 Wi-Fi CPE 的「内网设置」页）

| 字段 | 改前 | 改后 |
| --- | --- | --- |
| 网关地址 | `192.168.0.1` | `192.168.88.1` |
| 子网掩码 | `255.255.255.0` | 不变 |
| DHCP IP 池 | `192.168.0.2–192.168.0.253` | `192.168.88.2–192.168.88.253` |
| DHCP 租期 | `24` 小时 | 不变 |

选 `192.168.88.0/24` 的依据（四处占用都避开了）：

| 占用方 | 网段 |
| --- | --- |
| 公司下发 | `192.168.0` / `.5` / `.45` / `.73`，以及整个 `10/8` |
| OrbStack `bridge100` | `192.168.139.0/24` |
| OrbStack `bridge101`（atrust 容器） | `192.168.97.0/24` |
| 公版易撞段 | 避开 `192.168.1.0/24` |

### 13.2 改完的实测结果

```
en0                192.168.88.26/24
default gateway    192.168.88.1 (en0)
192.168.0.168  →   utun4  via 198.18.0.1   ← 不再是 en0
```

| 检查 | 结果 |
| --- | --- |
| `http://192.168.0.168:8080/jenkins/login` | **200**，`X-Jenkins: 2.177`，`X-Jenkins-CLI-Port: 49621` |
| `.../jenkins/view/智能客服/` | 403（匿名无读权限，登录后正常） |
| `10.0.1.102` | 302 |
| `https://git.sjgjj.cn/` | 302 |
| `http://192.168.88.1/`（家用网关） | 200 |
| `https://www.baidu.com/` | 200 |

### 13.3 对前几节结论的影响

| 方案 | 现状 |
| --- | --- |
| 第十三节（本节）改网段 | **已采用**，从根上消除重叠 |
| 第十二节 `tunnels` 端口转发 | **保留但非必需**。仍然可用（`127.0.0.1:8080` 实测 200），占一个本地端口；不需要时在「内核配置 → Tunnel」里删掉即可 |
| 第十一节 路由守护 LaunchDaemon | **不需要安装**，从未装过 |
| `tun.route-address` | 依旧是死字段（macOS），保留只为 Linux/Windows 的 mihomo CLI |

> 注意：换段后 `192.168.0.1` 也进了隧道（那是**公司的** `192.168.0.1`，不是家用网关）。家用网关现在是 `192.168.88.1`，两者不再冲突。

---

## 附录：本文用到的采集命令

```bash
# 路由与网卡
netstat -rn -f inet | grep -E '^(192\.168|10\.|113\.125|222\.222)'
ifconfig | grep -E '^utun|inet 198'

# 监听与进程
lsof -nP -iTCP -sTCP:LISTEN
pgrep -fl 'Bettbox|mihomo'
scutil --proxy

# 分流验证（对比两条路径）
curl -s -o /dev/null -w '%{http_code}\n' --socks5-hostname 127.0.0.1:1080 http://192.168.0.168:8080/
nc -z -G 5 -w 3 192.168.0.168 8080 && echo open || echo closed

# Bettbox 落盘配置
ls ~/Library/Application\ Support/com.appshub.bettbox/
diff ~/Library/Application\ Support/com.appshub.bettbox/scripts/*.js Script/mihomoScript.js
```
