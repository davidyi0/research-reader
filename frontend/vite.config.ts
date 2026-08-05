import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";


export default defineConfig({
  plugins: [react(), tailwindcss()],
  // `host` binds 0.0.0.0 so the dev server is reachable from outside the
  // container; polling is required because file events don't cross a Windows
  // host -> Linux container bind mount, which would otherwise break HMR.
  server: { port: 5173, host: true, watch: { usePolling: true } },
});
