#!/usr/bin/env python3
"""
classify-existing.py — 对 projects.json 已有的项目运行 Long Cat 硬件分类。

用法:
  python scripts/classify-existing.py           # 仅展示分类结果，不修改
  python scripts/classify-existing.py --apply   # 展示 + 从 projects.json 删除非硬件

依赖: LONG_CAT_API_KEY / AGNES_API_KEY 环境变量
"""
import sys, json, os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from merge import batch_hardware_classify

APPLY = "--apply" in sys.argv
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "src", "data", "projects.json")

data = json.load(open(DATA, encoding="utf-8"))
projects = data["projects"]

print(f"📦 共 {len(projects)} 个项目")

results = batch_hardware_classify(projects)

hw = [p for p in results if p.get("hardware_class") == "hardware"]
non_hw = [p for p in results if p.get("hardware_class") == "non-hardware"]

print(f"\n{'='*55}")
print(f"  硬件保留:  {len(hw):4} ({len(hw)*100//len(results):2}%)")
print(f"  非硬件剔除: {len(non_hw):4} ({len(non_hw)*100//len(results):2}%)")
print(f"{'='*55}")

if non_hw:
    types = Counter(p.get("hw_type", "?") for p in non_hw)
    print(f"\n非硬件分类:")
    for t, c in types.most_common():
        print(f"  {t}: {c}")

    print(f"\n剔除项目:")
    for idx, p in enumerate(non_hw, 1):
        print(f"  {idx:3}. ❌ {p.get('name','')[:50]:50} | {p.get('hw_reason','')[:30]}")

    if APPLY:
        data["projects"] = hw
        tmp = DATA + ".tmp"
        json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        os.replace(tmp, DATA)
        print(f"\n✅ 已从 projects.json 删除 {len(non_hw)} 个非硬件项目")
    else:
        print(f"\n💡 这是 --dry-run，未修改文件。确认后加 --apply 执行删除。")
else:
    print("\n✅ 全部项目均为硬件，无剔除项。")
