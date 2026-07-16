# TopNice SEO Audit — 快速扫描

| 检查项 | 状态 | 说明 |
|---|---|---|
| **robots.txt** | ✅ Pass | 存在，正确引用 sitemap |
| **Sitemap (XML)** | ✅ Pass | 1683 条 URL，含所有项目 EN/ZH + 品类页 |
| **404 页面** | ✅ Pass | 存在 `/404/` |
| **Title 标签** | ✅ Pass | 各页面均有 title，格式良好（如 `OMNI X1 ... \| TopNice`） |
| **Meta Description** | ✅ Pass | 首页和详情页均有 description |
| **H1 标签** | ✅ Pass | 首页 1 个 H1，详情页 1 个 H1 |
| **Canonical URL** | ⚠️ Warn | 存在但需确认是否正确指向 https://topnice.com |
| **hreflang** | ⚠️ Warn | 首页和详情页有 `en-US` / `zh-CN` 互链，品类页可能缺失 |
| **JSON-LD Schema** | ❌ Fail | 首页 **无结构数据标记**，详情页可能也没有 Product schema |
| **图片 Alt 属性** | ❌ Fail | 详情页大量内容图片 alt 为空（故事中的图片）|
| **Open Graph 标签** | ❌ 超出范围 | 需用 seo-audit-full 确认 |
| **页面速度 / LCP** | ⚠️ 本地无法测 | 上线后用 PageSpeed Insights |

## 详细发现

### 🔴 高危：JSON-LD Schema 缺失
详情页应标记 **Product** 类型 schema（名称、图片、价格、筹款状态等），帮助 Google 理解页面内容并展示丰富结果（富摘要）。

**修复：** 在项目详情页 `<head>` 添加 JSON-LD：
```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "项目名称",
  "image": "项目图片URL",
  "description": "项目简介",
  "offers": {
    "@type": "Offer",
    "price": "筹款金额",
    "priceCurrency": "USD"
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "评分(可选)",
    "reviewCount": "评论数(可选)"
  }
}
```

### 🟠 中危：图片 Alt 属性大量缺失
详情页故事正文中的图片全部没有有意义 alt 文本（90+ 个空 alt）。影响无障碍和图片搜索流量。

**修复：** 在 story_markdown 渲染时为每张图片生成描述性 alt（基于上下文分析文件名或周边文本）。

### 🟡 低危：hreflang 覆盖不全
首页和详情页有 `en-US` / `zh-CN` 互链，但品类页（`/category/gadgets/`）**可能缺少 hreflang**，导致中文品类页未被搜索引擎识别为翻译版。

**修复：** 品类页模板添加 `xhtml:link rel="alternate"` 链接。

### 🟡 低危：Canonical URL 配置
确认 canonical 指向 `https://topnice.com/` 而非 `http://localhost`。由于是静态站，基本不会出现重复内容问题，但 canonical 一致性能避免未来隐患。

### 🟢 好的方面
- 所有项目详情页 title 格式统一 `{name} | TopNice`
- 中英文分离路径清晰（`/project/slug` vs `/zh/project/slug`）
- Sitemap 覆盖全面（1683 条，含 EN + ZH）
- robots.txt 配置正确
- 有 About / Privacy / Terms 信任页面

## 优先级建议

| 优先级 | 事项 | 预估工时 |
|---|---|---|
| P0 | 添加 JSON-LD Schema（Product + WebSite） | 2-4h |
| P1 | 修复故事图片 alt 文本 | 4-8h（需 AI 生成） |
| P2 | 品类页 hreflang 补全 | 0.5h |
| P3 | 考虑添加 Blog 栏目吸引长尾流量 | 长期 |

**注意：** 基础 SEO 框架（robots/sitemap/title/h1/meta）已经就绪，核心缺口是 Schema 和图片 alt——这两项直接影响搜索富摘要展示和图片流量。
