import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` talks to a running `charla-web` backend on :7870.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:7870",
      "/media": "http://127.0.0.1:7870",
    },
  },
});
