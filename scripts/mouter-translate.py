#!/usr/bin/env python3
"""
mouter-translate.py — 使用 Mouter AI（独立翻译引擎）批量翻译

独立于 Cloudflare 英文抽取链路，独占 Mouter AI 额度，避免免费额度撞车。

用法:
  1. 设置环境变量（在 translate-only.yml 中以 secrets 注入）:
     export MOUTER_API_KEY="你的 Key"
     export MOUTER_BASE_URL="https://你的 Mouter 端点/v1"
     export MOUTER_MODEL="mouter-translate"   # 模型名（按引擎方提供）

  2. 翻译一批（通常由 translate_zh.py extract 生成）:
     python scripts/mouter-translate.py scripts/translations/batch_001.jsonl

  3. 回填（由 translate_zh.py apply 完成，本脚本只产出 _zh.jsonl）:
     python scripts/translate_zh.py apply

依赖: pip install requests openai

幂等 / 防额度浪费设计:
  - 若输出 _zh.jsonl 已存在，则其中「已完成翻译」的项目直接复用，不重复调用 API。
  - 单批内逐项目翻译；崩溃只丢本批未写盘部分，已有译文不丢、不重花。
  - JSON 解析多层兜底：严格数组 -> 贪婪正则 -> 字典兜底（模型偶发回对象而非数组）。
"""

import json, sys, os, time, re

# 统一 LLM/API 调用层（集中读 env、统一重试/超时/代理）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm import call_mouter, LLMError

# 可选本地代理（仅中国网络访问 Mouter 时需要）；留空则直连
PROXY = os.environ.get("MOUTER_PROXY", "") or None
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def parse_translations(content: str, n_expected: int):
    """把模型返回解析为译文列表。多层兜底，失败时返回 None（由调用方决定保留英文）。"""
    s = _strip_fences(content)
    # 1) 直接解析
    try:
        arr = json.loads(s)
        if isinstance(arr, list):
            return arr
    except Exception:
        pass
    # 2) 贪婪正则提取首个 [ ... ]
    m = re.search(r"\[.*\]", s, re.DOTALL)
    if m:
        try:
            arr = json.loads(m.group())
            if isinstance(arr, list):
                return arr
        except Exception:
            pass
    # 3) 字典兜底：模型偶发返回 {label: translation} 而非数组 —— 取插入顺序的 values
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return list(obj.values())
    except Exception:
        pass
    return None


def translate_batch(batch_file, force=False):
    with open(batch_file, "r", encoding="utf-8") as f:
        items = [json.loads(line) for line in f if line.strip()]

    print(f"📦 {batch_file}: {len(items)} 个项目")
    out_file = batch_file.replace(".jsonl", "_zh.jsonl")

    # 断点续译：复用已有 _zh 中已完成翻译的项目
    existing = {}
    if (not force) and os.path.exists(out_file):
        with open(out_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                it = json.loads(line)
                idx = it.get("project_idx")
                # 必须有至少一个非空译文才算「已完成」
                done = any(
                    fd.get("translation") not in (None, "", [], {})
                    for fd in it.get("fields", [])
                )
                if idx is not None and done:
                    existing[idx] = it
        if existing:
            print(f"  ♻️ 复用已有译文 {len(existing)} 项（不重复消耗额度）")

    output = []

    for idx, item in enumerate(items):
        pi = item.get("project_idx")
        # 已译项目直接复用
        if pi in existing:
            output.append(existing[pi])
            continue

        print(f"  [{idx+1}/{len(items)}] {item.get('name','')[:40]}...")

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

        # 调用 Mouter AI（OpenAI 兼容）
        prompt = f"""Translate each line to Simplified Chinese. Keep brand names, model numbers, and technical specs (e.g. 'HELIX', 'USB-C', '48GB') untranslated.

Return ONLY a JSON array of translated strings in the same order as the input lines. Do not add labels, keys, or commentary.

Input lines:
{chr(10).join(texts)}"""

        system = "You are a professional translator. Return only a valid JSON array."
        translations = None
        for attempt in range(3):
            try:
                content = call_mouter(
                    prompt,
                    system=system,
                    timeout=120,
                    max_retries=0,
                    proxies=PROXIES,
                )
                translations = parse_translations(content, len(field_map))
                if translations is None:
                    print(f"    ⚠️ 无法解析 JSON: {content[:120]}")
                    continue
                break
            except LLMError as e:
                print(f"    ⚠️ 错误: {e}, 重试 {attempt+1}/3")
                if attempt < 2:
                    time.sleep(3)

        if translations is None:
            # 翻译失败：保留原文（translation 置 None，apply 会跳过，不丢已有译文）
            print(f"    ⚠️ 翻译失败，保留英文源")
            output.append(item)
            if idx < len(items) - 1:
                time.sleep(1)
            continue

        # 回填
        for i, (typ, fd, ref, subkey) in enumerate(field_map):
            t = translations[i] if i < len(translations) else None
            if typ == "tier_name":
                ref["name_zh"] = t
            elif typ == "tier_desc":
                ref["description_zh"] = t
            elif typ == "str":
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
    if len(sys.argv) < 2:
        print("用法: python scripts/mouter-translate.py <batch.jsonl> [--force]")
        sys.exit(1)
    force = "--force" in sys.argv
    for arg in sys.argv[1:]:
        if arg.startswith("scripts/") or arg.endswith(".jsonl"):
            translate_batch(arg, force=force)