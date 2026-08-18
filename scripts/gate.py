#!/usr/bin/env python3
"""
gate.py — TopNice 内容级「智能硬件闸门」（确定性、零 API 依赖）

目的
----
merge.py 的 batch_hardware_classify 依赖 Cloudflare Workers AI 做硬件/非硬件判定。
当 CF 凭据缺失/宕机时，整批会兜底保留（hardware）；且单批删除率 >40% 的护栏会把
整批兜底保留。两者叠加 → 纯物理件（电影/书/泡菜/厨刀/毛绒/T恤/桌游/餐厅体验）持续漏入线上。

本模块在 LLM 分类 *之前* 跑一道确定性闸门：
  - 命中「强非硬件信号」且「无任何电子/智能信号」→ 直接判定 non-hardware（不打 LLM，
    CF 宕机也能拦），并给出细分类 hw_type 以便下游过滤 + 删除清单可追溯。
  - 否则 → pass，交给 LLM 判定（含边界/歧义项）。

设计原则（最重要）：**宁漏勿错**。闸门只拦「明显非硬件」，绝不拦真实硬件。
判定为 block 的两个前提（强非硬件词 + 无电子信号）同时成立才拦，二者缺一即放行。
真实硬件几乎必然带有电子/智能信号词，故被误拦概率极低。

精度 > 召回：闸门不追求拦下所有非硬件（那部分交给 LLM），只负责把「CF 宕机/护栏误保」
时会漏网的明显非硬件挡在摄入源头之外。
"""
import re

# ─────────────────────────────────────────────────────────────────────────────
# 1) 电子 / 智能信号：命中任一词即视为「疑似硬件」，闸门不拦截。
#    该正则越「贪心」越安全（贪心 → 更少拦截 → 保守侧），故尽量覆盖常见电子词。
#    全部用 \b 词边界，避免 chip→"potato chips"、bar→"soundbar"、led→"we led" 等误命中
#    （"potato chips" 中 chip 与 s 之间无词边界，\bchip\b 不匹配；"soundbar" 同理）。
# ─────────────────────────────────────────────────────────────────────────────
ELECTRONIC_RE = re.compile(
    r"""(?x)
    \b(
        bluetooth | wi-?fi | wireless | zigbee | nfc | rfid | uwb | lora | thread |
        iot | smart-?home | smart-?watch | smart-?phone | smart-?glasses | smart-?ring |
        smart-?band | smart-?scale | smart-?lock | app-?controlled | companion-?app |
        \bapp\b | connected | rechargeable | battery | batteries | usb-?c | \busb\b | solar |
        electric | electrical | charge | charging | charger |
        motor | brushless | actuator | pump | thermoelectric | peltier | heating-?element |
        sensor | sensors | camera | microphone | display | screen | e-?ink | touch-?screen |
        touch-?panel | mcu | arduino | raspberry | \bchip\b | pcb | circuit-?board | \bcircuit\b |
        led | oled | speaker | headphone | earbud | earbuds | projector | haptic | \bgpu\b |
        \bcpu\b | firmware | esp32 | esp8266 | raspberry-?pi | ai-?powered | machine-?learning |
        \bai\b | \buv\b | \bgps\b | imu | gyroscope | accelerometer |
        solenoid | servo | stepper | fan-?less | \brgb\b | microcontroller | silicon |
        transistor | motherboard | subwoofer | woofer | mems | laser | audio | recording |
        gpt | transcription | gesture | voice-?control | motion-?detect | \bsmart\b
    )\b
    """,
    re.VERBOSE | re.IGNORECASE | re.ASCII,
)

# ─────────────────────────────────────────────────────────────────────────────
# 2) 类别强信号（结构化、可靠）：parent_category / category 命中且无电子信号 → 拦截。
#    仅保留「几乎确定非硬件」的品类，避免误拦（如 Photography/Art/Games 含硬件边缘，不放）。
#    映射：类别词 → (hw_type, 展示名)
# ─────────────────────────────────────────────────────────────────────────────
CAT_HW_MAP = {
    "publishing":   ("书籍影视", "出版"),
    "film":         ("书籍影视", "影视"),
    "music":        ("书籍影视", "音乐"),
    "theater":      ("书籍影视", "戏剧"),
    "journalism":   ("书籍影视", "新闻"),
    "comics":       ("书籍影视", "漫画"),
    "crafts":       ("其他非硬件", "手作"),
    "dance":        ("其他非硬件", "舞蹈"),
    "food":         ("食品厨具", "食品"),
    "fashion":      ("服饰鞋包", "时尚"),
    "apparel":      ("服饰鞋包", "服饰"),
    "footwear":     ("服饰鞋包", "鞋履"),
    "jewelry":      ("服饰鞋包", "珠宝"),
    "accessories":  ("服饰鞋包", "配饰"),
}

# ─────────────────────────────────────────────────────────────────────────────
# 3) 关键词规则：name+blurb+story 命中强非硬件词，且无电子信号 → 拦截。
#    每条：(regex, hw_type, reason)。命中即拦（与电子信号互斥由调用方保证）。
#    关键词尽量具体，避免 bare 泛词（如 "coffee"/"tool"/"card"/"book" 过泛不放），
#    以守住精度。
# ─────────────────────────────────────────────────────────────────────────────
NONHW_RULES = [
    # 影视 / 出版 / 文字
    (r"\b(documentary|feature film|short film|full-?length film|indie film|web series|"
     r"tv series|comic book|graphic novel|manga|novel|coloring book|art book|photo book|"
     r"coffee table book|hardcover|paperback|zine|audiobook|textbook|memoir|biography|"
     r"poetry collection|childrens book|picture book)\b",
     "书籍影视", "出版/影视/文字类，无电子信号"),

    # 音乐（专辑/唱片，非硬件乐器）
    (r"\b(music album|debut album|studio album|vinyl record|vinyl lp|lp record|"
     r"record label|songwriter|bandcamp)\b",
     "书籍影视", "音乐专辑/唱片，无电子信号"),

    # 食品 / 饮品 / 厨具（无电路）
    (r"\b(kimchi|hot sauce|bbq sauce|pasta sauce|coffee bean|coffee beans|tea blend|"
     r"tea set|energy bar|protein bar|recipe book|cookbook|seasoning|whisky|whiskey|"
     r"craft beer|chocolate bar|pastry|ramen|noodle|instant noodle|jerky|matcha|"
     r"kombucha|olive oil|spice blend|condiment|meal kit|cookie|biscuit|jam|honey|"
     r"syrup|broth|soup|ferment|snack)\b",
     "食品厨具", "食品/饮品/厨具，无电子信号"),

    # 服饰 / 鞋包 / 配饰
    (r"\b(t-?shirt|hoodie|sweatshirt|sneaker|sneakers|jacket|scarf|socks|beanie|"
     r"sweater|dress|leggings|tote bag|canvas backpack|wallet|purse|jewelry|necklace|"
     r"bracelet|earring|gold ring|silver ring|wedding band)\b",
     "服饰鞋包", "服饰/鞋包/配饰，无电子信号"),

    # 纯玩具 / 卡牌 / 手作 / 装饰
    (r"\b(plush|plushie|stuffed animal|figurine|blind box|mystery box|sticker pack|"
     r"art print|poster print|greeting card|washi tape|embroidery kit|crochet|"
     r"knitting kit|origami|board game|card game|tabletop game|jigsaw|fidget toy|"
     r"fidget cube|coloring book|notebook|stationery)\b",
     "其他非硬件", "纯玩具/卡牌/手作/装饰，无电子信号"),

    # 服务 / 体验 / 众筹（无实体硬件）
    (r"\b(restaurant|caf[eé]|coffee shop|cocktail bar|wine bar|brewpub|travel experience|"
     r"retreat|workshop.*(learn|class|course)|coaching|community space|venue|"
     r"fundraiser|documentary fund)\b",
     "服务众筹", "服务/体验类，无实体硬件"),

    # 非智能健身器材（纯物理）
    (r"\b(yoga mat|resistance band|foam roller|jump rope|skipping rope|dumbbell|"
     r"kettlebell|water bottle|gym towel|ab roller|push-?up board)\b",
     "其他非硬件", "非智能健身器材，无电子信号"),

    # 纯机械工具（无电子模块）
    (r"\b(fixed blade|folding knife|pocket knife|edc knife|chef knife|kitchen knife|"
     r"damascus|multitool|multi-?tool|screwdriver|wrench|ratchet|sharpener|"
     r"mechanical pen|edc tool|pocket tool|camping cookware|cast iron|cutting board|"
     r"chopping board|titanium.*(tool|utensil)|climbing board|climbboard|fingerboard|"
     r"finger board|hangboard|hang board|training board|pull-?up board)\b",
     "纯机械工具", "纯机械工具，无电子模块"),
]


def _project_text(proj: dict) -> tuple[str, str]:
    """返回 (全文小写, 类别文本小写)。防御性取值，字段缺失不报错。"""
    name = proj.get("name", "") or ""
    blurb = proj.get("blurb") or proj.get("tagline") or ""
    desc = (
        proj.get("story")
        or proj.get("description")
        or proj.get("about")
        or ""
    )
    parent = proj.get("parent_category") or ""
    cat = proj.get("category") or ""
    text = f"{name} {blurb} {desc}".lower()
    cat_text = f"{parent} {cat}".lower()
    return text, cat_text


def gate_smart_hardware(proj: dict) -> dict:
    """内容级智能硬件闸门（确定性）。

    返回 dict:
      {
        "decision": "block" | "pass",
        "hw_type":  "<细分类，block 时非空>",
        "hw_reason": "<拦截理由，block 时非空>",
        "gate": True/False
      }

    规则：
      - 命中「强非硬件信号」 且 「无任何电子/智能信号」 → block。
      - 二者缺一 → pass（交给 LLM 或默认保留）。
    该判定不调用任何 LLM/API，结果稳定可复现。
    """
    text, cat_text = _project_text(proj)
    has_elec = bool(ELECTRONIC_RE.search(text))

    # ① 类别强信号（结构化，可靠）：命中且无电子信号 → 拦截
    if not has_elec:
        for cat, (hw_type, label) in CAT_HW_MAP.items():
            if cat in cat_text:
                return {
                    "decision": "block",
                    "hw_type": hw_type,
                    "hw_reason": f"类别含[{label}]且无电子信号",
                    "gate": True,
                }

    # ② 关键词规则：命中强非硬件词且不带电子信号 → 拦截
    if not has_elec:
        for pat, hw_type, reason in NONHW_RULES:
            if re.search(pat, text, re.IGNORECASE | re.ASCII):
                return {
                    "decision": "block",
                    "hw_type": hw_type,
                    "hw_reason": reason,
                    "gate": True,
                }

    return {"decision": "pass", "hw_type": "", "hw_reason": "", "gate": False}


# 便于 classify-existing.py 等复用：批量判定
def gate_batch(projects: list) -> list:
    """对一批项目逐个跑闸门，返回判定结果列表（与 projects 顺序一致）。"""
    return [gate_smart_hardware(p) for p in projects]


if __name__ == "__main__":
    # 简易 CLI 自测：从标准输入读 JSON 数组 或 直接演示若干样例
    import json, sys

    samples = [
        {"name": "The Last Voyage", "parent_category": "Film & Video",
         "blurb": "A feature documentary film about the ocean", "story": ""},
        {"name": "Seoul Kimchi Jar", "parent_category": "Food",
         "blurb": "Authentic fermented kimchi made in small batches", "story": ""},
        {"name": "ZenFit Smartwatch", "parent_category": "Technology",
         "blurb": "Bluetooth heart-rate smartwatch with app", "story": ""},
    ]
    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        samples = json.load(sys.stdin)
    for p in samples:
        g = gate_smart_hardware(p)
        print(f"[{g['decision'].upper():5}] {p.get('name',''):24} -> {g['hw_type'] or '-':10} | {g['hw_reason']}")
