#!/usr/bin/env python3
"""
pipeline.py — TopNice 每日数据管线（一次性编排）

执行顺序:
  1. fetch-kickstarter.py  → raw/kickstarter.json
  2. fetch-indiegogo.py    → raw/indiegogo.json
  3. fetch-html.py         → raw/html/*.html.gz（仅新项目，gzip 存盘）
  4. merge.py              → projects.json（解析 + 去重 + 历史 + 评分 + 硬件过滤）
  5. ai-extract.py         → 用 LLM 从 raw HTML 提取 6 个 AI 字段（仅缺字段的 live 项目）
  6. validate-ai-data.py   → 按两规则校验并写 ai_validated
  7. translate_zh.py extract → 抽取未翻译字段到 scripts/translations/batch_*.jsonl
  8. cf-translate.py       → 逐批调用 Cloudflare Workers AI 翻译 → *_zh.jsonl
  9. translate_zh.py apply   → 翻译结果回填 projects.json

环境变量（均从环境变量读取，禁止硬编码）:
  FIRECRAWL_API_KEY        Firecrawl（抓取 HTML）
  CLOUDFLARE_ACCOUNT_ID    Cloudflare Workers AI（硬件过滤 + 翻译）
  CLOUDFLARE_API_TOKEN     Cloudflare Workers AI
  LONG_CAT_API_KEY         AI 提取主引擎（可选，失败回退 Agnes/CF）
  AGNES_API_KEY            AI 提取备用引擎（可选）
  CF_PROXY                 （可选）中国网络访问 CF 的本地代理
  CF_TRANSLATE_MODEL       （可选）覆盖翻译模型
"""
import sys, subprocess, time, glob, os
from pathlib import Path

SCRIPTS = Path(__file__).parent
TRANSLATIONS = SCRIPTS / "translations"

STEPS = [
    ("1/9", "Fetching KS API",          ["python", str(SCRIPTS / "fetch-kickstarter.py")]),
    ("2/9", "Fetching IG API",          ["python", str(SCRIPTS / "fetch-indiegogo.py")]),
    ("3/9", "Fetching HTML (new only)", ["python", str(SCRIPTS / "fetch-html.py")]),
    ("4/9", "Merging + History + Score",["python", str(SCRIPTS / "merge.py")]),
    ("5/9", "AI extracting fields",     ["python", str(SCRIPTS / "ai-extract.py")]),
    ("6/9", "Validating AI data",       ["python", str(SCRIPTS / "validate-ai-data.py")]),
]


def run_cmd(label, cmd):
    print(f"\n▶  [{label}] {' '.join(cmd)}")
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=False)
    elapsed = time.time() - t0
    if r.returncode != 0:
        print(f"\n❌ Failed at step [{label}] — exit code {r.returncode}")
        sys.exit(1)
    print(f"   ✅ 完成 ({elapsed:.1f}s)")


def run_translation():
    """translate_zh extract → cf-translate(逐批) → translate_zh apply"""
    print(f"\n▶  [7/9] Extracting untranslated fields")
    t0 = time.time()
    r = subprocess.run(["python", str(SCRIPTS / "translate_zh.py"), "extract"],
                       capture_output=False)
    if r.returncode != 0:
        print(f"\n❌ Failed at step [7/9] — exit code {r.returncode}")
        sys.exit(1)
    print(f"   ✅ 完成 ({time.time()-t0:.1f}s)")

    # 找出所有待翻译批次
    batches = sorted(glob.glob(str(TRANSLATIONS / "batch_*.jsonl")))
    # 排除已翻译产物（*_zh.jsonl）
    batches = [b for b in batches if not b.endswith("_zh.jsonl")]
    if not batches:
        print("   ℹ️  无待翻译批次（中文已全覆盖），跳过翻译")
        return

    print(f"\n▶  [8/9] Translating {len(batches)} batch(es) via Cloudflare Workers AI")
    t0 = time.time()
    for b in batches:
        print(f"   📝 {os.path.basename(b)}")
        r = subprocess.run(["python", str(SCRIPTS / "cf-translate.py"), b],
                           capture_output=False)
        if r.returncode != 0:
            print(f"\n❌ Translation failed at {b} — exit code {r.returncode}")
            sys.exit(1)
    print(f"   ✅ 完成 ({time.time()-t0:.1f}s)")

    print(f"\n▶  [9/9] Applying translations to projects.json")
    t0 = time.time()
    zh_files = sorted(glob.glob(str(TRANSLATIONS / "batch_*_zh.jsonl")))
    if not zh_files:
        print("   ⚠️  未生成 *_zh.jsonl，跳过 apply")
        return
    r = subprocess.run(["python", str(SCRIPTS / "translate_zh.py"), "apply", *zh_files],
                       capture_output=False)
    if r.returncode != 0:
        print(f"\n❌ Failed at step [9/9] — exit code {r.returncode}")
        sys.exit(1)
    print(f"   ✅ 完成 ({time.time()-t0:.1f}s)")


def run():
    print("=" * 60)
    print("TopNice Pipeline —", time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
    print("=" * 60)

    for label, desc, cmd in STEPS:
        run_cmd(label, cmd)

    run_translation()

    print("\n" + "=" * 60)
    print("✅ Pipeline complete")
    print("=" * 60)


if __name__ == "__main__":
    run()
