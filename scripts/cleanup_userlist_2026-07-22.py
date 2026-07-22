#!/usr/bin/env python3
"""精准删除用户提交清单(2026-07-22)中的非硬件 slug。

逻辑：
- 解析 scripts/tmp_del_raw_2026-07-22.txt 拿到 266 个候选 slug
- 排除 KEEP 集合（用户确认保留 + 本轮 LLM 复读保留 = 40 个）
- 排除不在 projects.json 的 slug（已删/黑名单，跳过）
- 其余从 projects.json 删除，并合并进 blacklist_slugs.json
- 先备份 projects.json（.bak），--apply 才真写
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "scripts" / "tmp_del_raw_2026-07-22.txt"
PROJ = BASE / "src" / "data" / "projects.json"
BL = BASE / "scripts" / "blacklist_slugs.json"

# 用户确认保留（28 强 + 6 边界 + aironox）+ 本轮 LLM 复读保留（5）
KEEP = {
    # 28 强信号保留（真电子/智能硬件）
    "aiscan-o1-3d-gaussian-all-in-one-3d-scanner",
    "kare-3d-desktop-metal-3d-printer",
    "lini-your-everywhere-open-source-mini-computer-0",
    "volatco",
    "memoir-a-paper-like-e-ink-digital-frame",
    "hamu-high-accuracy-measurement-unit",
    "advanced-fishing-lure",
    "autofill-resin-management-system-for-3d-printers",
    "blackbird-coffee-gear-coffee-canister-and-vacuum-pump-0",
    "blast-air",
    "campcore--light-up-every-adventure",
    "cladist-titan-15-1-torque-redefines-power-and-precision",
    "compact-size-massive-power-1367mm-pocket-friendly-design",
    "dadbodd",
    "hunt-h2-this-tiny-flashlight-has-a-battery-swap-station",
    "jetro-keep-freshness-longer",
    "kovadex-x1-your-100w-rgb-desktop-hub-with-dual-monitor-arm",
    "luminyx-nfs-1-shadow-fighting-safety-eyewear",
    "mi2-window-fan",
    "nevilo-smart-cooler-travel-anywhere-with-insulin-freedom",
    "oncobag",
    "p10-elite-pss-compatible-taekwondo-foot-protector",
    "pfm",
    "swiftbuild",
    "tankogo-the-portable-propane-free-heated-shower-tank",
    "titaner-tiverse-the-infinite-modular-titanium-belt-buckle",
    "uknight-a-pixel-lantern-speaker-for-your-desk",
    "xatrix",
    # 6 边界保留
    "light-up-morale-patch-18-day-dual-color-velcro-badge",
    "verolite-the-modular-titanium-pocket-repair-system-pen",
    "drill-turbine",
    "securidoor",
    "fitn-focus-0",
    "yinyang-shades-adjustable-cyberpunk-sunglasses-0",
    # aironox（低置信保留，用户二次确认）
    "aironox-go-wrinkle-free-clothes-wherever-you-land",
    # 本轮 LLM 复读保留（9 选 5）
    "pitata-prometheus-signed-card-frame-and-master-acaan",
    "aranya-building-our-first-functional-prototype",
    "lovers-pack-cinematic-3d-lenticular-motion-art-set",
    "m3-magnetic-mechanical-masterpiece",
    "fat-iron-core",
}

# 已知不在库（早删/黑名单/slug 不符），直接跳过
KNOWN_MISSING = {
    "provoqué-modular-watch-cut-from-real-cds",
    "skyhy-ink-mobile-tattoo-studio-in-an-ambulance",
    "the-hidden-gem",
}


def parse_slugs(path):
    slugs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        m = re.match(r"^- (?P<slug>\S+?)\s*\|", line)
        if m:
            slugs.append(m.group("slug").strip())
    return slugs


def main(apply=False):
    raw_slugs = parse_slugs(RAW)
    print(f"解析删除清单: {len(raw_slugs)} 条")

    data = json.loads(PROJ.read_text(encoding="utf-8"))
    projects = data.get("projects", [])
    in_lib = {p.get("slug") for p in projects}
    print(f"projects.json 当前: {len(projects)} 项")

    to_delete = []
    skipped_keep = []
    skipped_missing = []
    for s in raw_slugs:
        if s in KEEP:
            skipped_keep.append(s)
            continue
        if s not in in_lib:
            skipped_missing.append(s)
            continue
        to_delete.append(s)

    print(f"→ 保留跳过 (KEEP): {len(skipped_keep)}")
    print(f"→ 不在库跳过: {len(skipped_missing)}")
    print(f"→ 待删除: {len(to_delete)}")
    print(f"预计 projects.json: {len(projects)} → {len(projects) - len(to_delete)}")

    if not apply:
        print("\n[DRY-RUN] 未写入。加 --apply 执行。")
        for s in to_delete:
            print("  DELETE", s)
        return

    # 备份
    bak = PROJ.with_suffix(".json.bak")
    shutil.copy2(PROJ, bak)
    print(f"\n备份 → {bak}")

    # 删除
    kept = [p for p in projects if p.get("slug") not in set(to_delete)]
    data["projects"] = kept
    PROJ.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写入 projects.json: {len(projects)} → {len(kept)} (删 {len(to_delete)})")

    # 合并黑名单
    if BL.exists():
        blob = json.loads(BL.read_text(encoding="utf-8"))
        existing = set(blob.get("slugs", []))
    else:
        blob = {"slugs": []}
        existing = set()
    merged = sorted(existing | set(to_delete))
    blob["slugs"] = merged
    blob["updated_at"] = datetime.utcnow().isoformat() + "Z"
    blob["note"] = "merged from user deletion list 2026-07-22 cleanup"
    BL.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"黑名单: {len(existing)} → {len(merged)} (新增 {len(set(to_delete) - existing)})")


if __name__ == "__main__":
    import sys
    main(apply="--apply" in sys.argv)
