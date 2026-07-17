#!/usr/bin/env python3
"""
ai-extract.py — 用 LLM 从原始抓取内容提取项目结构化字段

设计:
  - 优先读取 scripts/raw/html/{slug}.html.gz 原始 HTML（最完整）
  - 退回到 projects.json 的 html_story（若 raw HTML 缺失）
  - 清洗 HTML 后取正文文本喂给 LLM，让它输出与 KS 详情页同构的字段
  - 关键增强：LLM 同时产出 ai_tiers（档位/价格），解决 IG 正则解析失败的问题
  - KS / IG 共用同一套 AI schema，无需维护两套解析器

提供商: Long Cat (首选) → Agnes AI (备用)

用法:
  python scripts/ai-extract.py                              # 全量（只处理缺 AI 字段的 live 项目）
  python scripts/ai-extract.py --platform indiegogo --force # 强制重抽全部 IG（含 raw HTML tiers）
  python scripts/ai-extract.py --project omni-x1            # 指定项目
  python scripts/ai-extract.py --dry-run                    # 仅列出待处理
"""
import json, sys, os, gzip, re, time
from pathlib import Path
from datetime import datetime


# 统一 LLM/API 调用层（集中读 env、统一重试/超时）
sys.path.insert(0, str(Path(__file__).parent))
from llm import call_compatible_llm, call_cloudflare, parse_json
from safeio import atomic_write_json

DATA_FILE = Path(__file__).parent.parent / "src" / "data" / "projects.json"
RAW_HTML_DIR = Path(__file__).parent / "raw" / "html"

# LLM 配置
# 所有 Key 均从环境变量读取，禁止硬编码（防泄露进 git/分享）。
# 运行前请 export: LONG_CAT_API_KEY / AGNES_API_KEY / CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN
LLM_CONFIGS = [
    {
        "name": "Long Cat",
        "api_key_var": "LONG_CAT_API_KEY",
        "base_url": "https://api.longcat.chat/openai",
        "model": "LongCat-2.0",
        "timeout": 90,
    },
    {
        "name": "Agnes AI",
        "api_key_var": "AGNES_API_KEY",
        "base_url": "https://apihub.agnes-ai.com/v1",
        "model": "agnes-2.0-flash",
        "timeout": 90,
    },
]

# Cloudflare Workers AI 备用模型（仅当 LongCat+Agnes 都失败时使用；凭据统一在 llm.py 读取）
CF_AI_MODEL = "@cf/meta/llama-3.2-3b-instruct"

SYSTEM_PROMPT = """You are a senior crowdfunding product analyst. Given a project page's raw text, extract structured information.

Rules:
- Only extract information explicitly stated in the content
- If a field cannot be determined, return empty string or empty array
- Prices must come from the TIERS data, not guessed
- Do not fabricate, assume, or hallucinate
- Output will be shown on an English-language website

Respond ONLY with valid JSON, no markdown fences, no explanation."""

MAX_CONTENT_CHARS = 20000


def read_raw_html(slug: str):
    """读取 raw gz HTML，不存在返回 None"""
    gz = RAW_HTML_DIR / f"{slug}.html.gz"
    if gz.exists():
        return gzip.open(gz, "rt", encoding="utf-8", errors="ignore").read()
    return None


def html_to_llm_content(raw_html: str) -> str:
    """清洗 HTML → 正文文本（去除脚本/样式/噪音标签），供 LLM 解读档位+故事

    不使用外部解析库（BeautifulSoup），仅用标准库 re + 简单标签剥离。
    实际字段提取由 AI LLM 完成，规则解析器只做辅助定位。
    """
    if not raw_html:
        return ""

    # 预清洗：剥离导航/页脚/侧栏等噪音容器（标准语义标签，正则安全）
    cleaned = re.sub(
        r'<nav\b[^>]*>.*?</nav>', '',
        raw_html, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned = re.sub(
        r'<footer\b[^>]*>.*?</footer>', '',
        cleaned, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned = re.sub(
        r'<aside\b[^>]*>.*?</aside>', '',
        cleaned, flags=re.DOTALL | re.IGNORECASE
    )

    # 去掉 <script>, <style>, <noscript>, <svg>, <meta>, <link>, <head> 及其内容
    cleaned = re.sub(
        r'<(script|style|noscript|svg|meta|link|head)[^>]*>.*?</\1>',
        '', cleaned, flags=re.DOTALL | re.IGNORECASE
    )
    # 去掉剩余 HTML 标签，保留文本
    cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
    # 合并空白
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # 去掉过短行
    lines = [l.strip() for l in cleaned.split("\n") if len(l.strip()) >= 3]
    merged = "\n".join(lines)
    return merged[:MAX_CONTENT_CHARS]


def _call_llm(content: str, currency: str, platform: str, config: dict) -> dict | None:
    """调用单个 LLM，返回解析后的 dict 或 None"""
    user_prompt = (
        "You are analyzing a crowdfunding project page (raw page text). "
        "Extract structured information as JSON.\n\n"
        f"CONTEXT:\n- Platform: {platform}\n- Currency hint: {currency}\n\n"
        "Reward tiers may be called 'rewards', 'perks', 'contribution levels', or 'pledges'.\n\n"
        "Extract these fields:\n"
        "1. ai_intro_en: A 2-3 sentence product summary (max 400 chars)\n"
        "2. ai_highlights_en: Array of exactly 3 key selling points (each max 120 chars)\n"
        "3. ai_specs_en: Array of [spec_name, spec_value] pairs (max 12 pairs, include pricing if available)\n"
        "4. ai_risks_en: A brief, honest risk assessment (max 300 chars)\n"
        "5. ai_creator_bio_en: One-line creator/company description (max 200 chars)\n"
        "6. ai_tiers: Array of ALL reward/contribution tiers. Each tier object:\n"
        "   {\"name\": str, \"price\": number|null (native price as shown), "
        "\"price_usd\": number|null (USD equivalent if determinable), "
        "\"currency\": str (e.g. USD/HKD/EUR), \"backers\": number|null, "
        "\"description\": str (max 200 chars)}\n"
        "   - Extract EVERY tier with its price.\n"
        "   - If price is non-USD, put native price in 'price' with that 'currency', "
        "estimate 'price_usd' if inferable, else null.\n"
        "   - If no tiers on page, return empty array.\n\n"
        "PAGE TEXT:\n"
        f"{content}\n\n"
        "Respond ONLY with valid JSON, no markdown."
    )


    # 1) 尝试配置中的 OpenAI 兼容提供商 (LongCat / Agnes)，限流自动退避重试 1 次
    try:
        raw = call_compatible_llm(
            user_prompt,
            api_key=os.environ.get(config["api_key_var"], ""),
            base_url=config["base_url"],
            model=config["model"],
            system=SYSTEM_PROMPT,
            timeout=config["timeout"],
            max_retries=1,
        )
        return parse_json(raw)
    except Exception as e:
        print(f"  ⚠️  {config['name']} 失败: {e}")

    # 2) Cloudflare Workers AI 备用（无重试，与旧行为一致）
    print("  → 尝试 Cloudflare Workers AI 备用...")
    try:
        raw = call_cloudflare(user_prompt, model=CF_AI_MODEL, system=SYSTEM_PROMPT, timeout=60)
        return parse_json(raw)
    except Exception as e:
        print(f"  ❌ Cloudflare 备用也失败: {e}")
    return None
    return None
    return None


def extract(project: dict, force: bool = False) -> bool:
    """为单个项目提取 AI 字段。返回 True=成功写入，False=跳过/失败。"""
    if not force and project.get("ai_intro_en"):
        return False

    slug = project.get("slug") or project.get("id")
    platform = project.get("platform", "")
    currency = project.get("ai_currency") or project.get("currency_symbol") or "USD"

    # 优先 raw HTML，其次 html_story
    raw_html = read_raw_html(slug)
    content = html_to_llm_content(raw_html) if raw_html else (project.get("html_story") or "")
    src = "raw_html" if raw_html else ("html_story" if project.get("html_story") else "")

    if not content:
        print("  ⚠️  无 raw HTML 也无 html_story，跳过")
        return False

    print(f"  📖 来源:{src} | {len(content)} chars")

    result = None
    for i, config in enumerate(LLM_CONFIGS):
        name = config["name"]
        # 首选 provider 重试 3 次（应对偶发超时），其余 provider 只试 1 次
        max_attempts = 3 if i == 0 else 1
        for attempt in range(1, max_attempts + 1):
            print(f"  📡 尝试 {name}... (attempt {attempt}/{max_attempts})")
            result = _call_llm(content, currency, platform, config)
            if result:
                print(f"  ✅ {name} 成功")
                break
            if attempt < max_attempts:
                backoff = 2 * attempt  # 2s, 4s
                print(f"  ⏳ {name} 失败，{backoff}s 后重试")
                time.sleep(backoff)
        if result:
            break
        # 切到备用 provider 前冷却，避免紧跟重试触发免费版限流
        if i == 0:
            print(f"  ⏳ 切换备用前冷却 5s（避免免费版限流）")
            time.sleep(5)
        print(f"  ⏭️  {name} 失败，切换下一个")

    if not result:
        print("  ❌ 所有 LLM 提供商均失败")
        return False

    expected = ["ai_intro_en", "ai_highlights_en", "ai_specs_en",
                "ai_risks_en", "ai_creator_bio_en", "ai_tiers"]
    for field in expected:
        if field not in result:
            result[field] = [] if field in ("ai_highlights_en", "ai_specs_en", "ai_tiers") else ""

    # 写入（含 ai_tiers 同构字段）
    for field in expected:
        project[field] = result[field]

    project["ai_validated"] = False
    project["ai_source"] = src

    print(f"  ✅ intro {len(result.get('ai_intro_en',''))} | "
          f"highlights {len(result.get('ai_highlights_en',[]))} | "
          f"specs {len(result.get('ai_specs_en',[]))} | "
          f"tiers {len(result.get('ai_tiers',[]))}")
    return True


def main():
    force = "--force" in sys.argv
    dry_run = "--dry-run" in sys.argv
    only_empty_tiers = "--only-empty-tiers" in sys.argv
    target_project = None
    platform_filter = None

    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--project" and i + 2 < len(sys.argv):
            target_project = sys.argv[i + 2]
        elif arg == "--platform" and i + 2 < len(sys.argv):
            platform_filter = sys.argv[i + 2]

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    projects = data.get("projects", [])

    candidates = []
    for p in projects:
        if platform_filter and p.get("platform") != platform_filter:
            continue
        if p.get("platform") not in ("kickstarter", "indiegogo"):
            continue
        if p.get("state") not in ("live", "active"):
            continue
        if target_project and target_project not in p.get("slug", "") and target_project not in p.get("id", ""):
            continue
        if only_empty_tiers:
            if p.get("ai_tiers") and len(p.get("ai_tiers", [])) > 0:
                continue  # already has tiers, skip even if force
        elif not force and p.get("ai_intro_en"):
            continue
        # 需要 raw HTML 或 html_story 才能提取
        slug = p.get("slug") or p.get("id")
        if not read_raw_html(slug) and not p.get("html_story"):
            continue
        candidates.append(p)

    if dry_run:
        print(f"📋 待处理项目: {len(candidates)} 个")
        for p in candidates:
            has = "✅" if p.get("ai_intro_en") else "❌"
            src = "raw" if read_raw_html(p.get("slug") or p.get("id")) else "story"
            print(f"  {has} {p.get('platform')} | {p.get('name','?')[:42]} | src:{src}")
        return

    print(f"📊 待 AI 提取: {len(candidates)} 个项目")
    if not candidates:
        print("✅ 无待处理项目")
        return

    success = 0
    for i, p in enumerate(candidates):
        name = p.get("name", "?")[:50]
        print(f"\n[{i+1}/{len(candidates)}] {name}")
        ok = extract(p, force=force or only_empty_tiers)
        if ok:
            success += 1
        if (i + 1) % 5 == 0:
            atomic_write_json(DATA_FILE, data)  # 原子写：崩溃不损坏
            print(f"  💾 已保存 ({i+1}/{len(candidates)})")

    atomic_write_json(DATA_FILE, data)  # 原子写：崩溃不损坏

    print(f"\n✅ 完成: {success}/{len(candidates)} 成功")
    print(f"📊 预计 token 消耗: ~{success * 4000}")


if __name__ == "__main__":
    main()
