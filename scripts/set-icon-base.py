#!/usr/bin/env python3
"""统一切换覆写脚本与配置文件里的图标 base URL。

图标是 mihomo / Bettbox 匿名 GET 的，所以目标地址必须「谁都能读」：
私有仓库的 raw 需要 Authorization 头，客户端拿不到，直接用不了。
可用的目标只有公共仓（GitHub 任意 CDN，或 CNB 的 public 仓库）。

用法：
  # 预览影响范围，不写入
  python3 scripts/set-icon-base.py https://cdn.jsdelivr.net/gh/uni1k/MyClash@icons-v1/Icons/svg/ --dry-run

  # 实际写入（会先探测新地址是否可达）
  python3 scripts/set-icon-base.py https://cdn.jsdelivr.net/gh/uni1k/MyClash@icons-v1/Icons/svg/

  # 跳过可达性探测
  python3 scripts/set-icon-base.py <base> --no-probe

改完记得跑一遍测试与格式化：
  npm --prefix Test test
  npx prettier --check 'Script/*.js' 'Config/*.yaml'
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

TARGETS = [
    "Script/mihomoScript.js",
    "Script/Script.js",
    "Config/mihomoConfig.yaml",
    "Config/mihomoConfigLite.yaml",
]

# 只匹配「以 svg/ 或 png/ 目录结尾」的地址前缀，避免误伤规则集等其他 CDN 地址。
# 同时兼容 .../Icons/svg/ 与扁平化的 .../svg/ 两种布局。
ICON_BASE_RE = re.compile(r"""https?://[^\s'"()\[\]]+?/(?:[Ii]cons/)?(?:svg|png)/""")
BASE_SUFFIX_RE = re.compile(r"""(?:svg|png)/$""")

PROBE_FILE = "Auto.svg"


def probe(base: str, timeout: float = 10.0) -> tuple[bool, str]:
    """探测 base + Auto.svg 是否匿名可读。刻意绕过环境里的 http(s)_proxy。"""
    url = base + PROBE_FILE
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "MyClash-icon-check"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read(200)
            ctype = resp.headers.get("Content-Type", "")
            ok = resp.status == 200 and b"<svg" in body.lower()
            return ok, f"{resp.status} {ctype}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - 网络错误一律当作不可用
        return False, type(exc).__name__ + f": {exc}"


def rewrite(path: Path, new_base: str, dry_run: bool) -> tuple[int, list[str]]:
    text = path.read_text(encoding="utf-8")
    olds = ICON_BASE_RE.findall(text)
    if not olds:
        return 0, []
    new_text = ICON_BASE_RE.sub(new_base, text)
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return len(olds), sorted(set(olds))


def main() -> int:
    ap = argparse.ArgumentParser(description="切换图标 base URL")
    ap.add_argument("base", help="新的图标目录地址，需以 svg/ 或 png/ 结尾（如 .../Icons/svg/），建议带尾斜杠")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写入（同时跳过探测）")
    ap.add_argument("--no-probe", action="store_true", help="跳过可达性探测")
    args = ap.parse_args()

    base = args.base.strip()
    if not base.startswith(("http://", "https://")):
        print(f"✗ base 必须以 http(s):// 开头: {base}", file=sys.stderr)
        return 2
    if not BASE_SUFFIX_RE.search(base.rstrip("/") + "/"):
        print(f"✗ base 必须以 svg/ 或 png/ 结尾（如 .../Icons/svg/）: {base}", file=sys.stderr)
        return 2
    if not base.endswith("/"):
        base += "/"

    root = Path(__file__).resolve().parent.parent
    missing = [t for t in TARGETS if not (root / t).is_file()]
    if missing:
        print(f"✗ 找不到目标文件（请在仓库根目录运行）: {missing}", file=sys.stderr)
        return 2

    if not args.dry_run and not args.no_probe:
        ok, detail = probe(base)
        if not ok:
            print(f"✗ 探测失败 {base}{PROBE_FILE} → {detail}", file=sys.stderr)
            print("  图标地址必须匿名可读；私有仓库需要 Authorization 头，客户端无法提供。", file=sys.stderr)
            print("  确认要写就加 --no-probe。", file=sys.stderr)
            return 1
        print(f"✓ 探测通过 {base}{PROBE_FILE} → {detail}")

    total = 0
    for rel in TARGETS:
        count, olds = rewrite(root / rel, base, args.dry_run)
        total += count
        if count == 0:
            print(f"  {rel}: 无图标地址")
            continue
        print(f"  {rel}: {count} 处")
        for old in olds:
            print(f"      {old}")
    if total == 0:
        print("✗ 一个也没匹配到，检查 base 是否需要带 Icons/svg/ 结尾", file=sys.stderr)
        return 1

    verb = "将改写" if args.dry_run else "已改写"
    print(f"\n{verb} {total} 处 → {base}")
    if args.dry_run:
        print("（dry-run，未写入文件）")
    else:
        print("下一步：npm --prefix Test test && npx prettier --check 'Script/*.js' 'Config/*.yaml'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
