/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 계약 esl.md §9: 하위 경로 /esl/, API 접두 /esl/api. mock 모드는 fetch 래퍼(src/mock).
export default defineConfig(({ mode }) => ({
  base: "/esl/",
  plugins: [react()],
  define: {
    __MOCK__: JSON.stringify(mode === "mock"),
  },
  server: {
    host: "127.0.0.1",
    port: 5184,
    strictPort: true,
    proxy: mode === "mock" ? undefined : { "/esl/api": { target: "http://127.0.0.1:8200", changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
}));
