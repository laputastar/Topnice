#!/usr/bin/env python3
"""gate.py 自测：验证内容级智能硬件闸门的精度。

用法: python scripts/gate_selftest.py
纯 Python、零 API 依赖。期望结果：
  - SHOULD_BLOCK 用例 → decision == "block"（明显非硬件，全部拦下）
  - SHOULD_PASS  用例 → decision == "pass"（真实硬件，零误拦）
任一不符即退出码 1（CI 可据此失败）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate import gate_smart_hardware

# 明显非硬件（历史上漏入线上的典型）：期望全部 block
SHOULD_BLOCK = [
    {"name": "The Last Voyage", "parent_category": "Film & Video",
     "blurb": "A feature documentary film about the ocean", "story": ""},
    {"name": "Midnight Novel", "parent_category": "Publishing",
     "blurb": "A debut novel exploring the city at night", "story": ""},
    {"name": "Seoul Kimchi Jar", "parent_category": "Food",
     "blurb": "Authentic fermented kimchi made in small batches", "story": ""},
    {"name": "Ikigai Knives", "parent_category": "Design",
     "blurb": "Hand-forged Damascus chef knife and kitchen knife set", "story": ""},
    {"name": "Pixel Plush Bear", "parent_category": "Toys",
     "blurb": "Cute plush stuffed animal for kids", "story": ""},
    {"name": "Everyday Cotton Tee", "parent_category": "Apparel",
     "blurb": "Soft organic cotton t-shirt in 5 colors", "story": ""},
    {"name": "Dungeon Quest", "parent_category": "Games",
     "blurb": "A strategic board game for the whole family", "story": ""},
    {"name": "Nonna's Pasta Sauce", "parent_category": "Food",
     "blurb": "Traditional Italian hot sauce and pasta sauce", "story": ""},
    {"name": "Lumière Café", "parent_category": "Food",
     "blurb": "Help us open a cozy café and community space", "story": ""},
    {"name": "Vinyl Revival LP", "parent_category": "Music",
     "blurb": "Our debut music album on vinyl record", "story": ""},
    {"name": "Zen Rock Documentary", "parent_category": "Film & Video",
     "blurb": "An indie film and short film about mountains", "story": ""},
    {"name": "Paper Card Pack", "parent_category": "Crafts",
     "blurb": "Handmade greeting card and washi tape set", "story": ""},
    {"name": "ClimbBoard Pro", "parent_category": "Sports",
     "blurb": "A wooden climbing board training tool for fingers", "story": ""},
    {"name": "Gold Wedding Band", "parent_category": "Fashion",
     "blurb": "14k gold ring for your special day", "story": ""},
    {"name": "Travel Japan Retreat", "parent_category": "Travel",
     "blurb": "Join our travel experience and cultural retreat", "story": ""},
]

# 真实硬件（含电子/智能信号）：期望全部 pass（绝不被误拦）
SHOULD_PASS = [
    {"name": "ZenFit Smartwatch", "parent_category": "Technology",
     "blurb": "Bluetooth heart-rate smartwatch with companion app", "story": "wearable sensor"},
    {"name": "AeroX Drone", "parent_category": "Technology",
     "blurb": "WiFi FPV camera drone with GPS and app control", "story": "brushless motor"},
    {"name": "Thermal Collar 2.0", "parent_category": "Fashion",
     "blurb": "Battery-powered heated collar with USB-C rechargeable heating element", "story": "peltier"},
    {"name": "Smart Ring Trace", "parent_category": "Wearables",
     "blurb": "Smart ring with bluetooth tracker and sleep sensor", "story": "app"},
    {"name": "Maker 3D Printer", "parent_category": "Technology",
     "blurb": "WiFi 3D printer with touch screen and Arduino board", "story": "pcb"},
    {"name": "BoomBox Mini", "parent_category": "Hardware",
     "blurb": "Portable bluetooth speaker with rechargeable battery", "story": "led"},
    {"name": "Arduino Starter Kit", "parent_category": "Technology",
     "blurb": "MCU learning kit with esp32 and sensors", "story": "circuit"},
    {"name": "LumiDesk Lamp", "parent_category": "Product Design",
     "blurb": "USB-C LED desk lamp with touch panel dimming", "story": "oled display"},
    {"name": "RoboVac Neo", "parent_category": "Technology",
     "blurb": "Smart home robot vacuum with app-controlled mapping", "story": "motor"},
    {"name": "EchoGlasses", "parent_category": "Wearables",
     "blurb": "Smart glasses with display and voice control", "story": "microcontroller"},
    {"name": "PowerBank 20K", "parent_category": "Hardware",
     "blurb": "Solar rechargeable power bank with USB-C", "story": "battery"},
    {"name": "Smart Chef Scale", "parent_category": "Food",
     "blurb": "Bluetooth kitchen scale with app nutrition tracking", "story": "sensor"},
    {"name": "E-Bike Motor Kit", "parent_category": "Technology",
     "blurb": "Brushless motor e-bike conversion kit with controller", "story": "actuator"},
    {"name": "Flux Pen Stylus", "parent_category": "Design",
     "blurb": "Pressure-sensitive stylus with bluetooth for iPad", "story": "chip"},
    {"name": "EV Charger Home", "parent_category": "Hardware",
     "blurb": "Smart EV charger with wifi scheduling and app", "story": "circuit board"},
]

fails = []

def check(label, cases, expect_block):
    print(f"\n=== {label} (期望 {'BLOCK' if expect_block else 'PASS'}) ===")
    for p in cases:
        g = gate_smart_hardware(p)
        got_block = g["decision"] == "block"
        ok = got_block == expect_block
        mark = "✅" if ok else "❌"
        if not ok:
            fails.append((p.get("name"), expect_block, got_block, g["hw_reason"]))
        print(f"  {mark} [{g['decision'].upper():5}] {p.get('name',''):22} -> {g['hw_type'] or '-':10} | {g['hw_reason']}")

check("明显非硬件 (应拦)", SHOULD_BLOCK, True)
check("真实硬件 (应放行)", SHOULD_PASS, False)

print("\n" + "=" * 60)
if fails:
    print(f"❌ 自测失败 {len(fails)} 项:")
    for name, exp, got, reason in fails:
        print(f"   - {name}: 期望={'BLOCK' if exp else 'PASS'} 实际={'BLOCK' if got else 'PASS'} ({reason})")
    sys.exit(1)
else:
    print(f"✅ 全部通过：{len(SHOULD_BLOCK)} 项非硬件全拦，{len(SHOULD_PASS)} 项硬件零误拦")
    sys.exit(0)
