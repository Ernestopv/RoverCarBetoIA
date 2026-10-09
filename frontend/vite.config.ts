import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies `/api` to the FastAPI backend so the browser only ever
// talks to one origin (no CORS configuration needed).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
