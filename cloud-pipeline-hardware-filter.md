# 云端管线：自动识别非硬件项目方案

## 目标
在每日自动化管线（Cloudflare + GitHub Actions）中，自动识别并排除非硬件项目（如服装、护肤品、香氛、保健品、收藏品、徽章、日志本等），保持 TopNice 聚焦硬件平台定位。

## 当前已有管线 (pipeline.py)

```
fetch-kickstarter.py → raw/kickstarter.json
fetch-indiegogo.py  → raw/indiegogo.json
         ↓
    merge.py (合并/去重/评分/历史快照)
         ↓
    src/data/projects.json → Astro SSG Build → dist/
```

## 建议方案：混合策略

### 阶段 1: 类别预过滤（零成本）

在 `merge.py` 中增加排除规则，直接过滤掉明确非硬件的 KS 类目：

| 类目 | 动作 | 理由 |
|---|---|---|
| Tabletop | 排除 | 桌游，非硬件 |
| Toys | 排除 | 玩具类，非硬件（但 EDC 工具可能落入此处） |
| 3D Printing | 保留 | 3D 打印机本身是硬件 |
| Product Design | 需 AI 判定 | 混入大量非硬件（本次已清除41个） |
| Hardware / Gadgets | 保留 | 本身就是硬件 |

**代码示例**：
```python
# merge.py 中加入
HARDWARE_CATEGORIES = ['Hardware', 'Gadgets', '3D Printing', 'Camera Gear', 'Robotics']
SOFT_CATEGORIES = ['Tabletop', 'Toys']
# Product Design 需进一步判定
```

### 阶段 2: Product Design AI 分类（消耗少量 LLM credits）

对 `category == "Product Design"` 的项目，在 merge 时调用一次 LLM 判定，项目名 + blurb 即可（不需要读全文），准确率 >95%。

**调用时机**：`merge.py` 内调用已有 `ai-extract.py`（LongCat/Agnes）做单次分类。

**Prompt 示例**：
```
Classify the following Kickstarter project as "hardware" or "non-hardware":

Name: {name}
Blurb: {blurb}
Category: Product Design

A hardware project produces a physical manufactured/electronic/mechanical product.
A non-hardware project is: clothing, skincare, fragrance, food, supplements, pet supplies,
stationery, collectibles, art prints, maps, journals, keychains, decor, plush toys, etc.

Answer with exactly one word: "hardware" or "non-hardware"
```

**成本估算**：Product Design 约 199 个项目（上线后可能减少到 ~150 新项目）。
- LongCat：免费额度内足够
- 每项目约 100 tokens → 每天 199 × 100 = ~20K tokens → 远低于免费限额

### 阶段 3: 结果写入

在 `projects.json` 中增加字段：

```json
{
  "hardware_class": "non_hardware",
  "hardware_class_source": "longcat-20260707"
}
```

`astro build` 时过滤掉 `hardware_class == "non_hardware"` 的项目：
```astro
---
const projects = data.projects.filter(p => p.hardware_class !== 'non_hardware');
---
```

## 两种实现路径对比

| 方案 | 准确率 | 成本 | 复杂度 | 推荐度 |
|---|---|---|---|---|
| **A. 全 LLM 分类** | >95% | 低（每日~20K tokens） | 低 | ⭐ 推荐 |
| B. 关键词规则分类 | ~70% | 零 | 低 | 不推荐（漏杀多） |
| C. 混合预过滤 + LLM | >95% | 更低（仅 Product Design 需要 LLM） | 中 | ⭐ 最推荐 |

**推荐方案 C**：类别预过滤（排 Tabletop/Toys） + Product Design 用 LLM 判定。既保证准确率又控制成本。

## 首次部署后

- 首次上线：对现有全部项目跑一次 LLM 分类，打好 `hardware_class` 标记
- 每日增量：每天新拉取的项目只有几到几十个 → 分类成本可忽略
- 在 `merge.py` 结尾加入该步骤，整个流程自动化
