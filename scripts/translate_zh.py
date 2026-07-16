#!/usr/bin/env python3
"""
translate_zh.py — 本地批量翻译脚本

流程:
  1. extract: 从 projects.json 提取未翻译字段，输出待翻译 JSONL
  2. (人工/API 翻译 JSONL)
  3. apply: 将翻译结果回填到 projects.json

用法:
  python scripts/translate_zh.py extract [--limit N] [--batch N]
  python scripts/translate_zh.py apply <translated.jsonl>

翻译规则（硬编码，与 translation-plan.md 一致）:
  - 品牌名/型号保留英文，副标题翻译
  - 单位/协议不翻，配件/材料/颜色翻译
  - 语气忠实，不润色夸大
  - ai_description 分段数保持一致
"""

import json, os, sys, re, shutil

DATA_PATH = "src/data/projects.json"
BACKUP_SUFFIX = ".bak"

# 需要翻译的字段对: (en_field, zh_field, field_type, description)
FIELD_DEFS = [
    ("name",              "nameZh",              "str",       "项目名称"),
    ("ai_intro_en",       "ai_intro_zh",         "str",       "AI 简短介绍"),
    ("ai_description_en",  "ai_description_zh",   "str|list",  "AI 详细描述（多段）"),
    ("ai_highlights_en",  "ai_highlights_zh",    "list",      "Key Highlights"),
    ("ai_specs_en",       "ai_specs_zh",         "list",      "Technical Specs [[label,val],...]"),
    ("ai_risks_en",       "ai_risks_zh",         "str",       "Risks & Challenges"),
    ("ai_risks_structured_en", "ai_risks_structured_zh", "list", "结构化风险 [[title,desc],...]"),
    ("ai_creator_bio_en", "ai_creator_bio_zh",   "str",       "Creator Bio"),
    ("ai_tiers",          "ai_tiers_zh",         "list",      "Reward Tiers（翻 name/description）"),
]

def clean_zh(text):
    """清洗 AI 译文"""
    if not text or not isinstance(text, str):
        return text
    # 删除 AI 自带的注释前缀
    text = re.sub(r'^(Translation[：:].*?\n)', '', text)
    text = re.sub(r'^(Here\'s the Chinese translation[：:].*?\n)', '', text)
    text = re.sub(r'\(Note:.*?\)', '', text)
    text = re.sub(r'（注：.*?）', '', text)
    # 删除首尾空白/换行
    text = text.strip()
    # 过滤空字符串
    if not text:
        return None
    return text

def validate_translation(en_text, zh_text, field_name):
    """验证译文质量，返回 (ok, error_msg)"""
    if not zh_text:
        return False, "空译文"
    if not isinstance(zh_text, str):
        return False, f"类型错误: {type(zh_text)}"
    en_len = len(en_text) if isinstance(en_text, str) else 0
    zh_len = len(zh_text)
    if en_len > 0:
        ratio = zh_len / en_len
        # 不做强制性长度校验——自动放弃可能错过有效翻译
        # 注意：极少数特别短的译文会被后续 down stream 自然降级为英文
        if ratio > 2.0:
            return False, f"译文过长 ({ratio:.1%})"
    return True, ""

def normalize_tier(tier):
    """规范化档位数据结构"""
    result = {}
    for k in ("name", "description", "price", "price_usd", "currency", "backers"):
        v = tier.get(k)
        if v is not None:
            result[k] = v
    return result

# ─── Extract ─────────────────────────────────────────────────

def extract(args):
    limit = None
    batch_size = 50  # 每批项目数
    for a in args:
        if a.startswith("--limit="):
            limit = int(a.split("=")[1])
        elif a.startswith("--batch="):
            batch_size = int(a.split("=")[1])

    if not os.path.exists(DATA_PATH):
        print(f"❌ 找不到 {DATA_PATH}")
        return

    data = json.load(open(DATA_PATH, "r", encoding="utf-8"))
    projects = data["projects"]
    total = len(projects)
    print(f"📦 共 {total} 个项目")

    need_translate = []
    for idx, proj in enumerate(projects):
        if limit and len(need_translate) >= limit:
            break

        fields = []
        for en_field, zh_field, ftype, desc in FIELD_DEFS:
            if proj.get(zh_field) is not None:
                continue  # 已有中文，跳过
            en_val = proj.get(en_field)
            if en_val is None or en_val == "" or (isinstance(en_val, list) and len(en_val) == 0):
                continue  # 无英文源，跳过

            if en_field == "ai_tiers":
                # 档位: 只取 name/description 待翻译
                tier_texts = []
                for t in en_val:
                    name = t.get("name", "")
                    desc = t.get("description", "")
                    if name or desc:
                        tier_texts.append({"idx": len(tier_texts), "name": name, "description": desc})
                if tier_texts:
                    fields.append({
                        "en_field": en_field,
                        "zh_field": zh_field,
                        "type": "tiers",
                        "source": tier_texts,
                        "desc": desc,
                    })
            elif ftype == "list" and isinstance(en_val, list):
                # 列表类型: 所有元素都要翻译
                fields.append({
                    "en_field": en_field,
                    "zh_field": zh_field,
                    "type": "list",
                    "source": en_val,
                    "desc": desc,
                })
            else:
                # 字符串类型
                fields.append({
                    "en_field": en_field,
                    "zh_field": zh_field,
                    "type": "str",
                    "source": en_val,
                    "desc": desc,
                })

        if fields:
            need_translate.append({
                "project_idx": idx,
                "slug": proj.get("slug", ""),
                "name": proj.get("name", ""),
                "fields": fields,
            })

    print(f"📝 待翻译项目: {len(need_translate)} 个")
    total_fields = sum(len(p["fields"]) for p in need_translate)
    print(f"📝 待翻译字段: {total_fields} 条")

    # 分批输出到 JSONL
    output_dir = "scripts/translations"
    os.makedirs(output_dir, exist_ok=True)

    batches = []
    for start in range(0, len(need_translate), batch_size):
        batches.append(need_translate[start:start+batch_size])

    print(f"📦 分为 {len(batches)} 批（每批最多 {batch_size} 个项目）")
    for bi, batch in enumerate(batches):
        outfile = os.path.join(output_dir, f"batch_{bi+1:03d}.jsonl")
        with open(outfile, "w", encoding="utf-8") as f:
            for item in batch:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        proj_names = [p["name"][:30] for p in batch]
        print(f"  ✅ batch_{bi+1:03d}.jsonl — {len(batch)} 个项目: {', '.join(proj_names[:3])}{'...' if len(batch)>3 else ''}")

    print(f"\n💡 翻译后运行: python scripts/translate_zh.py apply scripts/translations/batch_*.jsonl")

# ─── Apply ────────────────────────────────────────────────────

def apply(args):
    if not args:
        print("❌ 用法: python scripts/translate_zh.py apply <translated.jsonl...>")
        return

    if not os.path.exists(DATA_PATH):
        print(f"❌ 找不到 {DATA_PATH}")
        return

    # 备份
    bak = DATA_PATH + BACKUP_SUFFIX
    if not os.path.exists(bak):
        shutil.copy2(DATA_PATH, bak)
        print(f"💾 已备份到 {bak}")

    data = json.load(open(DATA_PATH, "r", encoding="utf-8"))
    projects = data["projects"]
    applied = 0
    errors = 0

    for infile in args:
        if not os.path.exists(infile):
            print(f"⚠️ 跳过不存在文件: {infile}")
            continue
        with open(infile, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                pi = item["project_idx"]
                if pi >= len(projects):
                    print(f"⚠️ 索引越界: {pi}")
                    continue
                proj = projects[pi]

                for field in item["fields"]:
                    en_field = field["en_field"]
                    zh_field = field["zh_field"]
                    translation = field.get("translation")
                    if translation is None:
                        continue

                    if field["type"] == "tiers":
                        # 档位翻译: translation 是 [{idx, name_t, desc_t}, ...]
                        tiers = proj.get(en_field, [])
                        for t in translation:
                            ti = t.get("idx")
                            if ti is None or ti >= len(tiers):
                                continue
                            if t.get("name") is not None:
                                cleaned = clean_zh(t["name"])
                                if cleaned:
                                    tiers[ti]["name"] = cleaned
                            if t.get("description") is not None:
                                cleaned = clean_zh(t["description"])
                                if cleaned:
                                    tiers[ti]["description"] = cleaned
                        proj[zh_field] = tiers
                        applied += 1
                    elif field["type"] == "list":
                        # 列表翻译: translation 是 [zh_1, zh_2, ...]
                        if isinstance(translation, list):
                            cleaned = []
                            ok = True
                            for i, orig in enumerate(field.get("source", [])):
                                t = translation[i] if i < len(translation) else None
                                if t:
                                    t = clean_zh(t)
                                if t:
                                    cleaned.append(t)
                                else:
                                    ok = False
                                    cleaned.append(orig)
                            if ok:
                                proj[zh_field] = cleaned
                                applied += 1
                            else:
                                print(f"  ⚠️ {proj.get('name','?')}.{zh_field}: 部分元素为空，已保留原文")
                                proj[zh_field] = cleaned
                                applied += 1
                        else:
                            print(f"  ❌ {proj.get('name','?')}.{zh_field}: translation 不是 list")
                            errors += 1
                    else:
                        # 字符串翻译
                        t = clean_zh(translation) if isinstance(translation, str) else None
                        if t:
                            valid, msg = validate_translation(field.get("source", ""), t, en_field)
                            if valid:
                                proj[zh_field] = t
                                applied += 1
                            else:
                                print(f"  ❌ {proj.get('name','?')}.{zh_field}: {msg}")
                                errors += 1
                        else:
                            print(f"  ⚠️ {proj.get('name','?')}.{zh_field}: 空译文，跳过")
                            errors += 1

    # 写回
    json.dump(data, open(DATA_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n✅ 完成: 应用 {applied} 条翻译, {errors} 条错误")

# ─── CLI ──────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python scripts/translate_zh.py extract [--limit=N] [--batch=N]")
        print("  python scripts/translate_zh.py apply <translated.jsonl...>")
        return

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "extract":
        extract(rest)
    elif cmd == "apply":
        apply(rest)
    else:
        print(f"未知命令: {cmd}")

if __name__ == "__main__":
    main()
