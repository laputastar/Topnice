# TopNice 产品详情页 — 可用数据清单

> 给设计师的参考：以下数据均已存在于 `projects.json` 中，可在详情页中自由使用。

---

## 一、项目基本信息

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `name` | string | KS/IG API | 项目名称（英文） |
| `nameZh` | string | 翻译管线 | 中文名称（后续翻译） |
| `blurb` | string | KS/IG API | 一句话简介（<200字） |
| `slug` | string | 生成 | URL 标识符 |
| `state` | enum | KS/IG API | `live` / `successful` / `failed` |
| `platform` | enum | 标记 | `kickstarter` / `indiegogo` |
| `url` | string | KS/IG API | 原始项目页链接 |
| `score` | number | 计算 | TopNice 热度评分 0-100 |

---

## 二、产品描述（新增 🔥）

| 字段 | 类型 | 来源 | 数据量 |
|------|------|------|--------|
| `story_markdown` | string (Markdown) | **Firecrawl** | 平均 **46k chars**/项目（含图片、标题、段落） |
| `story_images` | string[] (URL) | **Firecrawl** | 平均 **60 张**/项目 |

**story_markdown 包含的内容：**
- 产品功能介绍（多段落）
- 技术规格参数
- 设计理念 / 品牌故事
- 奖励档位描述
- FAQ / 风险说明
- AI 使用声明 / 环保承诺

**story_images 特点：**
- 原始分辨率为 680×680 或更高
- 可升级为 1024×576 高清版本
- 存储方式：仅存 URL，不存文件

---

## 三、筹款数据

| 字段 | 类型 | 说明 |
|------|------|------|
| `pledged` | number | 已筹金额（原始币种） |
| `goal` | number | 目标金额 |
| `percent_funded` | number | 达成百分比（如 16192%） |
| `backers_count` | number | 支持者人数 |
| `daysLeft` | number | 剩余天数 |
| `currency` | string | 币种代码（HKD / USD / EUR 等） |
| `currency_symbol` | string | 币种符号（$ / € / £） |
| `launched_at` | ISO datetime | 上线时间 |
| `deadline` | ISO datetime | 截止时间 |

---

## 四、创建者信息

| 字段 | 类型 | 覆盖率 | 说明 |
|------|------|--------|------|
| `creator_name` | string | 100% | 创建者/品牌名称 |
| `creator_avatar_medium` | URL | **85%** | 创建者头像（可用） |
| `location` | string | 100% | 城市，国家 |
| `country` | string | 100% | 国家名称（可映射国旗 emoji） |

---

## 五、媒体资源

| 字段 | 说明 |
|------|------|
| `image_1024x576` | 主图高清版（1024×576）⭐ 最佳 |
| `image_full` | 主图中等（315px） |
| `image_med` | 主图小尺寸（153px） |
| `image_thumb` | 缩略图（27px） |
| `video_url` | 项目视频（**174/259** 项目有） |
| `story_images[]` | 产品故事中的额外图片（**平均 60 张**） |

---

## 六、标签与分类

| 字段 | 说明 |
|------|------|
| `category` | KS 子分类（如 Hardware / Gadgets） |
| `parent_category` | 父分类（如 Technology / Design） |
| `topnice_category` | TopNice 统一分类 |
| `staff_pick` | KS 官方推荐 ⭐（18/203 项目） |

---

## 七、IG 特有数据

| 字段 | 覆盖率 | 说明 |
|------|--------|------|
| `comment_count` | 56/56 | 评论数（如 560） |
| `reward_count` | 56/56 | 回报档位数（如 12） |
| `update_count` | 56/56 | 项目更新次数（如 2） |

---

## 八、计算/衍生数据

| 数据 | 计算公式 | 说明 |
|------|----------|------|
| 人均支持额 | `pledged / backers_count` | 衡量项目价值感 |
| 日均筹资 | `pledged / days_since_launch` | 融资速度指标 |
| 超募倍数 | `percent_funded / 100` | 超额完成倍数 |
| 首次追踪日 | `first_seen` | 新鲜度指标 |
| 国旗 emoji | country → 映射表 | 19 个国家已覆盖 |

---

## 设计建议

根据可用数据，详情页可包含以下模块：
1. **Hero**: 高清主图 + 视频播放 + 平台徽章 + Staff Pick
2. **筹款面板**: 金额 / 达成率 / 支持者 / 剩余时间 + 按钮
3. **创建者信息**: 头像 + 名称 + 地点
4. **产品故事**: Markdown 渲染（标题 + 正文 + 图片画廊）
5. **项目洞察**: 评分 / 人均支持 / 追踪时间 / 达成率
6. **Sidebar**: 项目元数据 / 来源 / 币种 / IG 活动数据
7. **相关项目**: 同类推荐
