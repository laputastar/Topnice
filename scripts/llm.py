#!/usr/bin/env python3
"""
llm.py — TopNice 数据管线统一 LLM / API 调用层（共享模块）

所有 API Key 仅从环境变量读取，严禁硬编码（防泄露进 git / 分享）。

提供商:
  - Cloudflare Workers AI (主, 英文抽取): CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID / 模型可配（默认 qwen3-30b）
  - Agnes AI   (OpenAI 兼容, 推理模型, 备用): AGNES_API_KEY / base https://apihub.agnes-ai.com/v1 / model agnes-2.0-flash
  - Mouter AI  (OpenAI 兼容, 翻译专用独立引擎): MOUTER_API_KEY + MOUTER_BASE_URL(缺省 https://api.ainext.com/v1) + MOUTER_MODEL(缺省 nvidia/nemotron-3-super-120b-a12b)
    翻译链路独占该引擎额度，与 Cloudflare 英文抽取解耦，避免 10k 免费额度撞车。

统一能力:
  - 环境变量只在此处集中读取一次（全管线唯一来源）
  - 统一超时 / 限流(429)退避重试 / 错误归一为 LLMError
  - 所有函数返回模型原始文本(str)；失败时抛 LLMError，由调用方决定 fallback

环境变量:
  AGNES_API_KEY, CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID
  MOUTER_API_KEY, MOUTER_BASE_URL, MOUTER_MODEL (翻译专用独立引擎)
  可选: CF_TRANSLATE_MODEL (覆盖 CF 默认模型), CF_PROXY (中国网络访问 CF 的本地代理)
"""
import os
import re
import time
import json
import requests

try:
    from openai import OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False


# ---- 集中读取环境变量（全管线唯一来源）----
CF_ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CF_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CF_MODEL = os.environ.get("CF_TRANSLATE_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8")
CF_PROXY = os.environ.get("CF_PROXY", "") or None
CF_PROXIES = {"http": CF_PROXY, "https": CF_PROXY} if CF_PROXY else None

AGNES = {
    "api_key_var": "AGNES_API_KEY",
    "base_url": "https://apihub.agnes-ai.com/v1",
    "model": "agnes-2.0-flash",
    "timeout": 90,
}

# Mouter AI — 翻译专用独立引擎（OpenAI 兼容协议）。
# 三个变量均从环境变量读取，绝不硬编码。base_url 缺省回退到官方地址 https://api.ainext.com/v1；
# model 缺省回退到 nvidia/nemotron-3-super-120b-a12b；若对应环境变量存在则以其为准（便于切换端点/模型）。
MOUTER = {
    "api_key_var": "MOUTER_API_KEY",
    "base_url": os.environ.get("MOUTER_BASE_URL") or "https://api.ainext.com/v1",
    "model": os.environ.get("MOUTER_MODEL") or "nvidia/nemotron-3-super-120b-a12b",
    "timeout": 120,
}


class LLMError(Exception):
    """统一错误类型：任何 LLM 调用失败都抛这个，调用方据此做 fallback。"""
    pass


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def _strip_think(text: str) -> str:
    """剥离推理模型可能在 content 中夹带的思考标签（<think>...</think> / <reasoning>...</reasoning>）。

    部分推理模型（如 Agnes）把思维链写入独立字段 reasoning_content，正常不污染 content；
    此处防御性移除，以防端点把思考塞进 content 而污染下游 JSON 解析 / 翻译。
    """
    if not text:
        return text
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<reasoning>.*?</reasoning>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def parse_json(text: str):
    """剥离 ``` 围栏后解析 JSON。失败抛 LLMError。"""
    try:
        return json.loads(_strip_fences(text))
    except Exception as e:
        raise LLMError(f"JSON 解析失败: {e}") from e


def _is_rate_limit(err: str) -> bool:
    e = (err or "").lower()
    return ("429" in err) or ("rate" in e) or ("ratelimit" in e) or ("too many requests" in e)


def call_compatible_llm(
    prompt: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
    system: str | None = None,
    temperature: float = 0.1,
    timeout: int = 90,
    max_tokens: int = 2000,
    max_retries: int = 1,
    retry_rate_limit_only: bool = True,
) -> str:
    """调用 OpenAI 协议兼容端点（如 Agnes AI 推理模型）。返回模型原始文本；失败抛 LLMError。

    max_retries: 首次失败后的额外重试次数（总尝试 = max_retries + 1）。
    retry_rate_limit_only=True 时仅在 429 限流时重试（与 ai-extract 旧行为一致）；
    设为 False 则在任何异常时都重试。

    max_tokens: 推理模型（如 Agnes）思考会占用上下文预算，需预留足够额度给最终答案，
    避免答案被截断。同时会防御性剥离可能混入 content 的思考标签（<think>/<reasoning>）。
    """
    if not _HAS_OPENAI:
        raise LLMError("openai 未安装")
    if not api_key:
        raise LLMError("API Key 未配置")
    client = OpenAI(api_key=api_key, base_url=base_url)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            raw = resp.choices[0].message.content
            # 推理模型（Agnes）可能在 content 中夹带 <think>/<reasoning> 思考内容，
            # 防御性剥离，避免污染下游 JSON 解析 / 翻译。
            raw = _strip_think(raw)
            if not raw:
                raise LLMError("empty response")
            return raw
        except LLMError:
            raise
        except Exception as e:
            last_err = e
            if attempt < max_retries and (not retry_rate_limit_only or _is_rate_limit(str(e))):
                backoff = 2 * (attempt + 1)
                print(f"  ⏳ 限流，{backoff}s 后重试")
                time.sleep(backoff)
                continue
            raise LLMError(str(e)) from e
    raise LLMError(str(last_err))


def call_cloudflare(
    prompt: str,
    *,
    model: str | None = None,
    system: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 2000,
    timeout: int = 60,
    max_retries: int = 0,
    backoff: int = 2,
    proxies=None,
    session=None,
) -> str:
    """调用 Cloudflare Workers AI。返回模型原始文本；失败抛 LLMError。

    max_retries: 失败后的额外重试次数（总尝试 = max_retries + 1），任何错误都重试。
    proxies: 可选 dict（如 {"http": "http://127.0.0.1:7897"}）用于中国网络访问 CF。
    session: 可选 requests.Session（合并.py 用于连接复用）；不传则每次新建。
    """
    if not CF_ACCOUNT or not CF_TOKEN:
        raise LLMError("Cloudflare 凭据未配置 (CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN)")
    model = model or CF_MODEL
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/{model}"
    body = {
        "messages": [
            *([{"role": "system", "content": system}] if system else []),
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {CF_TOKEN}",
        "Content-Type": "application/json",
    }
    http = session if session is not None else requests
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = http.post(url, json=body, headers=headers, timeout=timeout, proxies=proxies)
            data = resp.json()
            if not data.get("success"):
                raise LLMError(str(data.get("errors", [{}])[0].get("message", "unknown")))
            result = data.get("result", {})
            raw = result.get("response")
            # Qwen3 等新模型返回 OpenAI 兼容格式: choices[].message.content
            if raw is None or not isinstance(raw, str):
                choices = result.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    raw = msg.get("content")
                else:
                    raw = None
            if not raw:
                raise LLMError("empty response")
            return raw
        except LLMError:
            raise
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                print(f"  ⏳ Cloudflare 限流/错误，{backoff}s 后重试")
                time.sleep(backoff)
                continue
            raise LLMError(str(e)) from e
    raise LLMError(str(last_err))


def call_agnes(prompt: str, *, system=None, temperature=0.1, timeout=90, max_tokens=4000, max_retries=1) -> str:
    """调用 Agnes AI（OpenAI 协议兼容，推理模型）。失败抛 LLMError。

    max_tokens 默认 4000：推理模型思考占用上下文预算，需为最终答案预留额度，
    避免答案被截断（详见 call_compatible_llm 说明）。
    """
    return call_compatible_llm(
        prompt,
        api_key=os.environ.get(AGNES["api_key_var"], ""),
        base_url=AGNES["base_url"],
        model=AGNES["model"],
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
    )


def call_mouter(prompt: str, *, system=None, temperature=0.1, timeout=120, max_tokens=2000, max_retries=1) -> str:
    """调用 Mouter AI（翻译专用独立引擎，OpenAI 协议兼容）。失败抛 LLMError。

    与 Cloudflare 英文抽取解耦：翻译独占该引擎额度，避免两者在 Cloudflare
    免费 10k neurons 下撞车导致抽取/翻译互相饿死。

    未配置（MOUTER_BASE_URL 或 MOUTER_MODEL 为空）时明确抛错，而非用空 base_url
    打到 openai.com 默认端点造成难以排查的失败。
    """
    if not MOUTER["base_url"] or not MOUTER["model"]:
        raise LLMError("Mouter AI 未配置 (需设置 MOUTER_BASE_URL 与 MOUTER_MODEL 环境变量)")
    return call_compatible_llm(
        prompt,
        api_key=os.environ.get(MOUTER["api_key_var"], ""),
        base_url=MOUTER["base_url"],
        model=MOUTER["model"],
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
    )
