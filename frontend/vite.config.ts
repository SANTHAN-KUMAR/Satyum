import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// The frontend never hardcodes the backend origin (CLAUDE.md §5, §11 — config over hardcoding).
// In dev it proxies /api and /ws to the backend so the browser talks same-origin (cookies/CORS-free),
// mirroring the production Nginx reverse proxy (CLAUDE.md §11: Nginx routes /api /ws /).
// Override the target with SATYUM_BACKEND_ORIGIN in a gitignored .env.local.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendOrigin = env.SATYUM_BACKEND_ORIGIN ?? "http://127.0.0.1:8000";
  const wsTarget = backendOrigin.replace(/^http/, "ws");

  return {
    plugins: [react()],
    resolve: {
      alias: { "@": path.resolve(__dirname, "src") },
    },
    server: {
      port: 5173,
      proxy: {
        "/api": { target: backendOrigin, changeOrigin: true },
        "/ws": { target: wsTarget, ws: true, changeOrigin: true },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            vendor: ['react', 'react-dom', 'react-router-dom', 'lucide-react'],
          },
        },
      },
    },
  };
});
