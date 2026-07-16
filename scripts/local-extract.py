#!/usr/bin/env python3
"""
local-extract.py — 本地无 API 抽取缺失的 AI 结构化字段
=====================================================
策略（与 ai-extract.py 的 LLM 方案互补）：
  - 上线前用本地 BeautifulSoup 直接解析 gz HTML，不调用任何 LLM/API。
  - 仅填补【空缺】字段：ai_tiers / ai_creator_bio_en / ai_risks_en。
  - 绝不覆盖已有的 LLM 产出（叙事类 intro/highlights/specs 已 100% 完成，保留）。
  - 源数据缺失时写【事实性兜底】文案（不编造、不幻觉）。

字段 schema（与 ai-extract.py 产出一致）：
  ai_tiers: [{name, price(数值), price_usd(null), currency, backers(int|null), description}]
  ai_creator_bio_en: str
  ai_risks_en: str

用法:
  python scripts/local-extract.py                 # 填补全部空缺
  python scripts/local-extract.py --dry-run       # 只统计不写盘
  python scripts/local-extract.py --limit 5       # 仅前 5 个（测试）
  python scripts/local-extract.py --slug SOME-SLUG # 单项目
"""
import json, gzip, os, re, sys, shutil
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'src', 'data', 'projects.json')
HTML_DIR = os.path.join(ROOT, 'scripts', 'raw', 'html')

PRICE_RE = re.compile(r'(?:US\$|\$|€|£|¥|HK\$)?\s*([\d][\d,]*(?:\.\d+)?)')
BACKER_RE = re.compile(r'([\d][\d,]*)\s+backers', re.I)
NUM_RE = re.compile(r'[\d][\d,]*(?:\.\d+)?')


def read_html(slug):
    p = os.path.join(HTML_DIR, f'{slug}.html.gz')
    if not os.path.exists(p):
        return None
    return gzip.open(p, 'rt', encoding='utf-8', errors='ignore').read()


# ---------- KS tiers ----------
def extract_ks_tiers(soup, currency):
    tiers = []
    for a in soup.find_all('article'):
        txt = a.get_text(' ', strip=True)
        if not PRICE_RE.search(txt) or not a.find('h3'):
            continue
        h3 = a.find('h3')
        name = h3.get_text(' ', strip=True)
        if 'pledge without a reward' in name.lower():
            continue
        price = None
        # 精确优先：header 内的价格 <p>（class 含 shrink0/type-18），避免抽到 USD 副标签
        header = a.find('header')
        if header:
            hp = header.find('p')
            if hp:
                m = PRICE_RE.search(hp.get_text(' ', strip=True))
                if m:
                    price = float(m.group(1).replace(',', ''))
        # 兜底：第一个含价格的 <p>
        if price is None:
            for p in a.find_all('p'):
                pt = p.get_text(' ', strip=True)
                m = PRICE_RE.search(pt)
                if m:
                    price = float(m.group(1).replace(',', ''))
                    break
        if price is None:
            continue
        desc = ''
        dv = a.find('div', class_=re.compile('text-prewrap', re.I))
        if dv:
            desc = dv.get_text(' ', strip=True)
        else:
            divs = [x for x in a.find_all('div') if 30 < len(x.get_text(' ', strip=True)) < 600]
            if divs:
                desc = max(divs, key=lambda x: len(x.get_text(' ', strip=True))).get_text(' ', strip=True)
        m = BACKER_RE.search(txt)
        backers = int(m.group(1).replace(',', '')) if m else None
        tiers.append({
            'name': name,
            'price': price,
            'price_usd': None,
            'currency': currency,
            'backers': backers,
            'description': desc,
        })
    return tiers


# ---------- IG tiers ----------
def extract_ig_tiers(soup, currency):
    tiers = []
    cards = soup.find_all(class_=re.compile(r'reward-card|perk|tier-card', re.I))
    if not cards:
        # fallback: 任何含价格的 article
        cards = [a for a in soup.find_all('article') if PRICE_RE.search(a.get_text(' ', strip=True))]
    for c in cards:
        txt = c.get_text(' ', strip=True)
        m = PRICE_RE.search(txt)
        if not m:
            continue
        price = float(m.group(1).replace(',', ''))
        name_el = c.find(['h2', 'h3', 'h4'], class_=re.compile(r'title|name', re.I)) or c.find(['h2', 'h3', 'h4'])
        name = name_el.get_text(' ', strip=True) if name_el else (txt[:60])
        desc_el = c.find(class_=re.compile(r'description|detail', re.I))
        desc = desc_el.get_text(' ', strip=True) if desc_el else ''
        mb = BACKER_RE.search(txt)
        backers = int(mb.group(1).replace(',', '')) if mb else None
        tiers.append({
            'name': name,
            'price': price,
            'price_usd': None,
            'currency': currency,
            'backers': backers,
            'description': desc,
        })
    return tiers


# ---------- risks ----------
def extract_risks(soup):
    el = soup.find(class_=re.compile(r'js-risks-text', re.I)) or soup.find(class_=re.compile(r'\brisks\b', re.I))
    if el:
        t = el.get_text(' ', strip=True)
        t = re.sub(r'^risks and challenges\s*', '', t, flags=re.I).strip()
        if len(t) > 30:
            return t
    # 宽搜标题
    for h in soup.find_all(['h2', 'h3', 'h4', 'h5']):
        if re.search(r'risks? and challeng', h.get_text(' ', strip=True), re.I):
            sib = h.find_next_sibling()
            if sib:
                t = sib.get_text(' ', strip=True)
                if len(t) > 30:
                    return t
    return None


# ---------- creator bio ----------
def extract_creator_bio(soup, project):
    cands = []
    for el in soup.find_all(class_=re.compile(r'creator', re.I)):
        for p in el.find_all('p'):
            t = p.get_text(' ', strip=True)
            if 40 <= len(t) <= 400:
                cands.append(t)
    if cands:
        return max(cands, key=len)
    # 兜底：事实性行（不编造）
    name = project.get('creator_name') or project.get('name', '')
    loc = project.get('location') or project.get('country') or ''
    cat = project.get('parent_category') or project.get('category') or ''
    parts = [x for x in [name, loc, cat] if x]
    return ('Project creator: ' + ', '.join(parts)) if parts else None


def main():
    dry = '--dry-run' in sys.argv
    limit = None
    slug_filter = None
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
    if '--slug' in sys.argv:
        slug_filter = sys.argv[sys.argv.index('--slug') + 1]

    data = json.load(open(DATA))
    projects = data['projects']
    live = [p for p in projects if p.get('state') == 'live']
    if slug_filter:
        live = [p for p in live if p.get('slug') == slug_filter]

    stats = {'tiers': 0, 'risks': 0, 'bio': 0, 'checked': 0}
    for p in live:
        if limit is not None and stats['checked'] >= limit:
            break
        stats['checked'] += 1
        slug = p.get('slug')
        if not slug:
            continue
        # 已填满的跳过（避免无谓 IO）
        if p.get('ai_tiers') and p.get('ai_risks_en') and p.get('ai_creator_bio_en'):
            continue
        html = read_html(slug)
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        cur = p.get('currency') or 'USD'
        plat = p.get('platform')

        if not p.get('ai_tiers'):
            if plat == 'kickstarter':
                tiers = extract_ks_tiers(soup, cur)
            else:
                tiers = extract_ig_tiers(soup, cur)
            if tiers:
                p['ai_tiers'] = tiers
                stats['tiers'] += 1

        if not p.get('ai_risks_en'):
            r = extract_risks(soup)
            if r:
                p['ai_risks_en'] = r
                stats['risks'] += 1
            else:
                p['ai_risks_en'] = 'Risks and challenges not specified by the project creator.'
                stats['risks'] += 1

        if not p.get('ai_creator_bio_en'):
            b = extract_creator_bio(soup, p)
            if b:
                p['ai_creator_bio_en'] = b
                stats['bio'] += 1

        if not dry:
            p['ai_source'] = 'local-extract'

    print(f"checked={stats['checked']} | filled tiers={stats['tiers']} risks={stats['risks']} bio={stats['bio']} | dry={dry}")

    if not dry:
        # 备份 + 原子写
        bak = DATA + '.bak2'
        shutil.copy2(DATA, bak)
        tmp = DATA + '.tmp'
        json.dump(data, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
        os.replace(tmp, DATA)
        print(f"written. backup -> {os.path.basename(bak)}")


if __name__ == '__main__':
    main()
