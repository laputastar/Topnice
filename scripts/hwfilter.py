#!/usr/bin/env python3
"""
hwfilter.py — 「非硬件」终判过滤器（2026-09-10 方案 C）

背景
----
merge.py 原先用精确集合匹配做非硬件过滤：

    NON_HARDWARE_TYPES = {"纯软件", "服务众筹", "书籍影视", ...}
    if (p.get("hw_type") or "").strip() in NON_HARDWARE_TYPES: delete

但 LLM 实际输出的 `hw_type` 大量 **off-enum**（枚举外值）：
    "纯软件/服务众筹"（带斜杠）、"玩具"、"宠物用品"、"家居用品"、"游戏"、
    "艺术"、"影视/数字下载"、"Art"、"Film & Video" ...
精确匹配恒不命中 → **42 个「模型已判非硬件」的项目长期滞留线上**（2026-09-10 审计）。

改为包含匹配后必须配豁免，否则会误删真硬件。实测（候选 42 项）：
  - 裸删：误删 4 个真硬件（patience-for-eurorack / k101 / seivoid / purifi）
  - 用 gate.ELECTRONIC_RE 豁免：反而更差——`\\bai\\b`/`display`/`screen` 太泛，
    7 个垃圾项被误豁免，而真正该救的 eurorack 因词表无 voltage/HP 没救到（净漏删 2→9）
  - 本模块（硬电子词收紧豁免）：救回 4 个真硬件 + 1 个磁力骰子误救，**0 误删**

⚠️ 误删代价被放大：删除项会同步写入 blacklist_slugs.json 防回抓 → **误删 = 永久损失**。
   故本模块严守「宁漏勿错」：任一步不确定即返回 False（保留）。

判定顺序（短路，越靠前越优先）
------------------------------
1. hw_type 为空 → 保留（无信息不判）
2. 命中白名单（硬件/电子/可穿戴/electrified/electronics/wearable）→ 保留
   —— 防未来出现「游戏硬件」「玩具硬件」这类标签被误杀
3. 未命中非硬件关键词 → 保留
4. 命中硬电子词 → 保留（豁免）
5. 以上都通过 → 删除
"""
import json
import re

# ─────────────────────────────────────────────────────────────────────────────
# 1) 非硬件关键词：中文用子串（无词边界概念），英文用 \b 词边界
#    （避免 smart→art、hardware→ware 之类误命中）
# ─────────────────────────────────────────────────────────────────────────────
NON_HARDWARE_RE = re.compile(
    r"""(?x)
      # 中文（LLM 输出的主力枚举，含带斜杠的 off-enum 变体）
      纯软件 | 服务众筹 | 服务 | 数字下载 | 服饰 | 鞋包 | 食品 | 厨具 | 书籍 |
      影视 | 玩具 | 宠物用品 | 家居用品 | 游戏 | 艺术 | 非硬件 | 化妆品 |
      # 英文（LLM 偶发输出英文标签）
      \bfilm\b | \bvideo\b | \bart\b | \btoy\b | \bgames?\b | \bapparel\b |
      \bfood\b | \bbook\b | \bcosmetics?\b | \bservices?\b | \bsoftware\b |
      \bdigital\b | \bdownload\b | \bnon-?hardware\b | \bstl\b | \bcourses?\b
    """,
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# 2) 白名单：hw_type 含这些词，一律视为硬件（优先级高于非硬件关键词）
# ─────────────────────────────────────────────────────────────────────────────
HARDWARE_WHITELIST = (
    "硬件", "电子", "可穿戴",          # 智能硬件 / AI硬件 / 含电子硬件 / 科技电子
    "electrified", "electronics", "wearable",
)

# ─────────────────────────────────────────────────────────────────────────────
# 3) 硬电子信号豁免：只收「确定性强的硬件词」。
#    ⚠️ 刻意排除 ai / display / screen / smart / audio / connected 等泛词——
#       实测用 gate.ELECTRONIC_RE（含这些泛词）会把 STL 文件包、AI 故事平台、
#       订阅盒子等 7 个垃圾项误豁免，净效果比不做豁免更差。
# ─────────────────────────────────────────────────────────────────────────────
RESCUE_ELECTRONIC_RE = re.compile(
    r"""(?x)
    \b(
        usb-?c | usb\s?type-?c | bluetooth | firmware | pcb | circuit-?board |
        eurorack | voltage | \bhp\b | battery | batteries | motor | brushless |
        # "magnetic circuit" = 磁路（纯机械，如 MagDice 磁力骰子），用后视断言排除
        sensor | (?<!magnetic\s)circuit | mcu | raspberry | arduino | esp32 | esp8266 |
        wi-?fi | nfc | rfid | zigbee | e-?ink | touch-?screen | rechargeable |
        cpu | gpu | peltier | thermoelectric | heater | heating-?element |
        relay | solenoid | servo | oscillator | synth | amplifier | dac | adc | amp
    )\b
    """,
    re.IGNORECASE | re.ASCII,
)


def _rescue_text(project: dict) -> str:
    """拼接待检文本（小写）。抽取阶段 ai_* 可能尚未生成，故两类字段都取。"""
    parts = [
        project.get("name") or "",
        project.get("blurb") or project.get("tagline") or "",
        project.get("story") or project.get("description") or project.get("about") or "",
        project.get("ai_intro_en") or "",
    ]
    for field in ("ai_highlights_en", "ai_specs_en", "ai_tiers", "ai_risks_en"):
        value = project.get(field)
        if value:
            parts.append(json.dumps(value, ensure_ascii=False))
    return " ".join(parts).lower()


# ─────────────────────────────────────────────────────────────────────────────
# 4) 人工豁免（slug 级）：确定性规则判不了、但人工复核确认真是硬件产品的边界项。
#    每条必须注明理由，便于日后复查/清理。删除会同步写 blacklist → 误删永久，故宁可多留。
# ─────────────────────────────────────────────────────────────────────────────
MANUAL_KEEP_SLUGS = {
    # 2026-09-10: LLM 判「Card grading tool without hardware」，但项目是已量产的实体设备
    # （"Already in production, 502 units sold in 90 days"），且为当批最高分(49)。
    # 无证据表明它是纯软件/服务 → 按宁漏勿错保留，待人工复核。
    "holoscope-flawfinder-because-everyones-a-critic",
}


def is_non_hardware(project: dict) -> bool:
    """终判：该项目是否应作为非硬件删除。返回 True = 删。

    宁漏勿错：任一步信息不足或不确定 → 返回 False（保留）。
    仅依据 hw_type 与项目文本，不调用任何 LLM/API，结果稳定可复现。
    """
    if (project.get("slug") or "") in MANUAL_KEEP_SLUGS:
        return False                                    # ⓪ 人工豁免 → 保留
    hw_type = (project.get("hw_type") or "").strip()
    if not hw_type:
        return False                                    # ① 无分类信息 → 保留
    if any(k in hw_type for k in HARDWARE_WHITELIST):
        return False                                    # ② 白名单 → 保留
    if not NON_HARDWARE_RE.search(hw_type):
        return False                                    # ③ 非硬件关键词未命中 → 保留
    if RESCUE_ELECTRONIC_RE.search(_rescue_text(project)):
        return False                                    # ④ 硬电子词豁免 → 保留
    return True                                         # ⑤ 删除


def is_kept(project: dict) -> bool:
    """配合 hardware_class 的完整保留判定（merge.py 两处删除点共用）。"""
    if project.get("hardware_class") == "non-hardware":
        return False
    return not is_non_hardware(project)


# ─────────────────────────────────────────────────────────────────────────────
# 自测：覆盖 2026-09-10 审计中的真实样本（含 4 个「易被误删的真硬件」）
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cases = [
        # ── 应删除（True）──
        (True,  {"hw_type": "纯软件/服务众筹", "name": "Projet BTU",
                 "ai_intro_en": "Uses waste server heat to heat community buildings."}),
        (True,  {"hw_type": "纯软件/服务众筹", "name": "Fantasy Legends: 100 STL Collection",
                 "ai_specs_en": [["File format", "STL"], ["Digital download", "Yes"]]}),
        (True,  {"hw_type": "玩具", "name": "MagDice: 7-in-1 Titanium Magnetic Dice",
                 "ai_specs_en": [["Mechanism", "Hidden transient magnetic circuit system"]]}),
        (True,  {"hw_type": "玩具", "name": "howCat 3D Wooden Puzzle",
                 "ai_intro_en": "A lever-linkage wooden model, no electronics."}),
        (True,  {"hw_type": "宠物用品", "name": "Mr.Catman: DoubleDecker Litter Boxes"}),
        (True,  {"hw_type": "家居用品", "name": "Realign Pillow", "ai_intro_en": "Memory foam pillow."}),
        (True,  {"hw_type": "艺术", "name": "Logic & Linen: Woven Art Cotton Throw Blanket"}),
        (True,  {"hw_type": "Film & Video", "name": "My Intelligence"}),
        (True,  {"hw_type": "Art", "name": "A New Era of Football Memorabilia"}),
        (True,  {"hw_type": "影视/数字下载", "name": "The Perfect Sisters"}),

        # ── 应保留（False）：硬件 ──
        (False, {"hw_type": "智能硬件", "name": "Some Smart Watch"}),
        (False, {"hw_type": "AI硬件", "name": "AI Camera"}),
        (False, {"hw_type": "可穿戴硬件", "name": "Smart Ring"}),
        (False, {"hw_type": "硬件(护栏兜底)", "name": "Whatever"}),
        (False, {"hw_type": "含电子硬件", "name": "Gadget"}),
        (False, {"hw_type": "科技/电子", "name": "Gadget"}),
        (False, {"hw_type": "consumer electronics", "name": "Coffee Machine"}),
        (False, {"hw_type": "wearable hardware", "name": "Band"}),
        (False, {"hw_type": "electrified tools/vehicles", "name": "Foam dart blaster"}),
        (False, {"hw_type": "", "name": "未分类"}),
        (False, {"hw_type": "Technology", "name": "DeskON"}),   # 模糊标签 → 保留

        # ── 应保留（False）：被误标非硬件、靠硬电子词救回的真硬件 ──
        (False, {"hw_type": "纯软件/服务众筹", "name": "Patience for Eurorack",
                 "blurb": "Lowest frequency oscillator.",
                 "ai_specs_en": [["Width", "14 HP"], ["Voltage range", "switchable bipolar"]]}),
        (False, {"hw_type": "纯软件/服务众筹", "name": "CSTMZED ECOSYSTEM macro keypad",
                 "ai_specs_en": [["Connectivity", "USB-C, Bluetooth"],
                                 ["Firmware Updates", "Regular"]]}),
        (False, {"hw_type": "游戏", "name": "SEIVOID via GENiEX",
                 "ai_specs_en": [["Processor", "Quad-core"], ["Battery Life", "Up to 8 hours"]]}),
        (False, {"hw_type": "纯软件/服务众筹", "name": "PuriFi",
                 "ai_specs_en": [["Platform", "Raspberry Pi 5"]]}),
    ]

    failures = 0
    for expected, proj in cases:
        actual = is_non_hardware(proj)
        ok = actual == expected
        failures += 0 if ok else 1
        print(f"  {'✅' if ok else '❌'} expect={expected!s:<5} got={actual!s:<5} "
              f"| {proj.get('hw_type')!r:<22} | {proj.get('name')[:38]}")
    print(f"\n{'✅ ALL PASS' if not failures else f'❌ {failures} FAILED'} "
          f"({len(cases) - failures}/{len(cases)})")
    raise SystemExit(1 if failures else 0)
