#!/usr/bin/env python3
"""
validate-tiers.py — 档位漏抓守卫 (Tier-capture guard)

用途:
  在数据 merge 进 projects.json 之前跑一遍, 确认每个项目抓回的 ai_tiers
  数量 == 原始页面实际展示的档位数量. 任何 "页面有 N 个档位但只抓到 M<N 个"
  都会被标红, 防止再出现 OneXPlayer 漏抓第 3 个档位 (64GB+2TB) 的情况.

判定逻辑:
  - Indiegogo: 静态 HTML 的目录 (data-qa="sidebar-category-section:...") 完整列出
    每个 perk 名. 抽出其中的配置令牌 (如 48GB+1TB / 64GB+2TB), 与 ai_tiers 名称里的
    令牌做集合比对. 页面有而 ai_tiers 没有 => MISSING.
  - Kickstarter: 档位由 JS 渲染, 静态 HTML 不含列表. 改为软检查:
      * ai_tiers 为空 且项目有 backers/reward_count => REVIEW(可能整段漏抓)
      * 否则 OK(数量无法自动校验, 需人工抽查)
  - 任一 MISSING => 进程返回码 1 (可接入 CI / pre-commit 关卡).

用法:
  python scripts/validate-tiers.py [--data src/data/projects.json] [--raw scripts/raw/html]
"""
import json, os, re, sys, gzip, argparse

CONFIG_TOKEN = re.compile(r'(\d+GB\+?\d*TB?)', re.I)
PERK_SECTION = re.compile(r'data-qa="sidebar-category-section:([^"]+)"')

def platform_of(p):
    return (p.get('platform') or '').lower()

def tokens(text):
    return set(t.upper() for t in CONFIG_TOKEN.findall(text or ''))

def html_perk_tokens(slug, raw_dir):
    path = os.path.join(raw_dir, f"{slug}.html.gz")
    if not os.path.exists(path):
        return None  # 无 HTML 快照, 无法判定
    h = gzip.open(path, 'rb').read().decode('utf-8', 'ignore')
    toks = set()
    for name in PERK_SECTION.findall(h):
        toks |= tokens(name)
    return toks

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='src/data/projects.json')
    ap.add_argument('--raw', default='scripts/raw/html')
    args = ap.parse_args()

    data = json.load(open(args.data, encoding='utf-8'))
    projects = data['projects'] if isinstance(data, dict) and 'projects' in data else data

    problems = []   # (slug, platform, status, detail)
    print(f"{'SLUG':52} {'PLAT':4} {'STATUS':8} DETAIL")
    print('-' * 110)

    for p in projects:
        slug = p.get('slug', '?')
        plat = platform_of(p)
        tiers = p.get('ai_tiers') or []
        captured = tokens(' '.join(str(r.get('name', '')) for r in tiers))

        if plat == 'indiegogo':
            expected = html_perk_tokens(slug, args.raw)
            if expected is None:
                problems.append((slug, plat, 'REVIEW', 'no HTML snapshot'))
                print(f"{slug:52} IG   REVIEW  no HTML snapshot")
                continue
            missing = expected - captured
            if missing:
                problems.append((slug, plat, 'MISSING', f"page has {sorted(expected)}, missing {sorted(missing)}"))
                print(f"{slug:52} IG   MISSING  page={sorted(expected)} captured={sorted(captured)} -> missing {sorted(missing)}")
            else:
                print(f"{slug:52} IG   OK       {len(captured)} tiers matched")
        elif plat == 'kickstarter':
            if not tiers and (p.get('backers_count') or p.get('reward_count')):
                problems.append((slug, plat, 'REVIEW', 'ai_tiers empty but project has backers'))
                print(f"{slug:52} KS   REVIEW  ai_tiers empty but backers present")
            else:
                print(f"{slug:52} KS   OK*      {len(tiers)} tiers (JS-rendered; count not auto-verified)")
        else:
            print(f"{slug:52} {plat or '?':4} SKIP     unknown platform")

    print('-' * 110)
    if problems:
        print(f"✗ {len(problems)} project(s) need attention:")
        for slug, plat, st, detail in problems:
            print(f"  [{st}] {slug} ({plat}) — {detail}")
        sys.exit(1)
    else:
        print("✓ All checked projects passed tier-count validation.")
        sys.exit(0)

if __name__ == '__main__':
    main()
