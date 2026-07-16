# 详情页内容来源 & 翻译需求清单

## 一、数据来源文件

详情页所有内容来自以下文件：

### 1. `src/data/projects.json`（原始数据）
这是所有项目数据的唯一源头。详情页 `[slug].astro` 通过 `import { allProjects } from "../../data/projects"` 导入。

### 2. `src/data/projects.ts`（类型定义 + 透传）
从 `projects.json` 读取，提供 TypeScript 类型，导出 `allProjects` 数组供 Astro 页面使用。

### 3. `src/pages/project/[slug].astro`（模板文件）
从 `allProjects` 中取单个 `project` 对象，渲染到 HTML。

---

## 二、详情页每个区块的内容来源

### Hero 区域

| 区块 | 数据字段 | 来源 |
|---|---|---|
| 主图 | `project.image_1024x576` / `image_med` | 原始数据 |
| 视频（KS） | `project.video_url` | 原始数据 |
| 品类标签 | `project.topnice_category` / `project.category` | 原始数据 |
| **项目标题** 🈶 | `project.name` | 原始数据（英文） |
| Blurb 简介 🈶 | `project.blurb` | 原始数据（英文） |
| 筹款金额 | `project.pledged` | 原始数据（数字） |
| Goal / 平台标签 | `project.goal`, `project.platform` | 原始数据 |
| 支持者数量 | `project.backers_count` | 原始数据（数字） |
| 剩余天数 | `project.deadline → daysLeft 计算` | 原始数据（时间戳） |
| 档位数 | `ai_tiers.length` | AI 提取（英文名称）|
| CTA 按钮 | `project.url`, `project.platform` | 原始数据 |

### About This Project 区域

| 区块 | 数据字段 | 来源 |
|---|---|---|
| **AI 详细描述** 🈶 | `project.ai_description_en` | AI 提取（英文） |
| **AI 简短介绍** 🈶（降级用）| `project.ai_intro_en` | AI 提取（英文） |
| **Key Highlights** 🈶 | `project.ai_highlights_en` | AI 提取（英文） |
| **Technical Specs** 🈶 | `project.ai_specs_en` | AI 提取（英文） |
| **Reward Tiers** 🈶 | `project.ai_tiers` | AI 提取（名字/描述为英文） |
| **Risks & Challenges** 🈶 | `project.ai_risks_en` / `ai_risks_structured_en` | AI 提取（英文） |
| TopNice Score | `project.score` | 评分引擎（数字） |
| Avg Pledge | `project.pledged / backers_count` | 计算（数字） |
| Tracked Since | `project.first_seen` | 原始数据（日期） |
| Project Updates | `project.url + "/posts"` | 原始数据（链接） |

### 侧边栏

| 区块 | 数据字段 | 来源 |
|---|---|---|
| **Creator Bio** 🈶 | `project.ai_creator_bio_en` | AI 提取（英文） |
| 创造者名称 | `project.creator_name` | 原始数据 |
| 头像 | `project.creator_avatar_medium` | 原始数据 |
| 创建地点 | `project.location` / `project.country` | 原始数据 |
| Launch / Deadline | `project.launched_at` / `project.deadline` | 原始数据（时间戳）|
| 币种 | `project.currency` / `currency_symbol` | 原始数据 |

### Related 区域

| 区块 | 数据字段 | 来源 |
|---|---|---|
| 相关项目标题 | `rp.name` | 原始数据 |
| 相关项目图片 | `rp.image_full` | 原始数据 |
| 相关项目品类 | `rp.topnice_category` | 原始数据 |
| 相关项目金额 | `rp.pledged` | 原始数据 |

## 三、需要翻译的内容清单

### 🅰 项目级字段（275 个项目，每个 8 个字段）

| # | 字段名 | 类型 | 示例（EN → ZH） |
|---|---|---|---|
| 1 | `name` → `nameZh` | 字符串 | "OMNI X1: Beyond Real Strength..." → "OMNI X1：超越真实力量..." |
| 2 | `ai_intro_en` → `ai_intro_zh` | 字符串（1段） | "Helix is a self-watering plant pot..." → 中文 |
| 3 🌟 | `ai_description_en` → `ai_description_zh` | 字符串数组（多段） | 最长的字段，1-5段 |
| 4 | `ai_highlights_en` → `ai_highlights_zh` | 字符串数组（3-5条） | 每条一个亮点 |
| 5 | `ai_specs_en` → `ai_specs_zh` | 二维数组 [label, value] | 标签和值都要翻译 |
| 6 | `ai_risks_en` → `ai_risks_zh` | 字符串（1-2段） | 风险说明 |
| 7 | `ai_risks_structured_en` → `ai_risks_structured_zh` | 二维数组 [title, desc] | 如果有结构化风险，title+desc都要翻译 |
| 8 | `ai_creator_bio_en` → `ai_creator_bio_zh` | 字符串（1-2句） | 创始人简介 |

> 🌟 `ai_description_en` 是详情页最大块的正文，分段存储。需要确保 AI 输出的格式（分段）与原文一致。

### 🅱 档位字段（每个项目 2-5 个，总计 ~600 个）

`ai_tiers` 数组中的每个 tier 对象：

| 子字段 | 需要翻译？ |
|---|---|
| `tier.name` | ✅ 是（如 "Early Bird - 48GB+1TB"） |
| `tier.description` | ✅ 是（如 "Includes the device, charger, and case"） |
| `tier.price` | ❌ 数字，不翻译 |
| `tier.price_usd` | ❌ 数字，不翻译 |
| `tier.currency` | ❌ 符号，不翻译 |
| `tier.backers` | ❌ 数字，不翻译 |

### 🅲 固定 UI 文案（~20 条，硬编码在模板中）

以下英文文案仅在 EN 详情页使用，ZH 详情页应该替换为中文。**不在 projects.json 中，在模板文件里写死：**

- "About This Project" / "Key Highlights" / "Technical Specs" / "Reward Tiers" / "Risks & Challenges"
- "Project Insights" / "TopNice Score" / "Avg. Pledge per Backer" / "Tracked Since" / "Funded"
- "Creator" / "Project Info" / "Platform" / "Launched" / "Deadline" / "Backers" / "Origin" / "Currency"
- "Related Projects" / "Project Updates" / "backers" / "days to go" / "reward tiers"
- "This project has ended crowdfunding"
- CTA 按钮文字

### 🅳 不需要翻译的纯数据字段

| 字段 | 原因 |
|---|---|
| `pledged` / `goal` / `backers_count` / `score` | 数字，全球化 |
| `deadline` / `launched_at` | 时间戳，由 JS 格式化 |
| `currency` / `currency_symbol` | 币种符号不变 |
| `image_*` / `video_url` / `creator_avatar_*` | URL/文件，不变 |
| `platform` / `url` / `slug` | 标识符，不变 |
| `state` / `country` / `location` | 枚举值，不变 |

## 翻译规则

**确认日期：** 2026-07-13

| 规则 | 内容 |
|---|---|
| **项目名称** | 品牌名/型号保留英文，副标题翻中文。例：`"OMNI X1: ..." → "OMNI X1：..."` |
| **技术术语** | 单位/协议/型号不翻（48GB、USB-C），配件/材料/颜色翻（充电盒、铝合金）|
| **档位名称** | 前半描述翻中文（"Early Bird"→"早鸟优惠"），型号保留 |
| **语气风格** | 忠实转换语言，不额外润色/夸大 |
| **ai_description 分段** | 分段数必须与英文一致，不合并不拆分 |
| **后处理清洗** | 删 AI 注释、首尾空格；空译文标 error；长度校验（30%~200%）|

### 固定术语对照表

| 英文 | 中文 |
|---|---|
| Early Bird | 早鸟优惠 |
| Super Early Bird | 超级早鸟 |
| Limited Edition | 限量版 |
| Kickstarter | Kickstarter |
| Indiegogo | Indiegogo |
| crowdfunding | 众筹 |
| backer(s) | 支持者 |
| reward tier | 回报档位 |
| estimated delivery | 预计发货 |

## 四、工作量估算

| 类型 | 数量 | 翻译量估计 |
|---|---|---|
| 🅰 项目文本字段 | 275 × 8 = **2,200 条** | ~50 万 tokens |
| 🅱 档位名称/描述 | ~600 条 | ~15 万 tokens |
| 🅲 固定 UI 文案 | ~20 条 | 手动翻译，5 分钟 |
| **合计** | **~2,820 条** | **~65 万 tokens** |

