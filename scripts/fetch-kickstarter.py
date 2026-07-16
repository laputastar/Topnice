#!/usr/bin/env python3
"""Fetch Kickstarter live physical-product projects via Discover JSON API."""
import json, time, urllib.request, sys
from datetime import datetime
from pathlib import Path

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

def main():
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
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump({
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "source": "Kickstarter Discover API",
            "count": len(all_projects),
            "projects": all_projects,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Kickstarter: {len(all_projects)} live physical projects saved to {OUTPUT}")
    return len(all_projects)

if __name__ == "__main__":
    main()
