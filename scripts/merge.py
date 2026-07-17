#!/usr/bin/env python3
"""Merge KS + IG data into unified projects.json with deduplication, history, and scoring."""
import json, hashlib, os
from datetime import datetime
from pathlib import Path
import sys, requests
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

# 统一 LLM/API 调用层（集中读 env、统一重试/超时）
from llm import call_cloudflare, LLMError

from scripts.snapshot import batch_append
from scripts.score import batch_compute
from safeio import atomic_write_json, load_json_safe

RAW_DIR = Path(__file__).parent / "raw"
OUTPUT = Path(__file__).parent.parent / "src" / "data" / "projects.json"

# Cloudflare Workers AI — hardware classifier (free tier: 10K neurons/day)
# 凭据统一在 llm.py 读取（CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN）

HW_PROMPT = """You classify crowdfunding projects as hardware or non-hardware.
- hardware: electronics, gadgets, tools, robots, 3D printers, cameras, wearables, PC components, audio hardware, charging equipment, EDC gear, physical mechanical products.
- non-hardware: software, apps, films, books, music, food, clothing, skincare, crafts, digital goods, STL files, services, events.
Reply with exactly one word: hardware or non-hardware."""

_hw_session = None
def _get_hw_session():
    """复用连接的 Session（call_cloudflare 会自行注入鉴权头）"""
    global _hw_session
    if _hw_session is None:
        _hw_session = requests.Session()
    return _hw_session

def classify_hardware(name: str, blurb: str) -> str:
    """Returns 'hardware' or 'non-hardware' using Cloudflare Workers AI (free tier).

    Falls back to keyword-based heuristic when AI is unavailable.
    """
    # Keyword-based pre-filter: catch obvious non-hardware before AI
    _non_hw_keywords = [
        "board game", "card game", "tabletop", "rpg", "role-playing",
        "comic", "book", "novel", "publish", "zine",
        "film", "movie", "documentary", "video", "animation",
        "music", "album", "song", "concert",
        "food", "cook", "recipe", "beverage", "coffee", "tea",
        "fashion", "clothing", "apparel", "jewelry", "accessory",
        "software", "app ", " mobile app", "digital",
        "craft", "art ", "painting", "photography",
        "service", "event", "workshop", "class",
    ]
    combined = (name + " " + blurb[:200]).lower()
    for kw in _non_hw_keywords:
        if kw in combined:
            return "non-hardware"

    # AI classifier
    try:
        result = call_cloudflare(
            f"Name: {name}\nBlurb: {blurb[:200]}",
            model="@cf/meta/llama-3.2-3b-instruct",
            system=HW_PROMPT,
            temperature=0,
            max_tokens=10,
            timeout=15,
            max_retries=0,
            session=_get_hw_session(),
        ).strip().lower()
        return result if result in ("hardware", "non-hardware") else "hardware"
    except LLMError as e:
        print(f"  ⚠️ CF AI error: {e}")
        return "hardware"  # safe default: keep the project

# Category mapping from KS subcategory ID → TopNice category
CATEGORY_MAP = {
    338: "Robotics",
    337: "Gadgets",
    341: "Gadgets",
    52: "Hardware",
    339: "Hardware",
    334: "Hardware",
    331: "3D Printing",
    333: "Camera Gear",
    28: "Product Design",
    396: "Toys",
}

def normalize_category(proj: dict) -> str:
    """Infer unified TopNice category for any project."""
    cat_id = proj.get("category_id", 0)
    if cat_id in CATEGORY_MAP:
        return CATEGORY_MAP[cat_id]
    # Skip keyword inference for clearly non-hardware parents
    parent = (proj.get("parent_category") or "").lower()
    category = (proj.get("category") or "").lower()
    if any(p in parent or p in category for p in [
        "publishing", "film", "video", "music", "theater",
        "journalism", "comics", "crafts", "art", "dance",
    ]):
        return "Product Design"
    # Keyword inference
    name = (proj.get("name", "") + " " + proj.get("blurb", "")).lower()
    if any(k in name for k in ["robot", "drone"]): return "Robotics"
    if any(k in name for k in ["wearable", "gadget", "watch"]): return "Gadgets"
    if any(k in name for k in ["3d print", "printer"]): return "3D Printing"
    if any(k in name for k in ["camera", "lens", "tripod", "photo"]): return "Camera Gear"
    if any(k in name for k in ["toy", "plush", "doll", "figure"]): return "Toys"
    if any(k in name for k in ["keyboard", "monitor", "pc", "gaming", "display",
        "charger", "cable", "hub", "dock", "adapter", "battery", "power",
        "solar", "headphone", "speaker", "audio"]): return "Hardware"
    return "Product Design"

def content_hash(proj: dict) -> str:
    """Hash of static fields to detect content changes."""
    key_data = f"{proj.get('name','')}{proj.get('blurb','')}{proj.get('image_full','')}"
    return hashlib.md5(key_data.encode()).hexdigest()


def _to_ts(v):
    """ISO 字符串或数字 → UTC 时间戳；无法解析返回 None"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def apply_ended_states(projects: list) -> int:
    """最终兜底：deadline 已过且仍标 live/active 的项目 → 标记 state=ended。
    必须在 merge 用原始 API 状态覆盖 state 之后调用（否则会被覆盖回 live）。
    返回标记数量。保留全部字段，追加 ended_at。
    """
    now = datetime.utcnow().timestamp()
    n = 0
    for p in projects:
        if p.get("state") not in ("live", "active"):
            continue
        dl = _to_ts(p.get("deadline"))
        if dl is None or dl >= now:
            continue
        p["state"] = "ended"
        p["ended_at"] = datetime.utcnow().isoformat() + "Z"
        n += 1
    return n

def main():
    print("=" * 60)
    print("Merging KS + IG data → projects.json")
    print("=" * 60)

    # Load raw data
    ks_file = RAW_DIR / "kickstarter.json"
    ig_file = RAW_DIR / "indiegogo.json"

    ks_data = json.loads(open(ks_file, encoding="utf-8").read()).get("projects", []) if ks_file.exists() else []
    ig_data = json.loads(open(ig_file, encoding="utf-8").read()).get("projects", []) if ig_file.exists() else []

    print(f"KS: {len(ks_data)} projects")
    print(f"IG: {len(ig_data)} projects")

    # Load existing projects if any
    existing = {}
    if OUTPUT.exists():
        old_data = load_json_safe(OUTPUT)  # 损坏自动回退 .bak
        for p in old_data.get("projects", []):
            existing[p["id"]] = p
        print(f"Existing: {len(existing)} projects in previous projects.json")

    # Merge
    all_new = ks_data + ig_data

    # LLM hardware filter: classify ALL fresh API projects before merge
    print(f"Running AI hardware filter on {len(all_new)} projects...")
    hw_skipped = 0
    for p in all_new:
        hw = classify_hardware(p.get("name", ""), p.get("blurb", ""))
        p["hardware_class"] = hw
        if hw == "non-hardware":
            hw_skipped += 1
    if hw_skipped:
        print(f"  🚫 {hw_skipped} non-hardware projects skipped")
    else:
        print(f"  ✅ All projects classified as hardware")

    merged = {}
    new_count = 0
    updated_count = 0
    content_updated = 0

    for p in all_new:
        pid = p["id"]
        # Skip non-hardware projects entirely
        if p.get("hardware_class") == "non-hardware":
            if pid in existing:
                # Also remove from existing so it doesn't come back via historical step
                del existing[pid]
            continue
        p["topnice_category"] = normalize_category(p)
        p["content_hash"] = content_hash(p)

        if pid not in existing:
            # New project
            p["first_seen"] = datetime.utcnow().isoformat() + "Z"
            p["needs_translation"] = True
            merged[pid] = p
            new_count += 1
        else:
            # Existing project — update dynamic fields only
            old = existing[pid]
            old["pledged"] = p["pledged"]
            old["goal"] = p["goal"]
            old["backers_count"] = p["backers_count"]
            old["percent_funded"] = p["percent_funded"]
            old["state"] = p["state"]
            old["deadline"] = p["deadline"]
            old["staff_pick"] = p.get("staff_pick", False)
            old["score"] = p.get("score", old.get("score", 0))

            # Check if static content changed (hash mismatch)
            if content_hash(p) != old.get("content_hash", ""):
                old["name"] = p["name"]
                old["blurb"] = p["blurb"]
                old["image_full"] = p["image_full"]
                old["image_med"] = p["image_med"]
                old["image_thumb"] = p["image_thumb"]
                old["image_1024x576"] = p["image_1024x576"]
                old["needs_translation"] = True
                old["content_hash"] = content_hash(p)
                content_updated += 1
            else:
                updated_count += 1

            merged[pid] = old

    # Also keep projects that are no longer live (historical data), but skip non-hardware
    for pid, old_p in existing.items():
        if pid not in merged and old_p.get("hardware_class") != "non-hardware":
            merged[pid] = old_p

    # Convert merged dict back to list
    projects_list = list(merged.values())

    # Step: Initialize history & append daily snapshot
    snap_stats = batch_append(projects_list)
    print(f"  History: {snap_stats['initialized']} initialized, {snap_stats['appended']} appended")

    # Step: Compute scores
    projects_list = batch_compute(projects_list)
    print(f"  Scores computed for {sum(1 for p in projects_list if p.get('score'))} projects")

    # Sort by score descending
    projects_list.sort(key=lambda x: x.get("score", 0), reverse=True)

    # 最终兜底：标记已过期（deadline 已过但仍标 live）的项目为 ended
    ended_count = apply_ended_states(projects_list)
    if ended_count:
        print(f"  🏁 标记 {ended_count} 个过期项目为 ended（归档保留）")

    # Compute stats for summary
    total_raised = sum(p["pledged"] for p in projects_list)
    total_backers = sum(p["backers_count"] for p in projects_list)
    live_count = sum(1 for p in projects_list if p.get("state") == "live")

    out = {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "stats": {
            "total_projects": len(projects_list),
            "live_projects": live_count,
            "total_raised": total_raised,
            "total_backers": total_backers,
        },
        "projects": projects_list,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUTPUT, out)  # 原子写：崩溃不损坏，写前自动备份 .bak

    print(f"\n✅ Merge complete:")
    print(f"  New projects: {new_count}")
    print(f"  Updated (data only): {updated_count}")
    print(f"  Content changed (re-translate needed): {content_updated}")
    print(f"  Total in projects.json: {len(projects_list)}")
    print(f"  Saved to: {OUTPUT}")

if __name__ == "__main__":
    main()
