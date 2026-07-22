#!/usr/bin/env python3
"""Apply blacklist_slugs.json to projects.json: remove every blacklisted slug.

Idempotent: slugs already absent are skipped. Preserves all other projects
(including any newly fetched legit hardware from later CI runs), so this is
safe to run against the latest remote data after a merge.

Usage:
    python scripts/apply_blacklist.py            # dry-run
    python scripts/apply_blacklist.py --apply    # actually remove + write
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLACKLIST = ROOT / "scripts" / "blacklist_slugs.json"
PROJECTS = ROOT / "src" / "data" / "projects.json"


def load_blacklist():
    data = json.loads(BLACKLIST.read_text(encoding="utf-8"))
    slugs = set(data.get("slugs", []))
    return slugs, data.get("count", len(slugs))


def main():
    apply = "--apply" in sys.argv
    bl, bl_count = load_blacklist()
    doc = json.loads(PROJECTS.read_text(encoding="utf-8"))
    projects = doc.get("projects", [])

    before = len(projects)
    removed = [p["slug"] for p in projects if p.get("slug") in bl]
    kept = [p for p in projects if p.get("slug") not in bl]
    after = len(kept)

    print(f"blacklist slugs : {bl_count}")
    print(f"projects before : {before}")
    print(f"to remove       : {len(removed)}")
    print(f"projects after  : {after}")

    if not apply:
        print("\n[DRY-RUN] would remove the following slugs:")
        for s in removed:
            print(f"  - {s}")
        print("\n(use --apply to actually write)")
        return

    # backup
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = PROJECTS.with_suffix(f".json.bak-{ts}")
    shutil.copy(PROJECTS, bak)
    print(f"\nbackup -> {bak.name}")

    doc["projects"] = kept
    PROJECTS.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written: {after} projects ({before - after} removed)")


if __name__ == "__main__":
    main()
