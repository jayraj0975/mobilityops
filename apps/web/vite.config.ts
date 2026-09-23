/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// The dev server proxies the API so the browser only ever talks to one origin. If the API is
// protected by MOBILITYOPS_API_KEY, the proxy adds the header here, server-side: the key is never
// part of the bundle that ships to the browser.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.MOBILITYOPS_API_URL || "http://127.0.0.1:8000";
  const key = env.MOBILITYOPS_API_KEY;
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target,
          changeOrigin: true,
          headers: key ? { "X-API-Key": key } : undefined,
        },
        "/health": target,
        "/ready": target,
      },
    },
    build: { sourcemap: false, target: "es2022" },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: false,
    },
  };
});
