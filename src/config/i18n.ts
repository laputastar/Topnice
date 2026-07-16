// Shared i18n dictionary for UI strings
export const ui = {
  en: {
    siteName: "TopNice",
    tagline: "Discover Amazing New Products",
    search: "Search projects...",
    about: "About Us",
    privacy: "Privacy Policy",
    terms: "Terms of Service",
    langLabel: "中文",
    footerDesc: "Daily Data Tracking · Global Hardware Crowdfunding",
    viewOnKS: "View on Kickstarter",
    viewOnIG: "View on Indiegogo",
    backers: "backers",
    raised: "raised",
    goal: "goal",
    daysLeft: "days left",
    ended: "Ended",
    endedLabel: "This project has ended crowdfunding",
  },
  zh: {
    siteName: "TopNice",
    tagline: "发现新奇产品",
    search: "搜索项目...",
    about: "关于我们",
    privacy: "隐私政策",
    terms: "服务条款",
    langLabel: "EN",
    footerDesc: "每日数据追踪 · 全球硬件众筹",
    viewOnKS: "在 Kickstarter 查看",
    viewOnIG: "在 Indiegogo 查看",
    backers: "支持者",
    raised: "已筹",
    goal: "目标",
    daysLeft: "剩余天数",
    ended: "已结束",
    endedLabel: "本项目已结束众筹",
  },
} as const;

export type Lang = keyof typeof ui;
export type UIStrings = typeof ui.en;
