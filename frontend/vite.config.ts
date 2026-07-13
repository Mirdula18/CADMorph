import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy so the SPA and API are same-origin (FR-016 posture in production).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
