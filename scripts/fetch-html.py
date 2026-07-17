#!/usr/bin/env python3
"""
fetch-html.py — 用 Firecrawl HTML 格式抓取 KS/IG 项目页
功能:
  1. Raw layer:  原始 HTML → gzip → scripts/raw/html/{slug}.html.gz
  2. Parsed layer: 解析 tiers/story/images → 写入 projects.json

用法:
  python scripts/fetch-html.py                                 # 全量跑
  python scripts/fetch-html.py --limit 3                        # 测试前 N 个
  python scripts/fetch-html.py --project omni-x1               # 指定项目slug
"""
import json, os, sys, time, gzip, hashlib
from pathlib import Path
from datetime import datetime, timezone

DATA_FILE = Path(__file__).parent.parent / "src" / "data" / "projects.json"
RAW_HTML_DIR = Path(__file__).parent / "raw" / "html"
SLEEP_SEC = 2
# 安全：API Key 从环境变量读取，禁止硬编码（避免泄露进 git/分享）
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
if not FIRECRAWL_API_KEY:
    print("ERROR: 环境变量 FIRECRAWL_API_KEY 未设置。请先 export FIRECRAWL_API_KEY=你的key 再运行。")
    sys.exit(1)

# 额度耗尽异常：firecrawl 不同版本位置可能不同，做兜底导入
try:
    from firecrawl.v2.utils.error_handler import PaymentRequiredError
except Exception:
    class PaymentRequiredError(Exception):
        """兜底：导入失败时不会实际抛出，仅用于类型匹配"""
        pass


def _save_raw_html(slug: str, html_text: str) -> dict:
    """将原始 HTML 压缩存储到 raw/html/{slug}.html.gz，返回 metadata"""
    ts = datetime.now(timezone.utc).isoformat()
    content_hash = hashlib.sha256(html_text.encode()).hexdigest()[:16]

    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    gz_path = RAW_HTML_DIR / f"{slug}.html.gz"

    with gzip.open(gz_path, "wt", encoding="utf-8") as f:
        f.write(html_text)

    return {
        "raw_html_hash": content_hash,
        "raw_html_path": str(gz_path.relative_to(Path(__file__).parent.parent)),
        "fetched_at": ts,
    }


def extract_html_content(url: str) -> dict:
    """抓取项目页原始 HTML（仅存盘，不做字段解析）

    规则 #12：所有字段提取必须由 AI 完成（见 ai-extract.py），
    禁止在此用 BeautifulSoup 解析 tiers/story/images。
    本函数只负责把 Firecrawl 返回的完整 HTML 交回调用方做 gzip 存盘。
    """
    from firecrawl import Firecrawl
    app = Firecrawl(api_key=FIRECRAWL_API_KEY)
    result = app.scrape(url, formats=["html"], only_main_content=False, proxy="auto", timeout=45000)
    credits = result.metadata.credits_used if result.metadata else 1
    return {
        "html_length": len(result.html),
        "credits": credits,
        "raw_html": result.html,  # 交给调用方存 gzip
    }


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


def main():
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
                result = extract_html_content(url)
                raw_meta = _save_raw_html(p.get("slug", p.get("id", target_project)), result["raw_html"])
                p["raw_html_hash"] = raw_meta["raw_html_hash"]
                p["raw_fetched_at"] = raw_meta["fetched_at"]
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"  ✅ 原始 HTML 已存盘: {result['html_length']} chars")
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
    print(f"💰 预计花费: ~{len(to_fetch)} credits\n")

    total_credits = 0
    success = 0
    stopped_by_credits = False

    for i, p in enumerate(to_fetch):
        name = p.get("name", "?")[:50]
        url = p.get("url", "")
        print(f"[{i+1}/{len(to_fetch)}] {name}")
        if not url:
            print("  ⚠️  无 URL，跳过")
            continue
        try:
            result = extract_html_content(url)
        except PaymentRequiredError:
            print(f"\n💳 Firecrawl 额度耗尽！已成功抓取 {success}/{len(to_fetch)} 个。")
            print(f"   剩余 {len(to_fetch) - i} 个项目未抓取 —— 请充值后重新运行 workflow。")
            print(f"   已抓取的 HTML 文件保留在 {RAW_HTML_DIR.name}/，")
            print(f"   needs_refetch 会自动跳过，重跑不会重复计费。")
            stopped_by_credits = True
            break
        except Exception as e:
            print(f"  ❌ 抓取失败: {type(e).__name__}: {e}")
            print(f"     跳过，继续下一个")
            continue
        raw_meta = _save_raw_html(p.get("slug", p.get("id", str(i))), result["raw_html"])
        p["raw_html_hash"] = raw_meta["raw_html_hash"]
        p["raw_fetched_at"] = raw_meta["fetched_at"]
        total_credits += result["credits"]
        success += 1
        print(f"  ✅ 原始HTML:{result['html_length']}chars  💰 {result['credits']}cr")
        if (i + 1) % 20 == 0:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  💾 保存 ({i+1}/{len(to_fetch)})")
        time.sleep(SLEEP_SEC)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if stopped_by_credits:
        print(f"\n⏸️  因额度不足提前结束: 成功 {success}/{len(to_fetch)}  💰 {total_credits} credits")
        print("✅ 已抓取部分已存盘，workflow 会在本步后提交，充值后重跑即可续传。")
    else:
        print(f"\n✅ 完成: {success}/{len(to_fetch)}  💰 {total_credits} credits")


if __name__ == "__main__":
    main()
