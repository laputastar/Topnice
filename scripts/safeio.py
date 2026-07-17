#!/usr/bin/env python3
"""safeio — 原子 JSON 写 + 损坏自动回退。

为什么需要它：
  TopNice 流水线里 projects.json 是全站唯一核心产物，raw/*.json、html/*.gz
  是计费抓取的结果。任何一步用 open(path,'w') 直接截断写，一旦进程在
  写一半崩溃（OOM / 异常 / CI 超时），文件当场损坏，下一轮读取即连锁崩，
  且 workflow 的「if: always() 最终提交」会把损坏文件直接 push 上 main。

  atomic_write_json：
    1. 先写 *.tmp 临时文件 + fsync（落盘）
    2. 再用 os.replace 原子替换原文件（POSIX 下 rename 是原子的）
    → 中途崩溃只会留下一个 *.tmp，原文件完好无损。
    → backup=True 时，替换前把旧文件复制为 *.bak（= 上一版好数据），
       作为「读时损坏」的兜底。

  load_json_safe：
    主文件读取失败时，自动回退到 *.bak；都失败才把原始异常抛出。
"""
import json
import os
import shutil
from pathlib import Path


def atomic_write_json(path, obj, backup: bool = True, indent: int = 2) -> bool:
    """原子写 JSON。中途崩溃只留 *.tmp，原文件完好。返回 True。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
        f.flush()
        os.fsync(f.fileno())  # 确保数据落盘，避免 CI 被杀时 tmp 不全
    os.replace(tmp, path)  # 原子替换：要么旧文件，要么完整新文件
    return True


def load_json_safe(path):
    """读 JSON；主文件损坏自动回退 *.bak；都失败抛原异常。"""
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        bak = path.with_suffix(path.suffix + ".bak")
        if bak.exists():
            print(f"  [safeio] {path.name} 读取失败，回退到 {bak.name}")
            with open(bak, "r", encoding="utf-8") as f:
                return json.load(f)
        raise
