#!/usr/bin/env python3
"""
cf-translate.py — 使用 Cloudflare Workers AI 批量翻译（唯一翻译器入口）

用法:
  1. 设置环境变量:
     export CLOUDFLARE_ACCOUNT_ID="你的账号ID"
     export CLOUDFLARE_API_TOKEN="你的API Token"
     # 可选：从中国网络访问 CF 时设置本地代理
     export CF_PROXY="http://127.0.0.1:7897"
     # 可选：覆盖翻译模型（默认见下方 MODEL）
     export CF_TRANSLATE_MODEL="@cf/z-ai/glm-4.7-flash"

  2. 翻译一批:
     python scripts/cf-translate.py scripts/translations/batch_001.jsonl

  3. 回填:
     python scripts/translate_zh.py apply scripts/translations/batch_001_zh.jsonl

依赖: pip install requests
"""

import json, sys, os, time, re

# 统一 LLM/API 调用层（集中读 env、统一重试/超时/代理）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm import call_cloudflare, LLMError

# 默认模型为已验证可用的 GLM-4.7-Flash；可用 CF_TRANSLATE_MODEL 覆盖
MODEL = os.environ.get("CF_TRANSLATE_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8")
# 可选本地代理（仅中国网络访问 CF 时需要）；留空则直连
PROXY = os.environ.get("CF_PROXY", "") or None
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None

def translate_batch(batch_file):
    with open(batch_file, "r", encoding="utf-8") as f:
        items = [json.loads(line) for line in f if line.strip()]

    print(f"📦 {batch_file}: {len(items)} 个项目")
    out_file = batch_file.replace(".jsonl", "_zh.jsonl")
    output = []

    for idx, item in enumerate(items):
        print(f"  [{idx+1}/{len(items)}] {item['name'][:40]}...")

        # 收集所有待翻译文本
        texts = []
        field_map = []
        for fd in item["fields"]:
            if fd["type"] == "tiers":
                for t in fd["source"]:
                    if t.get("name"):
                        texts.append(f'TIER_NAME: {t["name"]}')
                        field_map.append(("tier_name", fd, t, "name"))
                    if t.get("description"):
                        texts.append(f'TIER_DESC: {t["description"]}')
                        field_map.append(("tier_desc", fd, t, "description"))
            elif fd["type"] == "list":
                for i, s in enumerate(fd["source"]):
                    if isinstance(s, list):
                        texts.append(f'SPEC: {" | ".join(str(x) for x in s)}')
                        field_map.append(("spec", fd, i, None))
                    else:
                        texts.append(f'HIGHLIGHT: {s}')
                        field_map.append(("highlight", fd, i, None))
            else:
                text = fd["source"]
                texts.append(f'{fd["zh_field"]}: {text[:1000]}')
                field_map.append(("str", fd, text, None))

        # 调用 CF Workers AI
        prompt = f"""Translate each line to Simplified Chinese. Keep brand names, model numbers, and technical specs (e.g. 'HELIX', 'USB-C', '48GB') untranslated.

Return ONLY a JSON array of translated strings in the same order as input.

Input:
{chr(10).join(texts)}"""

        system = "You are a professional translator. Return only valid JSON."
        for attempt in range(3):
            try:
                content = call_cloudflare(
                    prompt,
                    model=MODEL,
                    system=system,
                    timeout=120,
                    max_retries=0,
                    proxies=PROXIES,
                )
                # 提取 JSON 数组
                m = re.search(r'\[.*?\]', content, re.DOTALL)
                if not m:
                    print(f"    ⚠️ 无法解析 JSON: {content[:100]}")
                    continue  # 与旧行为一致：不 sleep，直接进入下一次尝试
                translations = json.loads(m.group())
                # 回填
                for i, (typ, fd, ref, subkey) in enumerate(field_map):
                    t = translations[i] if i < len(translations) else None
                    if typ == "tier_name":
                        ref["name_zh"] = t
                    elif typ == "tier_desc":
                        ref["description_zh"] = t
                    elif typ in ("str",):
                        fd["translation"] = t
                    elif typ == "spec":
                        if "translation" not in fd:
                            fd["translation"] = []
                        while len(fd["translation"]) <= ref:
                            fd["translation"].append(None)
                        fd["translation"][ref] = t
                    elif typ == "highlight":
                        if "translation" not in fd:
                            fd["translation"] = []
                        while len(fd["translation"]) <= ref:
                            fd["translation"].append(None)
                        fd["translation"][ref] = t
                break
            except LLMError as e:
                print(f"    ⚠️ 错误: {e}, 重试 {attempt+1}/3")
                if attempt < 2:
                    time.sleep(3)

        # 档位翻译回填
        for fd in item["fields"]:
            if fd["type"] == "tiers":
                tiers_zh = []
                for t in fd.get("source", []):
                    tier_copy = dict(t)
                    if t.get("name_zh"):
                        tier_copy["name"] = t["name_zh"]
                    if t.get("description_zh"):
                        tier_copy["description"] = t["description_zh"]
                    tiers_zh.append(tier_copy)
                fd["translation"] = tiers_zh

        output.append(item)

        # 冷却，避免限流
        if idx < len(items) - 1:
            time.sleep(1)

    # 原子写：先写 .tmp 再 os.replace，崩溃不损坏批处理文件
    tmp = out_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for item in output:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    os.replace(tmp, out_file)
    print(f"✅ 保存到 {out_file}")

if __name__ == "__main__":
    if len(sys.argv) < 2 or not os.environ.get("CLOUDFLARE_ACCOUNT_ID") or not os.environ.get("CLOUDFLARE_API_TOKEN"):
        print("用法: CLOUDFLARE_ACCOUNT_ID=xxx CLOUDFLARE_API_TOKEN=yyy python scripts/cf-translate.py batch.jsonl")
        sys.exit(1)
    translate_batch(sys.argv[1])
