import { defineConfig } from "astro/config";

const base = process.env.BASE_PATH ?? "/CHECUNAL_2026/";

export default defineConfig({
  site: "https://amalvarezme.github.io",
  base,
  output: "static"
});
