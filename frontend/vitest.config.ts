import { defineConfig } from "vitest/config";

export default defineConfig({
  root: process.cwd(),
  esbuild: { jsx: "automatic" },
  resolve: { alias: { "@": process.cwd() } },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    clearMocks: true,
  },
});
