import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `make dev` passes the port the comfylens server took through COMFYLENS_PORT.
const backend = `http://127.0.0.1:${process.env.COMFYLENS_PORT ?? "8765"}`;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // Served by the Python process; generated and gitignored.
    outDir: fileURLToPath(new URL("../src/comfylens/web", import.meta.url)),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    proxy: { "/api": backend, "/thumbs": backend },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
