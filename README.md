# MyClash

基于 [Mihomo](https://github.com/MetaCubeX/mihomo/tree/Alpha) 的**覆写脚本与配置文件**，仅适用于 mihomo 内核的代理客户端。

## 注意事项

- 使用本项目的脚本或配置时，**请关闭代理软件自带的 DNS 覆写**，否则 DNS 分流不生效。
- 脚本只用于覆写机场提供的配置文件，不要用它覆写自己手写的配置。
- Windows 上如需杜绝 DNS 泄露，关闭系统「智能多宿主名称解析」，或在客户端开启[严格路由](https://wiki.metacubex.one/config/inbound/tun/#strict-route)。
- 内网分流（aTrust / Jenkins 等）的额外配置单独维护，见 [`docs/intranet-routing-analysis.md`](/docs/intranet-routing-analysis.md)。

## 特色功能

- 🧩 **分流策略组**：内置 AI、YouTube、Google、Telegram、Steam、Netflix、Spotify 等常用分组，可按需开关
- 🎨 **SVG 图标**：策略组图标为手绘矢量，任意尺寸清晰；制作规范见 [`AGENT.md`](/AGENT.md)
- 🌏 **地区自动分组**：识别香港、日本、美国、新加坡、台湾等地区并生成对应策略组
- 🧹 **节点整理**：自动补国旗、规范名称、过滤无效节点、按倍率归类
- ✨ **精准分流**：以 `cn-ip,直连` 兜底 + `cn-domain` 国内 DNS 分流，减少「国内误走代理、国外误判直连」
- 🪶 **轻量规则**：`rule-set` 按需加载，降低配置体积与内存占用
- 🛡️ **DNS 分流**：加密 DNS 引导、节点解析、国内公共解析；国外解析经代理查询
- 🔧 **私有 DNS 自动处理**：自动识别机场私有 DNS 与节点域名 hosts 映射
- 🪜 **高级功能**：自定义节点、IPv4/IPv6 优先、屏蔽国外 QUIC
- 📱 **Bettbox 图形化适配**：可在界面直接开关策略组与功能项，无需改代码

## 版本选择

全量版与精简版功能基本一致，仅分流策略组数量不同：

- **全量版**：完整分流组，适合精细分流
- **精简版**：仅保留常用组，配置更简洁

## 使用方法

导入链接或完整代码即可，两个脚本分别对应两个版本：

| 版本 | 文件 | 覆写链接 |
| --- | --- | --- |
| 全量版 | [`Script/mihomoScript.js`](/Script/mihomoScript.js) | `https://raw.githubusercontent.com/uni1k/MyClash/refs/heads/main/Script/mihomoScript.js` |
| 精简版 | [`Script/Script.js`](/Script/Script.js) | `https://raw.githubusercontent.com/uni1k/MyClash/refs/heads/main/Script/Script.js` |

![导入步骤](https://raw.githubusercontent.com/uni1k/MyClash/main/Image/import.webp)

配置文件（YAML）与脚本效果基本一致，但静态配置无法动态生成地区组，未匹配到节点的地区会回退到 `REJECT`，使用私有 DNS 或 hosts 映射的机场需手动补写：

| 版本 | 文件 |
| --- | --- |
| 全量版 | [`Config/mihomoConfig.yaml`](/Config/mihomoConfig.yaml) |
| 精简版 | [`Config/mihomoConfigLite.yaml`](/Config/mihomoConfigLite.yaml) |

## 默认配置

- 引导解析用阿里 IP DoH；节点域名解析用阿里 DoQ + 腾讯 DoH。
- 国内常规与直连解析用陕西移动 DNS（`218.200.6.139`，明文 UDP）与阿里 DoQ（`quic://dns.alidns.com:853`），均经 `DIRECT`；国外解析经代理走 Cloudflare 与 Google。
- 国内 DNS 上游**不是严格主备**，陕西移动 DNS 的可用性取决于当前接入网络。
- 私有域名继续用系统 DNS，抖音保留原解析例外；这些例外不保证走加密 DNS。
- 默认不返回 AAAA（`dns.ipv6: false`），需要 IPv6 域名解析时自行修改；这不等于禁用所有 IPv6 流量。
- 两版默认关闭倍率组，全量版默认关闭负载均衡；关闭倍率组不删除倍率节点，节点仍按地区归类。
- 自动选择组：600 秒测速、2000ms 超时、2 次失败阈值、保留懒惰测速；容忍度精简版 50ms、全量版 100ms。
- 默认代理与 AI 的具体节点由客户端保存，脚本不绑定地区。

## 效果预览

推荐用 [Bettbox](https://github.com/appshubcc/Bettbox) 管理覆写脚本，可在界面调整策略组与配置项。

| | | | |
| --- | --- | --- | --- |
| ![1](https://raw.githubusercontent.com/uni1k/MyClash/main/Image/IMG_1.webp) | ![2](https://raw.githubusercontent.com/uni1k/MyClash/main/Image/IMG_2.webp) | ![3](https://raw.githubusercontent.com/uni1k/MyClash/main/Image/IMG_3.webp) | ![4](https://raw.githubusercontent.com/uni1k/MyClash/main/Image/IMG_4.webp) |
| ![5](https://raw.githubusercontent.com/uni1k/MyClash/main/Image/IMG_5.webp) | ![6](https://raw.githubusercontent.com/uni1k/MyClash/main/Image/IMG_6.webp) | ![7](https://raw.githubusercontent.com/uni1k/MyClash/main/Image/IMG_7.webp) | ![8](https://raw.githubusercontent.com/uni1k/MyClash/main/Image/IMG_8.webp) |

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [`AGENT.md`](/AGENT.md) | `Icons/svg/` 图标制作规范（几何、渐变、Flutter 兼容红线、校验流程） |
| [`docs/mihomoScript-analysis.md`](/docs/mihomoScript-analysis.md) | 脚本配置审查：兼容性基线、已修问题、保留的取舍、官方依据 |
| [`docs/intranet-routing-analysis.md`](/docs/intranet-routing-analysis.md) | 内网分流（Bettbox + docker-atrust）：三层模型、路由限制、客户端开关、覆盖率 |
| [`Test/README.md`](/Test/README.md) | 测试运行方式与覆盖范围 |

## 测试

```bash
npm --prefix Test install   # 可选：ES2020 / QuickJS 兼容性检查依赖
npm --prefix Test test
```

## 致谢

- [dahaha-365/YaNet](https://github.com/dahaha-365/YaNet)
- [YiXuanZX/rules](https://github.com/YiXuanZX/rules)
- [appshubcc/bett-rules](https://github.com/appshubcc/bett-rules)
- [Koolson/Qure](https://github.com/Koolson/Qure)
- [jsdmirror/JSDMirror](https://github.com/jsdmirror/JSDMirror)
