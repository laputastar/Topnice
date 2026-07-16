/**
 * format.ts — TopNice 共用格式化函数
 *
 * 所有 Astro 端格式函数集中管理，避免重复定义。
 * 客户端 JS 仍保留内联定义（无法跨 `<script>` import）。
 */

/** 金额格式化：$1,234 */
export function fm(n: number): string {
  return "$" + Math.round(n || 0).toLocaleString("en-US");
}

/** HTML 转义 */
export function esc(s: unknown): string {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** 项目名称：按语言取 nameZh 或 name */
export function nameOf(p: { nameZh?: string; name: string }, lang: string): string {
  return lang === "zh" ? (p.nameZh || p.name) : p.name;
}

/** 众筹档位类型 */
export interface AiTier {
  name: string;
  price?: number;
  currency?: string;
  price_usd?: number;
  backers: number;
  description?: string;
}
