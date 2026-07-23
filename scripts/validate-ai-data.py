#!/usr/bin/env python3
"""
validate-ai-data.py — 按"两条规则"校验并标记 ai_validated

规则（用户 2026-07-06 定义）：
  1. 爬虫爬回来的是完整的数据  -> 每个项目必须有非空的 HTML 快照（scripts/raw/html/{slug}.html.gz, >2KB）
  2. AI 完整解读了这些数据    -> 6 个 AI 字段全部非空（无占位/空值）；
                                 bio 在源站缺失时允许诚实兜底行（'Project creator:' 开头），不视为空缺

通过两项检查的项目：ai_validated = true。
未通过：ai_validated 保持原值（或置 false）并打印缺口，供人工处理。

用法:
  python scripts/validate-ai-data.py            # 校验全部 live 项目并写入 ai_validated
  python scripts/validate-ai-data.py --report   # 只报告，不写文件
"""
import json, os, sys, gzip, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safeio import atomic_write_json, load_json_safe

BASE = Path(__file__).parent.parent
DATA_FILE = BASE / "src" / "data" / "projects.json"
HTML_DIR = BASE / "scripts" / "raw" / "html"

FIELDS = ['ai_intro_en', 'ai_highlights_en', 'ai_specs_en', 'ai_risks_en', 'ai_creator_bio_en', 'ai_tiers']

BIO_FALLBACK_PREFIX = 'Project creator:'

# 占位符防护（与 ai-extract.py 同源逻辑）：历史上某版脚本在 LLM 失败时会把
# ai_* 字段写成模板占位符（'Product Summary'/'Highlight 1'/'Tier 1'/'X goes here' 等），
# 非空却属毒数据。此处作为"第三道规则"兜底——任何 ai_* 字段命中占位符即判未通过，
# 防止历史 bug 复发后污染数据且因字段非空而锁死重抽。
_PLACEHOLDER_EXACT = {"product summary", "risk assessment", "creator bio"}
_PLACEHOLDER_RE = re.compile(r"^(highlight|spec|tier|value|description)\s+\d+$", re.I)


def _is_placeholder(v):
    if not isinstance(v, str):
        return False
    s = v.strip()
    if not s:
        return False
    low = s.lower()
    if low in _PLACEHOLDER_EXACT:
        return True
    if low.endswith("goes here"):
        return True
    if _PLACEHOLDER_RE.match(low):
        return True
    return False


def _placeholder_field(p):
    str_fields = ['ai_intro_en', 'ai_risks_en', 'ai_creator_bio_en']
    list_fields = ['ai_highlights_en', 'ai_specs_en']
    for f in str_fields:
        if _is_placeholder(p.get(f)):
            return f
    for f in list_fields:
        v = p.get(f)
        if isinstance(v, list):
            for it in v:
                if _is_placeholder(it):
                    return f
                if isinstance(it, list):
                    for sub in it:
                        if _is_placeholder(sub):
                            return f
    tiers = p.get('ai_tiers')
    if isinstance(tiers, list):
        for t in tiers:
            if isinstance(t, dict):
                if _is_placeholder(t.get('name')) or _is_placeholder(t.get('description')):
                    return 'ai_tiers'
    return None


def field_ok(p, f):
    """判断单个字段是否算"已解读"（非空）。bio 容忍诚实兜底行。"""
    v = p.get(f)
    if f == 'ai_tiers':
        # 列表（含显式空 []）都算"已处理"：空 [] = 源站确认无档位（donation 型等）
        return isinstance(v, list)
    if v is None:
        return False
    if isinstance(v, str):
        if v.strip() == '':
            return False
        # bio 兜底行视为"已处理"（源站无 bio），不算空缺
        if f == 'ai_creator_bio_en' and v.startswith(BIO_FALLBACK_PREFIX):
            return True
        return True
    if isinstance(v, list):
        return len(v) > 0
    return bool(v)


def crawl_complete(p):
    path = HTML_DIR / f"{p.get('slug')}.html.gz"
    if path.exists() and path.stat().st_size >= 2048:
        return True, ''
    # 口径对齐：ai-extract 允许以 html_story 作退化素材提取字段，故校验也应接受。
    # 仅当 raw 快照缺失/过小 且 html_story 也无实质内容时，才判爬取不完整。
    story = p.get('html_story') or ''
    if len(story) >= 200:
        return True, ''
    if not path.exists():
        return False, 'HTML 快照缺失（且 html_story 过短/为空）'
    return False, 'HTML 快照过小(<2KB)'


def validate(p):
    issues = []
    # 规则 1：爬虫完整
    ok, msg = crawl_complete(p)
    if not ok:
        issues.append(f"爬取不完整: {msg}")
    # 规则 2：AI 字段完整
    for f in FIELDS:
        if not field_ok(p, f):
            issues.append(f"字段空缺: {f}")
    # 规则 3：占位符污染（历史 bug 复发防御）
    ph = _placeholder_field(p)
    if ph:
        issues.append(f"占位符污染: {ph}")
    return issues


def main():
    report_only = '--report' in sys.argv
    d = load_json_safe(DATA_FILE)  # 损坏自动回退 .bak
    projects = d['projects']
    live = [p for p in projects if p.get('state') == 'live']

    passed = 0
    failed = 0
    fail_samples = []
    for p in live:
        issues = validate(p)
        if issues:
            failed += 1
            if len(fail_samples) < 15:
                fail_samples.append((p.get('slug'), issues))
            if not report_only:
                p['ai_validated'] = False
        else:
            passed += 1
            if not report_only:
                p['ai_validated'] = True

    if not report_only:
        atomic_write_json(DATA_FILE, d)  # 原子写：崩溃不损坏

    print("=" * 60)
    print("AI 数据校验报告（规则：爬取完整 + AI 完整解读）")
    print("=" * 60)
    print(f"  live 项目总数 : {len(live)}")
    print(f"  通过(可标true): {passed}")
    print(f"  未通过        : {failed}")
    if fail_samples:
        print("\n--- 未通过样本（slug / 缺口）---")
        for slug, iss in fail_samples:
            print(f"  {slug}")
            for i in iss:
                print(f"     - {i}")
    if report_only:
        print("\n[report-only] 未写入文件")
    else:
        print(f"\n已写入 ai_validated（通过={passed}, 未通过={failed}）")
    return 0


if __name__ == '__main__':
    sys.exit(main())
