# `Script/mihomoScript.js` 配置审查

> 审查基线：2026-08-29 全量逐行审查 → 2026-08-31 按 Mihomo `v1.19.30` + Bettbox `714130a` 复核
> 当前状态：`bfb43fc`，测试 208/0

本文只保留**仍然有效**的结论。2026-08-29 那份按「修复前行号」编写的逐行审查已删除——行号与代码早已过期，留着重读反而误导。

---

## 1. 兼容性基线

| 项 | 取值 | 依据 |
| --- | --- | --- |
| Bettbox 脚本标记 | `Compatible_With_Bettbox` 置于**首行** | Bettbox 只在前 2000 字符内识别该标记 |
| TUN `stack` | `mixed`（官方优先推荐，也是 Bettbox 默认） | Mihomo TUN 文档 |
| IPv6 | 启用时额外排除 ULA `fc00::/7` | 同上 |
| Keep Alive | `keep-alive-interval: 60` + `keep-alive-idle: 60` | Mihomo 通用配置 |
| 规则集格式 | `http + mrs + domain/ipcidr + 86400s` | MRS 只支持 `domain` / `ipcidr` |

---

## 2. 已修复问题

| 原问题 | 处理 |
| --- | --- |
| 节点与内置出站 / 策略组重名 → 内核报 `duplicate name` | 预留全部生成名称；订阅节点加 `订阅-`、自定义节点加 `自建-`，并同步修引用 |
| hosts 域名重定向写成数组 | 改为字符串（官方规定：数组只适用于 IP 列表） |
| 私有 DNS 只做整体兜底 | 改为逐域名判断 policy 覆盖情况，仅为未覆盖域名补兜底 |
| 公共 DNS 用无边界子串匹配（`11.1.1.10` 命中 `1.1.1.1`） | 解析 endpoint 主机后按完整 IP / 明确后缀 / 完整服务商标签匹配 |
| 空标量 DNS policy 阻止兜底 | 空字符串、空数组、非字符串不再视为有效 policy |
| `dialer-proxy` 无法引用后加入的自定义节点 | 延后最终校验并合并重命名映射 |
| 默认开放 LAN 且无认证 | 新增「允许局域网访问」开关，默认关闭并绑 `127.0.0.1` |
| `0.51x`～`0.59x` 被误判低倍率 | 收紧 `<= 0.5` 的小数边界 |
| IP 判断过宽 | 补 IPv4 段范围 / 前导零、IPv6 结构与 zone suffix 校验 |
| 地区冲突（`🇯🇵 香港` 同时命中日本与香港） | 未消解，属已知设计边界 |
| 注释与实现不符（「内部去重」实为「重名改名」） | 注释已改 |

---

## 3. 保留的设计取舍

- **可变版本引用**（`main` / `meta` / `release`）：换取规则自动更新，接受供应链风险，不固定版本。
- **离线 Bundle 降级**：`fakeip_filter` → `private.mrs`、`cn_additional` → `cn.mrs`，语义不完全等同在线规则，属降级路径而非等价替代。
- **`:8000-9000` 类端口段规则**：由内网侧收敛，见 `docs/intranet-routing-analysis.md`。

---

## 4. 待确认

- **`172.168.0.0/16` 是否该排除**：2026-08-29 曾按「用户明确要求该公网段绕过代理」保留；`bfb43fc` 以「非 RFC1918、疑似 `172.16/12` 笔误」移除并加了禁止回归的测试。**两处记录冲突，当前按移除执行**，结论待定。

---

## 5. 官方依据

1. Mihomo 通用配置：<https://wiki.metacubex.one/en/config/general/>
2. 策略组：<https://wiki.metacubex.one/en/config/proxy-groups/>
3. DNS：<https://wiki.metacubex.one/en/config/dns/>
4. hosts（域名重定向不支持数组）：<https://wiki.metacubex.one/en/config/dns/hosts/>
5. TUN：<https://wiki.metacubex.one/en/config/inbound/tun/>
6. 规则：<https://wiki.metacubex.one/en/config/rules/>
7. Rule Providers：<https://wiki.metacubex.one/en/config/rule-providers/>
8. 域名通配符：<https://wiki.metacubex.one/en/handbook/syntax/#domain-wildcards>
9. Bettbox 脚本兼容标记：<https://github.com/appshubcc/Bettbox/blob/714130a3d746d093f6278c0503dac9e2e43fd3e3/lib/models/common.dart>
10. Bettbox TUN 默认值：<https://github.com/appshubcc/Bettbox/blob/714130a3d746d093f6278c0503dac9e2e43fd3e3/lib/models/clash_config.dart>
11. RFC 1918：<https://www.rfc-editor.org/rfc/rfc1918#section-3>

---

## 6. 验证方式

```bash
npm --prefix Test test                      # Node + ES2020 + QuickJS 全量
node --check Script/mihomoScript.js
git diff --check
```

- 生成的代表性配置用官方 `mihomo -t`（`v1.19.30`）校验通过。
- 历史上逐个请求过脚本内 41 个远程 URL：规则集、探测 URL、UI 均返回 200/204。
- 限制：没有做真实 TUN 路由、DNS 查询、QUIC 回退、流媒体解锁或 Bettbox 宿主行为的端到端测试，这些仍依赖平台、网络与订阅内容。
