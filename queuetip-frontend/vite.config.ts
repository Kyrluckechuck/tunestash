import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { TanStackRouterVite } from "@tanstack/router-vite-plugin";

// Mirror TuneStash's frontend/vite.config.ts pattern: proxy backend paths
// through the Vite dev server so the browser always sees a single origin.
// This eliminates the CORS/cookie/OAuth-allowlist friction of pointing the
// browser directly at the backend port.
//
// In dev, the queuetip backend is reachable on the Docker network as
// http://queuetip:5000. Production uses nginx to serve the static build
// and proxy /graphql + /auth.
//
// The /auth proxy preserves X-Forwarded-Host so OAuth redirect-URI detection
// builds URLs the browser can actually reach (matching what's whitelisted
// in the Spotify dashboard).
const BACKEND_TARGET = process.env.QUEUETIP_BACKEND_TARGET ?? "http://queuetip:5000";

export default defineConfig({
  plugins: [TanStackRouterVite(), react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    host: "0.0.0.0",
    port: 3001,
    proxy: {
      "/graphql": {
        target: BACKEND_TARGET,
        changeOrigin: true,
        rewrite: (p) => p,
      },
      "/auth": {
        target: BACKEND_TARGET,
        changeOrigin: true,
        rewrite: (p) => p,
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            // Preserve the browser-facing host so the backend can build OAuth
            // redirect URIs that match the Spotify dashboard whitelist.
            const originalHost = req.headers.host;
            if (originalHost) {
              proxyReq.setHeader("X-Forwarded-Host", originalHost);
              proxyReq.setHeader("X-Forwarded-Proto", "http");
            }
          });
        },
      },
      // Only proxy actual m3u downloads to the backend. The frontend has its
      // own /exports/<id> route (the export detail page) — proxying that
      // would 404 because the backend only registers /exports/<id>.m3u.
      "^/exports/.+\\.m3u$": {
        target: BACKEND_TARGET,
        changeOrigin: true,
        rewrite: (p) => p,
      },
      "/health": {
        target: BACKEND_TARGET,
        changeOrigin: true,
        rewrite: (p) => p,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
});
