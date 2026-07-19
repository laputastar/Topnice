#!/usr/bin/env python3
"""Fetch Kickstarter live physical-product projects via Discover JSON API."""
import json, time, urllib.request, sys, re, gzip
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safeio import atomic_write_json, load_json_safe

OUTPUT = Path(__file__).parent / "raw" / "kickstarter.json"

# Physical product subcategory IDs (verified from KS API)
PHYSICAL_SUB_IDS = {
    338,  # Robots
    337,  # Gadgets
    341,  # Wearables
    52,   # Hardware
    339,  # Sound
    334,  # DIY Electronics
    331,  # 3D Printing
    333,  # Camera Equipment
    28,   # Product Design
    396,  # Toys
}

# Digital / non-hardware subcategories to exclude
EXCLUDE_SUB_IDS = {
    51,   # Software
    332,  # Apps
    342,  # Web
    35,   # Video Games
    400,  # STL
    258,  # Architecture
    399,  # TTRPG
    34,   # Tabletop Games
    273,  # Playing Cards
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.kickstarter.com/discover/advanced",
    "Origin": "https://www.kickstarter.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

BASE_URL = "https://www.kickstarter.com/discover/advanced?format=json"
SORT_ORDERS = ["newest", "end_date", "popularity", "magic", "most_backed"]

def fetch_page(category_id: int, page: int, sort: str, retries: int = 3) -> dict | None:
    url = f"{BASE_URL}&sort={sort}&category_id={category_id}&page={page}&state=live"
    req = urllib.request.Request(url, headers=HEADERS)
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = e
            print(f"  ⚠️ page {page}: {e} (retry {attempt+1}/{retries})")
            time.sleep(2 * (attempt + 1))
    return None

def parse_data_initial(html: str) -> dict | None:
    """Extract the embedded project JSON from a KS project page's
    `data-initial` attribute. The value is an HTML-escaped JSON string
    wrapping {"project": <camelCase model>}. This is the stable JSON data
    contract (rule #12 path A: clean structured data, parsed directly).
    Returns the raw camelCase project model dict, or None on failure.
    """
    if not html:
        return None
    m = re.search(r'data-initial="(.*?)"', html, flags=re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(unescape(m.group(1)))
        proj = obj.get("project") if isinstance(obj, dict) else None
        if not isinstance(proj, dict) or "pid" not in proj:
            return None
        return proj
    except Exception:
        return None


def extract_project_from_page(p: dict) -> dict:
    """Normalize a KS project-page (data-initial) model into our schema.

    The project-page model is structurally different from the Discover API
    model (camelCase nested: pid/pledged.amount/backersCount/deadlineAt)
    vs snake_case flat (id/pledged/backers_count/deadline), so a separate
    mapper is required — extract_project() cannot consume it directly.
    """
    cat = p.get("category", {}) or {}
    parent = cat.get("parentCategory", {}) or {}
    creator = p.get("creator", {}) or {}
    loc = p.get("location", {}) or {}
    goal = p.get("goal", {}) or {}
    pledged = p.get("pledged", {}) or {}
    vid = (p.get("video") or {}).get("videoSources", {}) or {}
    deadline = p.get("deadlineAt")
    return {
        "id": f"ks-{p.get('pid', p.get('id'))}",
        "name": p.get("name", ""),
        "blurb": p.get("description", ""),
        "slug": p.get("url", "").rstrip("/").split("/")[-1],
        "state": (p.get("state") or "").lower(),
        "platform": "kickstarter",
        "category": cat.get("name", ""),
        "parent_category": parent.get("name", ""),
        "category_id": cat.get("id", 0),
        "image_full": p.get("imageUrl", ""),
        "image_med": p.get("imageUrl", ""),
        "image_thumb": p.get("imageUrl", ""),
        "image_1024x576": p.get("imageUrl", ""),
        "goal": float(goal.get("amount", 0) or 0),
        "pledged": float(pledged.get("amount", 0) or 0),
        "backers_count": int(p.get("backersCount", 0) or 0),
        "percent_funded": float(p.get("percentFunded", 0) or 0),
        "currency": p.get("currency", "USD"),
        "currency_symbol": pledged.get("symbol", "$"),
        "launched_at": "",
        "deadline": datetime.fromtimestamp(deadline).isoformat() if deadline else "",
        "creator_name": creator.get("name", ""),
        "creator_avatar_medium": creator.get("imageUrl", ""),
        "location": loc.get("displayableName", ""),
        "country": loc.get("displayableName", ""),
        "staff_pick": bool(p.get("isProjectWeLove", False)),
        "video_url": (vid.get("high") or {}).get("src", ""),
        "url": p.get("url", ""),
    }


def extract_vars_from_page(p: dict) -> dict:
    """Watchlist-only mapper: emit JUST the dynamic variables + identity.

    Deliberately omits name/blurb/image/content fields so that merge.py sees
    no content change and never re-triggers translation on already-translated
    products. (Variables only → zero wasted re-translation / zero token waste)
    """
    goal = p.get("goal", {}) or {}
    pledged = p.get("pledged", {}) or {}
    deadline = p.get("deadlineAt")
    return {
        "id": f"ks-{p.get('pid', p.get('id'))}",
        "platform": "kickstarter",
        "source": "kickstarter_watchlist",
        "slug": (p.get("url", "") or "").rstrip("/").split("/")[-1] or str(p.get("pid")),
        "pledged": float(pledged.get("amount", 0) or 0),
        "goal": float(goal.get("amount", 0) or 0),
        "backers_count": int(p.get("backersCount", 0) or 0),
        "percent_funded": float(p.get("percentFunded", 0) or 0),
        "currency": p.get("currency", "USD"),
        "deadline": datetime.fromtimestamp(deadline).isoformat() if deadline else "",
        "state": (p.get("state") or "").lower(),
        "staff_pick": bool(p.get("isProjectWeLove", False)),
    }


def fetch_project_by_url(url: str, retries: int = 3) -> dict | None:
    """Watchlist fetch: LIVE GET of the KS project page (free direct HTTP,
    zero Firecrawl/Context.dev/TinyFish credits), then parse the embedded
    data-initial JSON. Falls back to locally cached HTML only if the live GET
    fails (e.g. KS rate-limit) — so variables are fresh on every online run.
    Returns the raw camelCase project model, or None if all sources fail.
    """
    if not url:
        return None
    # 1) Live GET (primary) — fresh variables every run, zero credit cost
    req = urllib.request.Request(url, headers=HEADERS)
    html = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8")
            break
        except Exception as e:
            print(f"  ⚠️ GET {url}: {e} (retry {attempt+1}/{retries})")
            time.sleep(2 * (attempt + 1))
    # 2) Fallback to cached HTML if live GET failed
    if html is None:
        slug = url.rstrip("/").split("/")[-1]
        cache = Path(__file__).parent / "raw" / "html" / f"{slug}.html.gz"
        if cache.exists():
            try:
                html = gzip.open(cache, "rt", encoding="utf-8", errors="replace").read()
            except Exception:
                html = None
    if not html:
        return None
    return parse_data_initial(html)


def extract_project(p: dict) -> dict:
    """Extract and normalize a single KS project."""
    cat = p.get("category", {})
    photo = p.get("photo", {})

    return {
        "id": f"ks-{p['id']}",
        "name": p.get("name", ""),
        "blurb": p.get("blurb", ""),
        "slug": p.get("slug", ""),
        "state": p.get("state", ""),
        "platform": "kickstarter",
        "category": cat.get("name", ""),
        "parent_category": cat.get("parent_name", ""),
        "category_id": cat.get("id", 0),
        "image_full": photo.get("full", ""),
        "image_med": photo.get("med", ""),
        "image_thumb": photo.get("thumb", ""),
        "image_1024x576": photo.get("1024x576", ""),
        "goal": float(p.get("goal", 0) or 0),
        "pledged": float(p.get("pledged", 0) or 0),
        "backers_count": int(p.get("backers_count", 0) or 0),
        "percent_funded": float(p.get("percent_funded", 0) or 0),
        "currency": p.get("currency", "USD"),
        "currency_symbol": p.get("currency_symbol", "$"),
        "launched_at": datetime.fromtimestamp(p.get("launched_at", 0)).isoformat() if p.get("launched_at") else "",
        "deadline": datetime.fromtimestamp(p.get("deadline", 0)).isoformat() if p.get("deadline") else "",
        "creator_name": p.get("creator", {}).get("name", ""),
        "creator_avatar_medium": p.get("creator", {}).get("avatar", {}).get("medium", ""),
        "location": p.get("location", {}).get("displayable_name", ""),
        "country": p.get("country_displayable_name", ""),
        "staff_pick": p.get("staff_pick", False),
        "video_url": p.get("video", {}).get("high", "") if p.get("video") else "",
        "url": p.get("urls", {}).get("web", {}).get("project", ""),
    }

def main_discover():
    print("=" * 60)
    print("Fetching Kickstarter live projects")
    print("=" * 60)

    all_projects = []
    seen_ids = set()

    # Strategy: multiple sort orders to maximize coverage of live projects.
    # KS API limits each sort to ~5 pages per subcategory (403 on page 6+).
    # Different sort orders surface different projects.
    for sort in SORT_ORDERS:
        print(f"\n{'='*50}")
        print(f"Sort: {sort}")
        print(f"{'='*50}")
        
        for sub_id in sorted(PHYSICAL_SUB_IDS):
            page = 1
            sub_count = 0
            total_hits = 0

            while True:
                data = fetch_page(sub_id, page, sort)
                if not data:
                    break

                projects = data.get("projects", [])
                total_hits = data.get("total_hits", 0)
                if not projects:
                    break

                new_in_page = 0
                for p in projects:
                    pid = p["id"]
                    if pid in seen_ids:
                        continue
                    seen_ids.add(pid)

                    sub = p.get("category", {}).get("id", 0)
                    if sub in EXCLUDE_SUB_IDS:
                        continue

                    all_projects.append(extract_project(p))
                    sub_count += 1
                    new_in_page += 1

                if new_in_page > 0:
                    print(f"  sub={sub_id:>3} sort={sort:12s} page={page:>2}: +{new_in_page:>2} new (sub_total: {sub_count})")

                if page * 12 >= total_hits:
                    break
                page += 1
                time.sleep(0.5)

            # Rate limit between subcategories
            time.sleep(1)
        
        # Rate limit between sort orders (longer pause to avoid 429)
        time.sleep(5)

    # Sort by pledged descending
    all_projects.sort(key=lambda x: x["pledged"], reverse=True)

    # Score is now computed by score.py during merge phase

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUTPUT, {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Kickstarter Discover API",
        "count": len(all_projects),
        "projects": all_projects,
    })  # 原子写：崩溃不损坏，写前备份 .bak

    print(f"\n✅ Kickstarter: {len(all_projects)} live physical projects saved to {OUTPUT}")
    return len(all_projects)

def main_watchlist(limit: int | None = None) -> int:
    """Refresh variables of ALL known KS projects by ID — no discovery pagination.

    Reads known KS IDs from src/data/projects.json, does a LIVE GET of each
    project page (free direct HTTP, zero Firecrawl/Context.dev/TinyFish credits),
    parses the embedded data-initial JSON, and writes the refreshed (variables-
    only) raw KS set back to raw/kickstarter.json. merge.py then propagates the
    variables into projects.json without re-running discovery (which is 403-rate-
    limited and causes stale variables on projects that drop off the discovery
    pages). Variables only → existing translated pages are NEVER re-translated.
    """
    print("=" * 60)
    print("Kickstarter watchlist refresh (known IDs only)")
    print("=" * 60)

    proj_file = Path(__file__).parent.parent / "src" / "data" / "projects.json"
    if not proj_file.exists():
        print("⚠️ projects.json not found — cannot build watchlist")
        return 0
    known = load_json_safe(proj_file).get("projects", [])
    ks = [p for p in known if p.get("platform") == "kickstarter" and p.get("url")]
    print(f"Known KS projects to refresh: {len(ks)}")

    refreshed, ok, failed = [], 0, 0
    for i, p in enumerate(ks):
        if limit is not None and i >= limit:
            break
        fresh = fetch_project_by_url(p["url"])
        if not fresh:
            print(f"  ⚠️ [{i + 1}/{len(ks)}] {str(p.get('name', ''))[:38]}: fetch failed, skipped")
            failed += 1
            continue
        refreshed.append(extract_vars_from_page(fresh))
        ok += 1
        if ok % 25 == 0:
            print(f"  ✓ {ok} refreshed...")
        time.sleep(0.3)  # be polite to KS; avoids 403 storms on bulk refresh

    # Merge with existing kickstarter.json (produced by the discover step)
    # instead of overwriting: preserves newly discovered projects not yet in
    # projects.json, and updates variables for known ones by id.
    existing = load_json_safe(OUTPUT)
    exist_projects = existing.get("projects", []) if isinstance(existing, dict) else []
    exist_map = {p.get("id"): p for p in exist_projects if isinstance(p, dict)}
    for rp in refreshed:
        exist_map[rp["id"]] = rp
    merged = list(exist_map.values())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUTPUT, {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Kickstarter Watchlist Refresh",
        "count": len(merged),
        "projects": merged,
    })
    print(f"\n✅ Watchlist: {ok} refreshed, {failed} skipped → {OUTPUT}")
    return ok


def main():
    args = sys.argv[1:]
    mode = "discover"
    limit = None
    if "watchlist" in args:
        mode = "watchlist"
    if "--limit" in args:
        try:
            limit = int(args[args.index("--limit") + 1])
        except Exception:
            limit = None
    if mode == "watchlist":
        return main_watchlist(limit=limit)
    return main_discover()


if __name__ == "__main__":
    main()
