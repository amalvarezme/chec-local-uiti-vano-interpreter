import { defineConfig } from "astro/config";

const base = process.env.BASE_PATH ?? "/chec-local-uiti-vano-interpreter/";

export default defineConfig({
  site: "https://jclugor.github.io",
  base,
  output: "static"
});
