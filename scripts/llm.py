#!/usr/bin/env python3
"""
llm.py — TopNice 数据管线统一 LLM / API 调用层（共享模块）

所有 API Key 仅从环境变量读取，严禁硬编码（防泄露进 git / 分享）。

提供商:
  - Long Cat   (OpenAI 兼容): LONG_CAT_API_KEY  / base https://api.longcat.chat/openai / model LongCat-2.0
  - Agnes AI   (OpenAI 兼容): AGNES_API_KEY     / base https://apihub.agnes-ai.com/v1    / model agnes-2.0-flash
  - Cloudflare Workers AI:     CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID / 模型可配

统一能力:
  - 环境变量只在此处集中读取一次（全管线唯一来源）
  - 统一超时 / 限流(429)退避重试 / 错误归一为 LLMError
  - 所有函数返回模型原始文本(str)；失败时抛 LLMError，由调用方决定 fallback

环境变量:
  LONG_CAT_API_KEY, AGNES_API_KEY, CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID
  可选: CF_TRANSLATE_MODEL (覆盖 CF 默认模型), CF_PROXY (中国网络访问 CF 的本地代理)
"""
import os
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

LONGCAT = {
    "api_key_var": "LONG_CAT_API_KEY",
    "base_url": "https://api.longcat.chat/openai",
    "model": "LongCat-2.0",
    "timeout": 90,
}
AGNES = {
    "api_key_var": "AGNES_API_KEY",
    "base_url": "https://apihub.agnes-ai.com/v1",
    "model": "agnes-2.0-flash",
    "timeout": 90,
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
    max_retries: int = 1,
    retry_rate_limit_only: bool = True,
) -> str:
    """调用 OpenAI 协议兼容端点（LongCat / Agnes）。返回模型原始文本；失败抛 LLMError。

    max_retries: 首次失败后的额外重试次数（总尝试 = max_retries + 1）。
    retry_rate_limit_only=True 时仅在 429 限流时重试（与 ai-extract 旧行为一致）；
    设为 False 则在任何异常时都重试。
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
                timeout=timeout,
            )
            raw = resp.choices[0].message.content
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


def call_longcat(prompt: str, *, system=None, temperature=0.1, timeout=90, max_retries=1) -> str:
    """调用 Long Cat（OpenAI 协议兼容）。失败抛 LLMError。"""
    return call_compatible_llm(
        prompt,
        api_key=os.environ.get(LONGCAT["api_key_var"], ""),
        base_url=LONGCAT["base_url"],
        model=LONGCAT["model"],
        system=system,
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries,
    )


def call_agnes(prompt: str, *, system=None, temperature=0.1, timeout=90, max_retries=1) -> str:
    """调用 Agnes AI（OpenAI 协议兼容）。失败抛 LLMError。"""
    return call_compatible_llm(
        prompt,
        api_key=os.environ.get(AGNES["api_key_var"], ""),
        base_url=AGNES["base_url"],
        model=AGNES["model"],
        system=system,
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries,
    )
