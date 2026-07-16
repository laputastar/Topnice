import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import tailwindcss from "@tailwindcss/vite";

// https://astro.build/config
export default defineConfig({
  site: "https://topnice.com",
  compressHTML: true,
  integrations: [sitemap({
    i18n: {
      defaultLocale: "en",
      locales: {
        en: "en-US",
        zh: "zh-CN",
      },
    },
    filter: (page) => !page.includes("/search"),
  })],
  vite: {
    plugins: [tailwindcss()],
  },
  i18n: {
    defaultLocale: "en",
    locales: ["en", "zh"],
    routing: {
      prefixDefaultLocale: false,
    },
  },
});
