import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: process.env.MOVIEHUB_BASE_PATH ?? "/",
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/moviehub/api": {
        target: process.env.MOVIEHUB_API_PROXY ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/moviehub/, "")
      },
      "/api": {
        target: process.env.MOVIEHUB_API_PROXY ?? "http://127.0.0.1:8000",
        changeOrigin: true
      }
    }
  }
});
