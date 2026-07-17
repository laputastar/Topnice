#!/usr/bin/env python3
"""fetch-html 双 provider 降级逻辑测试（纯 mock，不调 live API）。

验证核心 fetch_one() 降级行为：
  1. Firecrawl 成功时优先用 Firecrawl
  2. Firecrawl 额度耗尽时自动降级 Context.dev
  3. 两 provider 均失败时返回 (None, None)
  4. Context.dev 额度为 0 时停止
"""
import os, sys, importlib.util

# 必须在加载 fetch-html 前设 dummy key（模块顶部会据此初始化 dead 标志）
os.environ.setdefault("FIRECRAWL_API_KEY", "dummy-fc")
os.environ.setdefault("CONTEXT_DEV_API_KEY", "dummy-cd")

# fetch-html.py 含连字符，不能用 import 语句，用 importlib 按路径加载
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("fetch_html", os.path.join(_HERE, "fetch-html.py"))
fh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fh)

passed = 0
failed = 0


def _reset():
    fh.firecrawl_dead = not bool(fh.FIRECRAWL_API_KEY)
    fh.contextdev_dead = not bool(fh.CONTEXT_DEV_API_KEY)


def _patch(fc_fn, cd_fn):
    orig = (fh.extract_html_firecrawl, fh.extract_html_contextdev)
    fh.extract_html_firecrawl = fc_fn
    fh.extract_html_contextdev = cd_fn
    return orig


def _restore(orig):
    fh.extract_html_firecrawl, fh.extract_html_contextdev = orig


def _raise_fc(url):
    raise fh.PaymentRequiredError()


def _raise_cd(url):
    raise RuntimeError("contextdev boom")


def run(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"✅ {name}")
    except AssertionError as e:
        failed += 1
        print(f"❌ {name}: {e}")
    except Exception as e:
        failed += 1
        print(f"❌ {name} 抛出异常: {type(e).__name__}: {e}")


def t_fc_success():
    _reset()
    orig = _patch(
        lambda url: {"html_length": 100, "credits": 1, "raw_html": "<html>fc</html>", "credits_remaining": None},
        lambda url: {"html_length": 100, "credits": 1, "raw_html": "<html>cd</html>", "credits_remaining": 500},
    )
    try:
        r, prov = fh.fetch_one("http://x")
        assert prov == "firecrawl", f"期望 firecrawl, 实际 {prov}"
        assert r["raw_html"] == "<html>fc</html>"
        assert fh.firecrawl_dead is False
    finally:
        _restore(orig)


def t_fc_payment_then_cd():
    _reset()
    orig = _patch(
        _raise_fc,
        lambda url: {"html_length": 100, "credits": 1, "raw_html": "<html>cd</html>", "credits_remaining": 499},
    )
    try:
        r, prov = fh.fetch_one("http://x")
        assert prov == "contextdev", f"期望 contextdev, 实际 {prov}"
        assert fh.firecrawl_dead is True
        assert r["raw_html"] == "<html>cd</html>"
    finally:
        _restore(orig)


def t_both_fail():
    _reset()
    orig = _patch(_raise_fc, _raise_cd)
    try:
        r, prov = fh.fetch_one("http://x")
        assert r is None and prov is None
        assert fh.firecrawl_dead and fh.contextdev_dead
    finally:
        _restore(orig)


def t_cd_zero_credits():
    _reset()
    fh.firecrawl_dead = True  # 模拟 Firecrawl 已耗尽，只走 Context.dev 且其额度为 0
    orig = _patch(
        _raise_fc,
        lambda url: {"html_length": 100, "credits": 1, "raw_html": "<html>cd</html>", "credits_remaining": 0},
    )
    try:
        r, prov = fh.fetch_one("http://x")
        assert r is None and prov is None
        assert fh.contextdev_dead is True
    finally:
        _restore(orig)


if __name__ == "__main__":
    run("Firecrawl 成功时优先用 Firecrawl", t_fc_success)
    run("Firecrawl 额度耗尽自动降级 Context.dev", t_fc_payment_then_cd)
    run("两 provider 均失败返回 (None, None)", t_both_fail)
    run("Context.dev 额度为 0 时停止", t_cd_zero_credits)
    print(f"\n通过 {passed} / 失败 {failed}")
    sys.exit(1 if failed else 0)
