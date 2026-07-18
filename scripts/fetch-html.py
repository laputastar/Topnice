#!/usr/bin/env python3
"""
fetch-html.py — 用 Firecrawl / Context.dev / TinyFish Fetch 抓取 KS/IG 项目页 HTML
三 provider 降级: Firecrawl 优先 → Context.dev 次选 → TinyFish 兜底（免费）。
Firecrawl 和 Context.dev 额度耗尽后自动走 TinyFish（0 credit/url）。

功能:
  1. Raw layer:  原始 HTML → gzip → scripts/raw/html/{slug}.html.gz
  2. 仅存盘，字段解析交给 ai-extract.py（规则 #12: AI 读，禁用规则解析器）

用法:
  python scripts/fetch-html.py                                 # 全量跑
  python scripts/fetch-html.py --limit 3                        # 测试前 N 个
  python scripts/fetch-html.py --project omni-x1               # 指定项目slug
"""
import json, os, sys, time, gzip, hashlib
from pathlib import Path
from datetime import datetime, timezone

from safeio import atomic_write_json

DATA_FILE = Path(__file__).parent.parent / "src" / "data" / "projects.json"
RAW_HTML_DIR = Path(__file__).parent / "raw" / "html"
SLEEP_SEC = 2

# 安全：API Key 从环境变量读取，禁止硬编码（避免泄露进 git/分享）
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
CONTEXT_DEV_API_KEY = os.environ.get("CONTEXT_DEV_API_KEY", "")
TINYFISH_API_KEY = os.environ.get("TINYFISH_API_KEY", "")

# Firecrawl 额度耗尽异常：不同 SDK 版本位置可能不同，做兜底导入
try:
    from firecrawl.v2.utils.error_handler import PaymentRequiredError
except Exception:
    class PaymentRequiredError(Exception):
        """兜底：导入失败时不会实际抛出，仅用于类型匹配"""
        pass

# Provider 可用性全局标志（首次失败后置位，避免每个项目反复重试浪费时间）
firecrawl_dead = not bool(FIRECRAWL_API_KEY)
contextdev_dead = not bool(CONTEXT_DEV_API_KEY)
tinyfish_dead = not bool(TINYFISH_API_KEY)


def _save_raw_html(slug: str, html_text: str) -> dict:
    """将原始 HTML 压缩存储到 raw/html/{slug}.html.gz，返回 metadata"""
    ts = datetime.now(timezone.utc).isoformat()
    content_hash = hashlib.sha256(html_text.encode()).hexdigest()[:16]

    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    gz_path = RAW_HTML_DIR / f"{slug}.html.gz"

    # 原子写：先写 .tmp.gz 再 os.replace，崩溃只留临时文件、原快照完好
    tmp = RAW_HTML_DIR / f"{slug}.html.tmp.gz"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        f.write(html_text)
    os.replace(tmp, gz_path)

    return {
        "raw_html_hash": content_hash,
        "raw_html_path": str(gz_path.relative_to(Path(__file__).parent.parent)),
        "fetched_at": ts,
    }


def extract_html_firecrawl(url: str) -> dict:
    """Firecrawl 抓取（官方 SDK）"""
    from firecrawl import Firecrawl
    app = Firecrawl(api_key=FIRECRAWL_API_KEY)
    result = app.scrape(url, formats=["html"], only_main_content=False, proxy="auto", timeout=45000)
    credits = result.metadata.credits_used if result.metadata else 1
    return {
        "html_length": len(result.html),
        "credits": credits,
        "raw_html": result.html,
        "credits_remaining": None,  # Firecrawl SDK 不返回剩余额度，靠 PaymentRequiredError 探测
    }


def extract_html_contextdev(url: str) -> dict:
    """Context.dev 抓取（官方 Python SDK，懒导入；带 waitForMs 等 JS 懒加载内容）"""
    from context.dev import ContextDev
    client = ContextDev()  # 自动读取 CONTEXT_DEV_API_KEY
    resp = client.web.web_scrape_html(
        url=url,
        wait_for_ms=5000,    # 等 JS 懒加载（KS founder bio / IG 档位）
        timeout_ms=60000,
        max_age_ms=0,        # 强制新鲜抓（我们本地已有"有快照即跳过"的幂等层）
        # country="us",      # 可选：美国住宅代理出口
    )
    # 兼容 SDK 对象属性与 dict 两种返回形态
    if isinstance(resp, dict):
        html = resp.get("html", "")
        km = resp.get("key_metadata", {}) or {}
        remaining = km.get("credits_remaining")
        consumed = km.get("credits_consumed", 1)
    else:
        html = getattr(resp, "html", "")
        km = getattr(resp, "key_metadata", None)
        remaining = getattr(km, "credits_remaining", None) if km else None
        consumed = getattr(km, "credits_consumed", 1) if km else 1
    return {
        "html_length": len(html or ""),
        "credits": consumed,
        "raw_html": html,
        "credits_remaining": remaining,
    }


def extract_html_tinyfish(url: str) -> dict:
    """TinyFish Fetch API 抓取（免费，0 credit/url）"""
    import requests
    r = requests.post(
        "https://api.fetch.tinyfish.ai",
        headers={
            "X-API-Key": TINYFISH_API_KEY,
            "Content-Type": "application/json",
        },
        json={"urls": [url], "format": "html"},
        timeout=90,
    )
    data = r.json()
    errors = data.get("errors", [])
    if errors:
        raise Exception(f"TinyFish error: {errors[0].get('message', str(errors[0]))}")
    results = data.get("results", [])
    if not results:
        raise Exception("TinyFish: no results returned")
    item = results[0]
    html = item.get("text") or item.get("content") or ""
    return {
        "html_length": len(html),
        "credits": 0,
        "raw_html": html,
        "credits_remaining": 999999,  # 免费，永不耗尽
    }


def fetch_one(url: str):
    """按降级顺序尝试 provider。返回 (result_dict, provider_name) 或 (None, None)。"""
    global firecrawl_dead, contextdev_dead

    # 1. Firecrawl 优先
    if not firecrawl_dead:
        try:
            return extract_html_firecrawl(url), "firecrawl"
        except PaymentRequiredError:
            firecrawl_dead = True
            print("  ⚠️  Firecrawl 额度耗尽，后续降级 Context.dev")
        except Exception as e:
            firecrawl_dead = True
            print(f"  ⚠️  Firecrawl 异常({type(e).__name__})，降级 Context.dev: {e}")

    # 2. Context.dev 降级
    if not contextdev_dead:
        try:
            r = extract_html_contextdev(url)
            if r.get("credits_remaining") is not None and r["credits_remaining"] <= 0:
                contextdev_dead = True
                print("  ⚠️  Context.dev 额度耗尽")
                return None, None
            return r, "contextdev"
        except Exception as e:
            contextdev_dead = True
            print(f"  ⚠️  Context.dev 异常({type(e).__name__}): {e}")

    # 3. TinyFish Fetch 兜底（免费，0 credit/url）
    if not tinyfish_dead:
        try:
            return extract_html_tinyfish(url), "tinyfish"
        except Exception as e:
            tinyfish_dead = True
            print(f"  ⚠️  TinyFish 异常({type(e).__name__}): {e}")

    return None, None


def needs_refetch(p: dict, raw_html_dir: Path) -> bool:
    """判断是否需要抓取
    - 项目必须 live（已结束的不抓）
    - 不能已有 raw HTML 快照（从未抓过）
    - 必须有 URL
    - KS/IG 都支持
    """
    if p.get("state") not in ("live", "active"):
        return False
    slug = p.get("slug") or p.get("id")
    if (raw_html_dir / f"{slug}.html.gz").exists():
        return False
    if not p.get("url"):
        return False
    return True


def _save_data(data):
    atomic_write_json(DATA_FILE, data)  # 原子写：崩溃不损坏，写前备份 .bak


def main():
    if not FIRECRAWL_API_KEY and not CONTEXT_DEV_API_KEY and not TINYFISH_API_KEY:
        print("ERROR: 需至少设置 FIRECRAWL_API_KEY、CONTEXT_DEV_API_KEY 或 TINYFISH_API_KEY 之一。")
        sys.exit(1)

    limit = None
    target_project = None
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--limit" and i + 2 < len(sys.argv):
            limit = int(sys.argv[i + 2])
        elif arg == "--project" and i + 2 < len(sys.argv):
            target_project = sys.argv[i + 2]

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    projects = data.get("projects", [])

    # 指定项目模式
    if target_project:
        for p in projects:
            if target_project in p.get("slug", "") or target_project in p.get("id", ""):
                url = p.get("url", "")
                if not url:
                    print(f"❌ {p.get('name','?')} 无 URL")
                    return
                print(f"▶️  {p.get('name','?')}")
                print(f"   URL: {url}")
                result, provider = fetch_one(url)
                if result is None:
                    print("❌ 两 provider 均失败")
                    return
                raw_meta = _save_raw_html(p.get("slug", p.get("id", target_project)), result["raw_html"])
                p["raw_html_hash"] = raw_meta["raw_html_hash"]
                p["raw_fetched_at"] = raw_meta["fetched_at"]
                _save_data(data)
                print(f"  ✅ [{provider}] 原始 HTML 已存盘: {result['html_length']} chars")
                print(f"  💰 消耗: {result['credits']} credit")
                return
        print(f"❌ 未找到项目: {target_project}")
        return

    # 批量模式
    to_fetch = [p for p in projects if needs_refetch(p, RAW_HTML_DIR)]
    total = len(to_fetch)
    if limit:
        to_fetch = to_fetch[:limit]
    if not to_fetch:
        print("✅ 所有项目已有 html_story，无需抓取")
        return

    print(f"📊 需要抓取: {len(to_fetch)}/{total} 个项目")
    print(f"💰 预计最多花费: ~{len(to_fetch)} credits（Firecrawl 优先，失败降级 Context.dev）\n")

    total_credits = 0
    success = 0
    both_dead = False

    for i, p in enumerate(to_fetch):
        name = p.get("name", "?")[:50]
        url = p.get("url", "")
        print(f"[{i+1}/{len(to_fetch)}] {name}")
        if not url:
            print("  ⚠️  无 URL，跳过")
            continue
        result, provider = fetch_one(url)
        if result is None:
            if firecrawl_dead and contextdev_dead:
                print("\n💀 Firecrawl 与 Context.dev 均不可用，提前结束。")
                both_dead = True
                break
            print("  ❌ 两 provider 均失败，跳过，继续下一个")
            continue
        raw_meta = _save_raw_html(p.get("slug", p.get("id", str(i))), result["raw_html"])
        p["raw_html_hash"] = raw_meta["raw_html_hash"]
        p["raw_fetched_at"] = raw_meta["fetched_at"]
        total_credits += result["credits"]
        success += 1
        print(f"  ✅ [{provider}] 原始HTML:{result['html_length']}chars  💰 {result['credits']}cr")
        if (i + 1) % 20 == 0:
            _save_data(data)
            print(f"  💾 保存 ({i+1}/{len(to_fetch)})")
        time.sleep(SLEEP_SEC)

    _save_data(data)
    if both_dead:
        print(f"\n⏸️  两 provider 额度皆尽/均失败，提前结束: 成功 {success}/{len(to_fetch)}  💰 {total_credits} credits")
        print("✅ 已抓取部分已存盘，workflow 会在本步后提交，恢复额度后重跑即可续传。")
    else:
        print(f"\n✅ 完成: {success}/{len(to_fetch)}  💰 {total_credits} credits")


if __name__ == "__main__":
    main()
