#!/usr/bin/env python3
"""One-off: remove manually audit-confirmed non-hardware slugs from projects.json.

Round 1 (already applied): strong-signal 41 deleted, ai-djembe-go kept.
Round 2 (this): high/low confidence sets — keep the user-listed slugs,
delete everything else in those two sections.

Safety:
- Dry-run by default (prints plan, makes NO changes).
- On --apply: backs up projects.json -> .bak first, then removes matches.
- Merges with existing blacklist_slugs.json so fetch scripts skip them later.
"""
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent  # topnice/
AUDIT = Path(r"C:\Users\LuckyF\WorkBuddy\2026-06-04-11-02-53\audit-non-hardware-2026-07-22.md")
PROJECTS = ROOT / "src" / "data" / "projects.json"
BLACKLIST = ROOT / "scripts" / "blacklist_slugs.json"

# Round 1 keep (already applied; listed for idempotency / clarity)
KEEP_STRONG = {"ai-djembe-go-smart-rhythm-training-for-brain-and-motor-skill"}

# Round 2 keeps (user-confirmed, 2026-07-22)
KEEP_HIGH = {
    "the-3-in-1-book-light",
    "washwow-p1-electrolyzed-water-generating-pet-paw-cleaner",
    "ear-bus-the-first-ai-translator-for-dog-barks-and-emotions",
    "creator1-turn-your-kids-words-into-real-stickers",
    "vintter-mug-warmer-and-sanitizer",
    "meowetrics-stress-free-health-monitoring-for-your-cat",
}
KEEP_LOW = {
    "aironox-go-wrinkle-free-clothes-wherever-you-land",
    "lumysi-the-luxury-fitness-bracelet",
    "keep-the-connected-keychain-that-keeps-your-people-close",
    "glass-air-fryer-with-ceramic-coating-and-steam-function",
}


def parse_section(audit_text, start_marker, end_marker=None, tag="高"):
    if end_marker:
        pat = re.escape(start_marker) + r".*?(?=" + re.escape(end_marker) + r")"
    else:
        pat = re.escape(start_marker) + r".*"
    m = re.search(pat, audit_text, re.DOTALL)
    if not m:
        raise RuntimeError(f"Could not find {start_marker} in audit file")
    sec = m.group(0)
    return re.findall(rf"\[{tag}\]\s*`([^`]+)`", sec)


def main():
    apply = "--apply" in sys.argv
    print(f"MODE: {'APPLY' if apply else 'DRY-RUN (no changes)'}")

    audit_text = AUDIT.read_text(encoding="utf-8")

    # Round 2: process high + low only (strong already deleted in round 1)
    high = parse_section(audit_text, "## 二", "## 三", "高")
    low = parse_section(audit_text, "## 三", None, "低")

    print(f"High slugs parsed: {len(high)}")
    print(f"Low slugs parsed: {len(low)}")

    del_high = [s for s in high if s not in KEEP_HIGH]
    del_low = [s for s in low if s not in KEEP_LOW]

    print(f"\nKEEP high ({len(KEEP_HIGH)}):")
    for s in sorted(KEEP_HIGH):
        print(f"   + {s}")
    print(f"KEEP low ({len(KEEP_LOW)}):")
    for s in sorted(KEEP_LOW):
        print(f"   + {s}")
    print(f"\nDELETE high: {len(del_high)}")
    for s in del_high:
        print(f"   - {s}")
    print(f"DELETE low: {len(del_low)}")
    for s in del_low:
        print(f"   - {s}")

    data = json.loads(PROJECTS.read_text(encoding="utf-8"))
    projects = data["projects"]
    print(f"\nProjects in projects.json BEFORE: {len(projects)}")

    del_slugs = set(del_high) | set(del_low)
    matched = [p for p in projects if p.get("slug") in del_slugs]
    missing = [s for s in del_slugs if not any(p.get("slug") == s for p in projects)]
    print(f"Matched for deletion: {len(matched)}")
    if missing:
        print(f"  ⚠️ NOT found (already absent?): {missing}")

    # Verify keeps are present
    for k in sorted(KEEP_HIGH | KEEP_LOW):
        present = any(p.get("slug") == k for p in projects)
        flag = "✅" if present else "⚠️ MISSING"
        print(f"  KEEP present {k}: {flag}")

    if not apply:
        print("\n[DRY-RUN] No files modified. Re-run with --apply to execute.")
        return

    bak = PROJECTS.with_suffix(".json.bak")
    shutil.copy2(PROJECTS, bak)
    print(f"\n💾 Backup: {bak}")

    remaining = [p for p in projects if p.get("slug") not in del_slugs]
    data["projects"] = remaining
    PROJECTS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ Projects AFTER: {len(remaining)} (removed {len(projects) - len(remaining)})")

    # Merge with existing blacklist (cumulative)
    existing = set()
    if BLACKLIST.exists():
        try:
            existing = set(json.loads(BLACKLIST.read_text(encoding="utf-8")).get("slugs", []))
        except Exception:
            pass
    all_slugs = existing | del_slugs
    bl = {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "note": "Manual audit-confirmed non-hardware slugs (strong + high/low rounds, 2026-07-22). Fetch scripts should skip these to prevent re-ingestion.",
        "slugs": sorted(all_slugs),
    }
    BLACKLIST.write_text(json.dumps(bl, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📝 Blacklist written: {BLACKLIST} ({len(all_slugs)} slugs total)")


if __name__ == "__main__":
    main()
