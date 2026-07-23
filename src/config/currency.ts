/**
 * currency.ts — TopNice 货币换算与格式化
 *
 * 数据里的 pledged / goal 是「带币种」的数值（USD/HKD/EUR/GBP/... 混合），
 * 全站此前直接当纯美元相加，导致聚合金额虚高数倍。
 *
 * 设计（2026-07-23，用户确认）：
 *  - 聚合统计（首页 Total Raised、分类页 raised、排行榜排序）= 折算成 USD 等价后求和/比较；
 *  - 单个项目（卡片 / 详情 / Hero 卡）= 用项目自身币种符号展示原始金额，不篡改。
 *
 * 汇率用静态表（构建时确定）：沙箱无 FX API key、Cloudflare 配额也紧张，实时汇率不可行。
 * rate = 1 单位该币种兑换多少 USD（近似值，需定期更新）。
 */
export const USD_RATES: Record<string, number> = {
  USD: 1,
  HKD: 0.128,
  EUR: 1.08,
  GBP: 1.27,
  CAD: 0.73,
  JPY: 0.0067,
  CHF: 1.12,
  AUD: 0.66,
  SGD: 0.74,
  PLN: 0.25,
  NOK: 0.095,
  MXN: 0.058,
};

/** 折算成 USD 等价（未知币种按 1 处理，不放大也不缩小） */
export function toUsd(amount: number, currency?: string): number {
  const rate = (currency && USD_RATES[currency]) || 1;
  return (amount || 0) * rate;
}

/** USD 等价金额格式化：$1,234 */
export function fmtUsd(n: number): string {
  return "$" + Math.round(n || 0).toLocaleString("en-US");
}

const SYMBOLS: Record<string, string> = {
  USD: "$",
  HKD: "HK$",
  EUR: "€",
  GBP: "£",
  CAD: "C$",
  JPY: "¥",
  CHF: "CHF",
  AUD: "A$",
  SGD: "S$",
  PLN: "zł",
  NOK: "kr",
  MXN: "MX$",
};

/**
 * 取单个项目的展示符号。
 * 以 currency 代码为准（数据权威），currency_symbol 字段常被错填成 "$"（连 HKD 都填 "$"），
 * 故仅当它存在且 currency 代码不在映射里时才作兜底。
 */
export function moneySymbol(currency?: string, currencySymbol?: string): string {
  if (currency && SYMBOLS[currency]) return SYMBOLS[currency];
  if (currencySymbol && String(currencySymbol).trim()) return String(currencySymbol).trim();
  if (currency) return currency + " ";
  return "$";
}

/** 单个项目金额：用其自身币种符号展示原始数值 */
export function fmtMoney(amount: number, currency?: string, currencySymbol?: string): string {
  return moneySymbol(currency, currencySymbol) + Math.round(amount || 0).toLocaleString("en-US");
}
