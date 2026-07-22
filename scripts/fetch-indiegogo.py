#!/usr/bin/env python3
"""Fetch Indiegogo active projects with physical-product keyword filtering."""
import json, time, urllib.request, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safeio import atomic_write_json
from blacklist import is_blacklisted, blacklist_size

OUTPUT = Path(__file__).parent / "raw" / "indiegogo.json"

# Physical product keywords for filtering
PHYSICAL_KW = [
    "robot", "drone", "smart", "sensor", "printer", "device", "wearable",
    "gadget", "speaker", "headphone", "camera", "charger", "battery",
    "3d print", "hardware", "tool", "light", "monitor", "keyboard", "headset",
    "watch", "home", "kitchen", "glass", "bag", "backpack", "desk", "chair",
    "bike", "scooter", "lens", "tripod", "mount", "dock", "stand", "adapter",
    "cable", "hub", "power", "solar", "display", "screen", "case", "stand",
    "fan", "cooler", "storage", "lock", "door", "window", "grill", "cook",
    "coffee", "water", "bottle", "mug", "pen", "notebook", "wallet", "card",
    "toy", "model", "kit", "console", "controller", "gamepad", "handheld",
    "gaming", "pc", "laptop", "tablet", "phone", "earbud", "buds", "pro",
]

# Non-physical keywords to exclude
NON_PHYSICAL_KW = [
    "film", "movie", "book", "album", "music", "comic", "podcast",
    "documentary", "song", "app", "software", "game", "nft", "token",
    "crypto", "web3", "metaverse", "virtual", "digital download",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
}

LIST_URL = "https://www.indiegogo.com/api/public/projects/getActiveCrowdfundingProjects"

def is_physical(name: str, desc: str) -> bool:
    """Check if project is likely a physical product."""
    text = (name + " " + desc).lower()
    for kw in NON_PHYSICAL_KW:
        if kw in text:
            return False
    for kw in PHYSICAL_KW:
        if kw in text:
            return True
    return False

def extract_project(p: dict) -> dict:
    """Extract and normalize a single IG project."""
    return {
        "id": f"ig-{p['projectUrlName']}",
        "name": p.get("projectName", ""),
        "blurb": p.get("shortDescription", ""),
        "slug": p.get("projectUrlName", ""),
        "state": "live",
        "platform": "indiegogo",
        "category": "",
        "parent_category": "",
        "category_id": 0,
        "image_full": p.get("projectImageUrl", ""),
        "image_med": p.get("projectImageUrl", ""),
        "image_thumb": p.get("projectImageUrl", ""),
        "image_1024x576": p.get("projectImageUrl", ""),
        "goal": float(p.get("campaignGoal") or 0),
        "pledged": float(p.get("fundsGathered") or 0),
        "backers_count": int(p.get("backerCount") or 0),
        "percent_funded": 0,
        "currency": p.get("currencyShortName", "USD"),
        "currency_symbol": "",
        "launched_at": p.get("campaignStartDate", ""),
        "deadline": p.get("campaignEndDate", ""),
        "creator_name": p.get("creatorName", ""),
        "creator_avatar_medium": "",
        "location": "",
        "country": "",
        "staff_pick": False,
        "video_url": "",
        "url": p.get("projectHomeUrl", ""),
        "reward_count": int(p.get("rewardCount") or 0),
        "update_count": int(p.get("updateCount") or 0),
        "comment_count": int(p.get("commentCount") or 0),
    }

def main():
    print("=" * 60)
    print("Fetching Indiegogo active projects")
    print("=" * 60)

    req = urllib.request.Request(LIST_URL, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            all_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Error fetching IG: {e}")
        return 0

    print(f"Total active IG projects: {len(all_data)}")
    print(f"(blacklist: {blacklist_size()} audited non-hardware slugs will be skipped)")

    projects = []
    physical_count = 0
    blacklisted_skipped = 0

    for p in all_data:
        # Permanent block: audited non-hardware slugs must never re-ingest
        if is_blacklisted(p.get("projectUrlName", "")):
            blacklisted_skipped += 1
            continue

        name = p.get("projectName", "")
        desc = p.get("shortDescription", "")

        if is_physical(name, desc):
            physical_count += 1
            proj = extract_project(p)
            proj["percent_funded"] = round(
                (proj["pledged"] / proj["goal"] * 100) if proj["goal"] > 0 else 0, 1
            )
            proj["score"] = min(100, int(
                (proj["pledged"] / max(proj["goal"], 1)) * 10 +
                min(proj["backers_count"] / 10, 30)
            ))
            projects.append(proj)

    projects.sort(key=lambda x: x["pledged"], reverse=True)

    # Fetch creator details for top projects (batch with delays)
    for p in projects[:30]:
        if p["creator_name"]:
            try:
                time.sleep(0.5)
                cname = p["creator_name"].lower().replace(" ", "-")
                curl = f"https://www.indiegogo.com/api/public/creators/getCreator?urlName={cname}"
                creq = urllib.request.Request(curl, headers=HEADERS)
                with urllib.request.urlopen(creq, timeout=10) as r:
                    cd = json.loads(r.read().decode("utf-8"))
                if cd:
                    p["creator_avatar_medium"] = cd.get("thumbImageUrl", "")
            except Exception:
                pass

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUTPUT, {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "source": "Indiegogo Public API",
        "total_active": len(all_data),
        "physical_filtered": len(projects),
        "projects": projects,
    })  # 原子写：崩溃不损坏，写前备份 .bak

    print(f"\n✅ Indiegogo: {len(projects)} physical projects (from {len(all_data)} total) saved to {OUTPUT}")
    if blacklisted_skipped:
        print(f"   🚫 Skipped {blacklisted_skipped} blacklisted non-hardware slug(s)")
    return len(projects)

if __name__ == "__main__":
    main()
