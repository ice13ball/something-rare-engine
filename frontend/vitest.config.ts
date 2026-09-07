/// <reference types="vitest" />
// Separate from vite.config.ts on purpose — vite.config.ts's rollupOptions/manualChunks
// must stay byte-equivalent for the production bundle, and merging a `test` block in
// risks touching that file by accident on a future edit. vitest.config.ts reuses the
// same plugin so JSX/TSX transforms match what the app actually ships.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // `seo/` is server-side (SSR + sitemap) but its URL encoder is the single
    // point both the sitemap and every canonical tag go through — it needs tests
    // more than most of `src/` does.
    include: ["src/**/*.test.{ts,tsx}", "seo/**/*.test.js"],
  },
});
