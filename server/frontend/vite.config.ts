import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` talks to a running `studio` backend on :7880.
const studio = "http://127.0.0.1:7880";
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": studio, "/m": studio, "/media": studio, "/files": studio } },
});
