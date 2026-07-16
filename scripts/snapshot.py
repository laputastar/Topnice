#!/usr/bin/env python3
"""
snapshot.py — 每日快照管理

只要追加，不删除，不覆盖。
每个 project 维护 history[] 数组:
  history: [
    {"date": "2026-07-02", "backers": 120, "pledged": 260000},
    {"date": "2026-07-03", "backers": 146, "pledged": 320000},
  ]
"""
from datetime import datetime


def today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def append_snapshot(p: dict) -> bool:
    """
    追加当日快照。如果今日已有记录则跳过。
    返回 True 表示追加成功，False 表示跳过（今日已存在）
    """
    history = p.get("history", [])
    date_today = today()

    # 检查今日是否已有记录
    if history and history[-1].get("date") == date_today:
        return False  # 已有今日快照，跳过

    snapshot = {
        "date": date_today,
        "backers": p.get("backers_count", 0),
        "pledged": p.get("pledged", 0),
    }

    history.append(snapshot)

    # 可选：限制历史长度，防止无限膨胀（保留最近 30 天）
    # if len(history) > 30:
    #     history = history[-30:]

    p["history"] = history
    return True


def init_history(p: dict) -> bool:
    """
    为没有 history 的项目初始化第一条快照。
    运行一次即可，后续由 append_snapshot 维护。
    """
    if p.get("history"):
        return False  # 已有历史

    p["history"] = [{
        "date": today(),
        "backers": p.get("backers_count", 0),
        "pledged": p.get("pledged", 0),
    }]
    return True


def batch_append(projects: list) -> dict:
    """批量追加快照，返回统计"""
    stats = {"appended": 0, "initialized": 0, "skipped": 0}
    for p in projects:
        if p.get("platform") != "kickstarter":
            continue
        # 初始化（仅首次）
        if not p.get("history"):
            init_history(p)
            stats["initialized"] += 1
        # 每日追加
        if append_snapshot(p):
            stats["appended"] += 1
        else:
            stats["skipped"] += 1
    return stats
