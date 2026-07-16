# TopNice 数据架构文档 & 缺口清单

_2026-07-07 确认稿_

---

## 一、目录结构总览

```
topnice/
├── src/                          ← 前端源码 (Astro)
│   ├── components/               │   11 个 UI 组件
│   ├── config/                   │   类别 & 国际化配置
│   │   ├── categories.ts         │
│   │   └── i18n.ts               │
│   ├── data/                     │   核心数据文件
│   │   ├── projects.json         │   584 项目主数据 (18MB)
│   │   └── projects.ts           │   TypeScript 类型定义
│   ├── layouts/
│   │   └── Layout.astro          │   全局布局 (含 theme toggle)
│   ├── pages/                    │   12 页面 (6en + 6zh)
│   │   ├── index.astro           │   首页
│   │   ├── project/[slug].astro  │   详情页 (KS/IG 统一模板)
│   │   ├── zh/                   │   中文版 (残页，缺数据)
│   │   └── ...
│   ├── styles/
│   │   └── global.css            │   Tailwind + 暖橙品牌色
│   └── components/
│       ├── ProjectCard.astro     │   首页项目卡片
│       ├── Navbar.astro          │   导航栏
│       ├── Footer.astro          │   页脚
│       └── ...
├── scripts/                      ← 数据管线 (Python)
│   ├── pipeline.py               │   每日编排入口
│   ├── merge.py                  │   核心合并引擎
│   ├── score.py                  │   评分引擎
│   ├── snapshot.py               │   历史快照
│   ├── fetch-html.py             │   Firecrawl 抓取 HTML
│   ├── validate-tiers.py         │   档位守卫 (QA 关卡)
│   ├── validate-ai-data.py       │   AI 数据校验
│   └── parse-ks-tiers.py         │   KS 档位解析 (待 AI 覆盖)
├── raw/                          ← 原始数据 (scripts/raw/)
│   ├── kickstarter.json          │   KS Discover API dump (885 项目)
│   ├── indiegogo.json            │   IG Public API dump (175 项目)
│   └── html/                     │   558 个 .html.gz 快照
├── dist/                         │   构建产出 (1178 页)
├── demo/                         │   自创 demo (残留，待删)
└── node_modules/                 │   依赖
```

---

## 二、数据流 (Pipeline)

```
                                pipeline.py (每日编排)
                                       │
        ┌──────┬───────┬───────┬───────┘
        ▼      ▼       ▼       ▼
  fetch-ks    fetch-ig  fetch-html  merge.py
     │         │         │         │
     ▼         ▼         ▼         ├─ 合并 KS+IG 数据
  raw/       raw/       raw/html/  ├─ 去重
  kickstarter.json  indiegogo.json ├─ 历史快照 (snapshot.py)
                                   ├─ 评分 (score.py)
                                   └─ 标记 ended
                                       │
                                       ▼
                                 src/data/projects.json
                                       │
                                       ▼
                                 Astro SSG Build
                                       │
                                       ▼
                                  dist/ (1178 pages)
```

**关键路径**：
- 原始数据层：`raw/kickstarter.json` + `raw/indiegogo.json` + `raw/html/*.html.gz`
- 合并层：`merge.py` → `projects.json`
- AI 内容层：多个独立脚本填充 `ai_*` 字段 → `projects.json`
- 展示层：Astro SSG → `dist/`

---

## 三、projects.json 完整字段清单

### 3.1 核心标识 (100% 填充)

| 字段 | 类型 | 用途 | 完成度 |
|---|---|---|---|
| `id` | string | 唯一标识 (eg. ks-1571821629) | 584/584 |
| `slug` | string | URL 友好标识 (eg. helia-pillbox) | 584/584 |
| `name` | string | 项目名称 | 584/584 |
| `blurb` | string | 一句话标语 (hero 区使用) | 584/584 |
| `platform` | "kickstarter"\|"indiegogo" | 来源平台 | 584/584 |
| `state` | "live"\|"ended"\|... | 项目状态 | 584/584 |

### 3.2 资金数据 (90–100%)

| 字段 | 类型 | 用途 | 完成度 |
|---|---|---|---|
| `goal` | number | 目标金额 | 573/584 |
| `pledged` | number | 已筹金额 | 531/584 |
| `backers_count` | number | 支持人数 | 531/584 |
| `percent_funded` | number | 达成百分比 | 520/584 |
| `currency` | string | 币种代码 (USD/HKD/...) | 584/584 |

### 3.3 时间数据 (100%)

| 字段 | 类型 | 用途 | 完成度 |
|---|---|---|---|
| `launched_at` | ISO datetime | 发起时间 | 584/584 |
| `deadline` | ISO datetime | 截止时间 | 584/584 |
| `daysLeft` | — | **运行时动态计算** (不在 JSON 中) | — |

### 3.4 创建者与媒体 (70–100%)

| 字段 | 类型 | 用途 | 完成度 |
|---|---|---|---|
| `creator_name` | string | 创建者/团队名 | 584/584 |
| `image_full` | string | 项目主图 URL | 584/584 |
| `video_url` | string | 宣传视频 URL | 394/584 |
| `url` | string | 原站链接 | 584/584 |
| `category` | string | 品类 (eg. Product Design) | 513/584 |
| `reward_count` | number | 回报档位数量 | 71/584 |

### 3.5 AI 内容字段 —— **关键缺口所在**

| 字段 | 类型 | 用途 | 完成度 | 缺口 |
|---|---|---|---|---|
| `ai_intro_en` | string | 简介 (1-2句) | 574/584 | 10 缺 |
| `ai_highlights_en` | string[] | 亮点列表 | 574/584 | 10 缺 |
| `ai_specs_en` | `[["L","V"],...]` | 规格表 | 574/584 | 10 缺 |
| `ai_risks_en` | string | 风险说明 | 574/584 | 10 缺 |
| `ai_creator_bio_en` | string | 创建者简介 | 574/584 | 10 缺 |
| **`ai_description_en`** | **string** | **产品详细描述 (多段)** | **2/584** | **🔴 最大缺口** |
| `ai_tiers` | object[] | 档位列表 | 565/584 | 19 缺 |
| `ai_source` | string | 数据来源标记 | 499/584 | 85 缺 |
| `ai_validated` | boolean | AI 数据完整性标记 | 558/584 | 26 缺 |

### 3.6 评分与原始数据

| 字段 | 类型 | 用途 | 完成度 |
|---|---|---|---|
| `score` | number | 热度评分 (0–100) | 543/584 |
| `raw_html_hash` | string | HTML 快照 SHA256 摘要 | 583/584 |
| `raw_html_path` | string | HTML 快照路径 | **0/584** |

---

## 四、脚本清单

### 核心管线

| 脚本 | 用途 | 状态 |
|---|---|---|
| `pipeline.py` | 每日编排入口 | 完成 |
| `merge.py` | 合并 KS/IG 数据、去重、评分、标 ended | 完成 |
| `score.py` | 热度评分: Static×0.4 + Momentum×0.5 + Trend×0.1 | 完成 |
| `snapshot.py` | 每日快照 (history[] arrays) | 完成 |
| `fetch-html.py` | Firecrawl 抓取 HTML (幂等: 已存在则跳过) | 完成 |

### AI 内容

| 脚本 | 用途 | 状态 |
|---|---|---|
| `ai-extract.py` | LongCat/Agnes AI 抽取 (上线后启用) | 待上线 |
| `local-extract.py` | 本地规则解析 (已背 AI 规则禁用，待重构) | **待重构 |
| `merge_desc.py` | 合并 ai_description_en | 原型 |
| `merge_agent_read.py` | 合并 AI 读取结果 | 原型 |

### QA 守卫

| 脚本 | 用途 | 状态 |
|---|---|---|
| `validate-tiers.py` | 档位完整性检查 (IG 精确/Ks 软检查) | ✅ 落地 |
| `validate-ai-data.py` | AI 字段完整性检查 + 写 ai_validated | ✅ 落地 |

### 遗留/残留

| 脚本 | 用途 | 状态 |
|---|---|---|
| `fetch-ks-tiers.py` | Firecrawl 抓 KS 档位 (用 AI 读取代) | ⛔ 废弃 |
| `parse-ks-tiers.py` | BeautifulSoup 解析 KS 档位 (违规) | ⛔ 待删 |
| `gen_demo.py` | 生成玻璃态 demo 页 (用户未确认) | 待删 |
| `recrawl-bios.py` | 重抓创始人页 (一次性的) | 完成 |

---

## 五、页面模板清单

| 页面 | 路由 | 状态 |
|---|---|---|
| 首页 | `/` | ✅ 基本版 |
| 项目详情页 | `/project/[slug]` | ✅ KS/IG 统一模板，暖橙主题，theme toggle |
| 关于 | `/about` | ✅ |
| 隐私 | `/privacy` | ✅ |
| 条款 | `/terms` | ✅ |
| 404 | `/404` | ✅ |
| **品类页** | — | 🔴 缺失 |
| 中文版首页 | `/zh/` | ⚠️ 有模板无数据 |
| 中文详情页 | `/zh/project/[slug]` | ⚠️ 有模板无数据 |

---

## 六、缺口清单（按优先级）

### P0 — 影响产品体验

| # | 缺口 | 影响 | 解决路径 |
|---|---|---|---|
| 1 | **`ai_description_en` 缺失 (582/584)** | 详情页 About 区只有短回退文本 | 我逐批读 HTML 生成描述 |
| 2 | **3 KS 空档位** (pengo, general-watch, fresh) | 3 项目无档位展示 | 我用 AI 读它们的原始 HTML 确认是否有档位 |
| 3 | **16 IG 空档位** (多为 0-2 backers) | 16 项目无档位展示 | 我用 AI 读它们的原始 HTML + IG perk 目录确认是"真无档位"还是"漏抓" |

### P1 — 功能缺失

| # | 缺口 | 说明 |
|---|---|---|
| 4 | 品类页 | 聚合站核心导航，数据已有 (category/parent_category) |
| 5 | 中文版数据 | /zh/ 有 6 页模板但无项目数据，自动跳转已禁用 |

### P2 — 可优化

| # | 缺口 | 说明 |
|---|---|---|
| 6 | 残留文件 | `demo/` + `gen_demo.py` 待删；`parse-ks-tiers.py` 待替换为 AI 读取 |
| 7 | 非 Git 仓库 | 无版本管理 |
| 8 | 97 个 `ai_source=None` | 未被抽取步骤碰过，可能缺部分字段 |
| 9 | 26 个 ended 未 `ai_validated` | 标记为 true 即可 (已有数据) |

---

## 七、存档的规则

_每次读取原始 HTML 均须遵守_

1. **AI 优先**：任何从原始 HTML 读取数据，必须使用 AI 能力（读原文、理解内容、提取字段），禁止规则解析器
2. **来源标注**：所有 AI 产出的数据必须标明来源
3. **不编造**：页面缺失的信息留空，不能编造
4. **先备份后修改**：修改 `projects.json` 前必须 `cp projects.json.bak`
5. **逐批确认**：批量操作先用 `--limit 1` 测试，确认后再全量
