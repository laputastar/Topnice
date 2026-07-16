#!/usr/bin/env python3
"""
score.py — TopNice 评分引擎（纯函数，无副作用）

评分 = Static x 0.5 + Momentum x 0.4 + Trend x 0.1

Static 成分:
  - heat (45%): 筹款额 + backers + 完成度（真实热度）
  - execution (25%): 视频、故事、照片、Staff Pick、档位
  - pricing (20%): 档位数量和折扣质量
  - category (10%): 统一 70 分，不按品类差异化

使用方式:
  from scripts.score import compute
  result = compute(project)
  # -> {"score": 78, "static": 68, "momentum": 29, "trend": 5, "heat": 72}
"""
import math


def _category_score(p: dict) -> float:
    """统一品类基础分 (0-100)，所有品类相同"""
    return 70.0


def _heat_score(p: dict) -> float:
    """热度分 — 基于真实筹款数据 (0-100)"""
    pledged = p.get("pledged") or 0
    backers = p.get("backers_count") or 0
    pct = p.get("percent_funded") or 0

    pledge_pts = min(pledged / 10000 * 20, 40)
    backer_pts = min(math.log2(backers + 1) * 3, 30) if backers > 0 else 0
    pct_pts = min(pct / 10, 30) if pct > 0 else 0

    return min(pledge_pts + backer_pts + pct_pts, 100)


def _pricing_score(p: dict) -> float:
    """基于价格档位的分数 (0-100)"""
    tiers = p.get("ai_tiers", [])
    if not tiers:
        return 40

    n_tiers = len(tiers)
    tier_score = min(n_tiers * 8, 40)

    discount_keywords = ["save", "early bird", "discount", "off", "limited"]
    discount_score = 0
    for t in tiers:
        desc = (t.get("description", "") + t.get("name", "")).lower()
        for kw in discount_keywords:
            if kw in desc:
                discount_score += 3
                break
    discount_score = min(discount_score, 30)

    msrp_score = 0
    for t in tiers:
        desc = (t.get("description", "") + t.get("name", "")).lower()
        if "msrp" in desc or "retail" in desc:
            msrp_score = 30
            break

    return min(tier_score + discount_score + msrp_score, 100)


def _execution_score(p: dict) -> float:
    """基于执行力的分数 (0-100)"""
    score = 0

    if p.get("staff_pick"):
        score += 25
    if p.get("video_url"):
        score += 20

    story = p.get("html_story", "")
    if len(story) > 1000:
        score += 20
    elif len(story) > 200:
        score += 10

    if p.get("ai_tiers"):
        score += 20

    gallery = p.get("html_gallery", [])
    if len(gallery) >= 8:
        score += 15
    elif gallery:
        score += 8

    return min(score, 100)


def static_score(p: dict) -> float:
    """静态基础分 (0-100) — 真实数据驱动"""
    return (
        _heat_score(p) * 0.45 +
        _execution_score(p) * 0.25 +
        _pricing_score(p) * 0.20 +
        _category_score(p) * 0.10
    )


def momentum_score(h: list) -> float:
    """动态动量分 — 基于 backers/pledged history"""
    if len(h) < 2:
        return 0

    last = h[-1]
    prev = h[-2]

    backers_growth = max(last.get("backers", 0) - prev.get("backers", 0), 0)
    pledged_growth = max(last.get("pledged", 0) - prev.get("pledged", 0), 0)
    growth_rate = backers_growth / max(prev.get("backers", 1), 1)

    b_score = math.log(backers_growth + 1) * 10
    r_score = growth_rate * 50
    p_score = math.log(pledged_growth + 1) * 8

    return min((b_score + r_score + p_score) / 2, 60)


def trend(h: list) -> int:
    """趋势修正 (-5 / 0 / +5)"""
    if len(h) < 3:
        return 0

    g1 = h[-1].get("backers", 0) - h[-2].get("backers", 0)
    g2 = h[-2].get("backers", 0) - h[-3].get("backers", 0)

    if g1 > g2:
        return 5
    elif g1 < g2:
        return -5
    return 0


def compute(p: dict) -> dict:
    """
    输入单个 project dict，返回评分结果
    输出: {"score": int, "static": float, "momentum": float, "trend": int, "heat": float}
    """
    s = static_score(p)
    h = p.get("history", [])
    m = momentum_score(h)
    t = trend(h)

    if len(h) >= 2:
        score = s * 0.5 + m * 0.4 + t * 0.1
    else:
        score = s

    return {
        "score": min(100, max(0, int(round(score)))),
        "components": {
            "static": round(s, 1),
            "momentum": round(m, 1),
            "trend": t,
            "heat": round(_heat_score(p), 1),
        },
    }


def batch_compute(projects: list) -> list:
    """批量计算所有项目评分，返回更新后的列表"""
    for p in projects:
        result = compute(p)
        p["score"] = result["score"]
        p["score_components"] = result["components"]
    return projects
