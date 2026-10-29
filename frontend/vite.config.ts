import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import viteCompression from "vite-plugin-compression";

export default defineConfig({
  plugins: [
    react(),
    // Pre-compress all text assets at build time — server serves .gz directly
    viteCompression({ algorithm: "gzip", ext: ".gz" }),
    viteCompression({ algorithm: "brotliCompress", ext: ".br" }),
  ],
  server: {
    // Mirrors server.js's production proxy (createProxyMiddleware with
    // pathRewrite: { '^/api': '' }) — the backend has no /api routes, only
    // /v1, /v2, /admin, so the /api prefix must be stripped here too.
    // Port is configurable via BACKEND_PORT for a backend running elsewhere;
    // 8765 matches `uvicorn main:app --reload --port 8765` from the README.
    proxy: {
      "/api": {
        target: `http://localhost:${process.env.BACKEND_PORT || 8765}`,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  build: {
    // maplibre-gl v4 and deck.gl v9 require Safari 15+ (WebGL2 + ES module workers)
    target: ["es2020", "safari15"],
    chunkSizeWarningLimit: 950,
    rollupOptions: {
      output: {
        // Keep model-only geometry/GLTF dependencies out of the default map.
        manualChunks(id) {
          if (/node_modules\/(?:@deck.gl\/mesh-layers|@loaders.gl\/gltf|@luma.gl\/gltf)\//.test(id)) return "object-models";
          if (/node_modules\/@deck.gl\/(core|layers|geo-layers|react)\//.test(id)) return "vendor-deckgl";
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return "vendor-react";
          if (id.includes("node_modules/maplibre-gl/")) return "vendor-maplibre";
          if (id.includes("node_modules/@turf/")) return "vendor-turf";
          if (id.includes("node_modules/zustand/")) return "vendor-zustand";
        },
      },
    },
  },
});
