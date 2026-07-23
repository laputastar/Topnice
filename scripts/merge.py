#!/usr/bin/env python3
"""Merge KS + IG data into unified projects.json with deduplication, history, and scoring."""
import json, hashlib, os, re
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

# 统一 LLM/API 调用层（集中读 env、统一重试/超时）
from llm import call_cloudflare, CF_MODEL

# 分类专用模型（默认沿用 CF 翻译模型 qwen3-30b；如需更强可设 CF_CLASSIFY_MODEL 覆盖）
CLASSIFY_MODEL = os.environ.get("CF_CLASSIFY_MODEL", CF_MODEL)

from scripts.snapshot import batch_append
from scripts.score import batch_compute
from safeio import atomic_write_json, load_json_safe

RAW_DIR = Path(__file__).parent / "raw"
OUTPUT = Path(__file__).parent.parent / "src" / "data" / "projects.json"

def batch_hardware_classify(projects: list, batch_size: int = 50) -> list:
    """使用 Cloudflare Workers AI 批量分类硬件/非硬件项目（替代旧的逐个分类）。

    分批传入 name + tagline + category，Each 50 项一批避免上下文超限。
    每项写入 hardware_class / hw_type / hw_reason 字段。
    LLM 不可用时兜底标记为 hardware（safe default）。
    """
    if not projects:
        return projects

    classified = []
    total = len(projects)
    skipped = 0
    n_batches = (total + batch_size - 1) // batch_size

    for batch_idx in range(n_batches):
        batch = projects[batch_idx * batch_size:(batch_idx + 1) * batch_size]

        # 精简字段省 token
        products = []
        for p in batch:
            products.append({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "tagline": (p.get("blurb") or p.get("tagline") or "")[:300],
                "description": (p.get("story") or "")[:600],
                "category": p.get("parent_category") or p.get("category") or "",
            })

        prompt = f"""You are a crowdfunding product classifier. Classify each product as hardware (keep) or non-hardware (delete).
TopNice ONLY curates TECH / ELECTRONIC / SMART hardware. Strict bias: when in doubt, DELETE.

DEFINITION OF HARDWARE (KEEP) — product must contain at least one clear electronic/intelligent signal:
- electronic components / circuit board / chip / IC / PCB / soldered electronics
- battery or rechargeable power as a CORE function (not just a decorative LED)
- motor / brushless motor / actuator / pump / electrically-driven moving mechanism
- sensor / camera module / microphone / display / screen / e-ink / touch panel
- wireless module: WiFi / Bluetooth / NFC / RFID / Zigbee / UWB
- computing unit: MCU / Arduino / Raspberry Pi / local AI chip / app-controlled logic
- actively-controlled heating/cooling element (graphene heating, Peltier, thermoelectric)
- smart / APP-connected function that is the PRIMARY purpose of the product

KEEP examples (verified real hardware from audit):
1. AI hardware: AI chip, local AI terminal, AI camera/speaker/vision/robot/controller
2. Smart IoT: WiFi/BT/IoT devices, drones, 3D printers, smart home, digital A/V, charging/power
3. Wearables: smartwatch, smart glasses, smart earbuds, health monitors, VR/AR, wearable sensors
4. Consumer electronics: cameras/lenses, audio gear, computer peripherals, storage, displays, maker/workshop electronics kits, solar chargers WITH circuits, ferrofluid music visualizers with mic, Arduino/Pi kits
5. Electrified tools/vehicles: brushless foam-dart blaster, motorized window fan, e-bike/scooter motor accessories, electronic/Bluetooth percussion (smart drum)
6. Smart apparel/accessories: heated shoes/vest (battery-powered), smart glasses with display, NFC-equipped gear

DELETE (non-hardware) — pure physical / service / digital with NONE of the electronic signals above:
1. Food, beverage, coffee gear, kitchenware, food containers, cookware (no circuit/chip)
2. Apparel, footwear, bags, jewelry, watches that are purely mechanical/analog with no smart module
3. Home/furniture/decor, storage, cable organizers (purely physical, no electronics)
4. Books, comics, biographies, films/TV series, music albums, VST plugins (pure software), digital downloads (STL files, e-books)
5. Pure toys/board games/card games/puzzles/figurines/blind boxes/mechanical fidget toys (no circuit)
6. App/software/cloud service with NO physical hardware; pure digital membership
7. Services & personal fundraising: bar/restaurant space, farm experience, individual "help me upgrade" campaigns, racing/arcade VENUE + app (no product shipped)
8. Pure mechanical EDC / precision tools with NO electronics: titanium/steel knives, multitools, screwdrivers, ratchets, sharpeners, outdoor cooking tools, flip tools, mechanical pen (DELETE even if CNC/titanium-forged/precision-engineered)
9. Cosmetics, skincare, manual beauty tools, pet supplies (no smart module)
10. Courses, workshops, fitness coaching (no hardware shipped)

CATEGORY RED FLAGS — default DELETE unless the description clearly shows an electronic signal above:
Product Design, Ready-to-wear, Footwear, Performance Art, Interactive Design, Toys (pure toys), Sound (audio software), 3D Printing (pure STL), DIY (pure handcraft no circuit), Gadgets (pure accessory), and EMPTY/missing category with no electronic descriptor.

BOUNDARY RULES:
1. Product has electronic body + ordinary accessories → KEEP (body is hardware)
2. Only minor electronic accessory, main body is clothing/furniture/craft → DELETE
3. Pure digital / app / cloud / membership, no physical hardware → DELETE
4. Prototype: clear mass-production electronic hardware → KEEP; pure design concept, no circuit → DELETE
5. EDC/precision tools: KEEP ONLY IF they contain electronics/motor/battery/smart module. Pure mechanical tools (knife/screwdriver/ratchet/sharpener/cooking tool/flip tool/fidget pen) → DELETE even if titanium/CNC/precision-engineered.

Output ONLY a JSON array. Each entry:
{{"id": "product id", "keep": true/false, "product_type": "智能硬件/含电子硬件/可穿戴硬件/纯机械工具/纯软件/服务众筹/数字下载/服饰鞋包/食品厨具/书籍影视/其他非硬件", "reason": "short reason"}}

Products:
{json.dumps(products, ensure_ascii=False, indent=2)}"""

        try:
            raw = call_cloudflare(
                prompt,
                model=CLASSIFY_MODEL,
                system="You are a product classifier. Output only valid JSON arrays.",
                temperature=0,
                max_tokens=4000,
                timeout=120,
                max_retries=1,
                backoff=3,
            )
            m = re.search(r'\[.*\]', raw, flags=re.DOTALL)
            if not m:
                raise ValueError("No JSON array in LLM response")
            classifications = json.loads(m.group())
            for i, cls in enumerate(classifications):
                if i < len(batch):
                    keep = cls.get("keep", True)
                    batch[i]["hardware_class"] = "hardware" if keep else "non-hardware"
                    batch[i]["hw_type"] = cls.get("product_type", "")
                    batch[i]["hw_reason"] = cls.get("reason", "")
                    if not keep:
                        skipped += 1
        except Exception as e:
            print(f"  ⚠️ 批次 {batch_idx + 1}/{n_batches} LLM 分类失败: {e}")
            for p in batch:
                p["hardware_class"] = "hardware"

        # 失败护栏：本批次删除率过高（>40%）视为模型异常，整批默认保留，
        # 杜绝静默砍掉 90% 数据（参考 2026-07-20 的 635→58 事故）。
        _non = sum(1 for p in batch if p.get("hardware_class") == "non-hardware")
        if batch and _non / len(batch) > 0.4:
            print(f"  🛡️ 护栏触发：本批 {_non}/{len(batch)} 被判删除(>{40}%) → 视为异常，整批改判保留")
            for p in batch:
                p["hardware_class"] = "hardware"
                if not p.get("hw_type"):
                    p["hw_type"] = "硬件(护栏兜底)"
                if not p.get("hw_reason"):
                    p["hw_reason"] = "删除率超阈值，护栏兜底保留"

        classified.extend(batch)
        print(f"  ✓ 批次 {batch_idx + 1}/{n_batches}: {len(batch)} 项")

    print(f"  🚫 {skipped} non-hardware projects skipped ({total - skipped} hardware kept)")
    return classified

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

    # ⚠️ 增量分类（用户规则：除非显式要求整体重筛，否则只对【新增】产品
    #    分类/删除；已入库项目沿用历史 hardware_class，绝不重新筛选或删除）。
    new_projects = [p for p in all_new if p["id"] not in existing]
    existing_raw = [p for p in all_new if p["id"] in existing]
    print(f"  · 新增待分类: {len(new_projects)} | 已入库(跳过分类、沿用历史): {len(existing_raw)}")
    if new_projects:
        new_projects = batch_hardware_classify(new_projects)
    # 已入库项目：沿用其在 projects.json 中的历史分类结果（不重新判定）
    for p in existing_raw:
        old = existing[p["id"]]
        p["hardware_class"] = old.get("hardware_class", "hardware")
        p["hw_type"] = old.get("hw_type", "")
        p["hw_reason"] = old.get("hw_reason", "")
    all_new = new_projects + existing_raw

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

            # Watchlist refresh = variables only; NEVER re-translate content
            # (prevents wasting tokens re-translating already-translated pages)
            if "watchlist" in (p.get("source") or ""):
                updated_count += 1
            elif content_hash(p) != old.get("content_hash", ""):
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

    # ── Final classification pass (enforces "classify → delete BEFORE extract") ──
    # The classify above only covers freshly-fetched `all_new`. Existing projects that
    # lost hw_type (e.g. LLM was down during a prior merge, or the field was never
    # persisted) would stay unclassified and slip through. Re-classify ANY project
    # still missing hw_type so the output is always fully filtered. LLM-unavailable
    # batches fall back to hardware (kept) without hw_type and will be retried next run.
    unclassified = [p for p in projects_list if not p.get("hw_type")]
    if unclassified:
        print(f"Re-classifying {len(unclassified)} projects lacking hw_type...")
        re_cls = batch_hardware_classify(unclassified)
        by_id = {p["id"]: p for p in re_cls}
        for p in projects_list:
            if p["id"] in by_id:
                src = by_id[p["id"]]
                p["hw_type"] = src.get("hw_type", p.get("hw_type"))
                p["hw_reason"] = src.get("hw_reason", p.get("hw_reason"))
                p["hardware_class"] = src.get("hardware_class", p.get("hardware_class"))

    # Global safety net: drop any non-hardware that slipped through (incl. from above).
    before = len(projects_list)
    deleted = [p for p in projects_list if p.get("hardware_class") == "non-hardware"]
    projects_list = [p for p in projects_list if p.get("hardware_class") != "non-hardware"]
    removed = before - len(projects_list)
    if removed:
        print(f"  🗑️  Deleted {removed} non-hardware project(s) after classification")
        # Audit manifest — write what was deleted so a wrong deletion is recoverable.
        manifest = {
            "deleted_at": datetime.utcnow().isoformat() + "Z",
            "reason": "classified non-hardware by batch_hardware_classify (terminal pass)",
            "count": removed,
            "items": [
                {
                    "id": p.get("id"),
                    "slug": p.get("slug"),
                    "name": p.get("name"),
                    "platform": p.get("platform"),
                    "hw_type": p.get("hw_type"),
                    "hw_reason": p.get("hw_reason"),
                }
                for p in deleted
            ],
        }
        try:
            import os
            raw_dir = Path(__file__).parent / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            mpath = raw_dir / f"deleted_non_hardware_{datetime.utcnow().strftime('%Y%m%d')}.json"
            # Append to today's manifest if it exists (multiple runs per day)
            existing_manifest = []
            if mpath.exists():
                try:
                    existing_manifest = json.loads(mpath.read_text(encoding="utf-8")).get("items", [])
                except Exception:
                    existing_manifest = []
            all_items = existing_manifest + manifest["items"]
            mpath.write_text(
                json.dumps({"deleted_at": manifest["deleted_at"], "count": len(all_items), "items": all_items},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  📝  Deletion manifest written: {mpath}")
        except Exception as e:
            print(f"  ⚠️  Failed to write deletion manifest: {e}")

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

    # NOTE: We intentionally do NOT write a static "stats" object into projects.json.
    # Counts (total / live / raised / backers) are now derived at build time from the
    # project array in src/data/projects.ts, so they can never drift out of sync
    # when projects are added/removed outside of this script (e.g. classify deletions).
    out = {
        "updated_at": datetime.utcnow().isoformat() + "Z",
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
