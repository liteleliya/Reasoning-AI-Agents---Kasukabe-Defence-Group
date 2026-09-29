import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The Python server (uv run python -m server --demo) listens on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
