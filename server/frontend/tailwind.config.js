/** @type {import('tailwindcss').Config} */
// Tailwind is only used by the Escalera modality; the shell and Conversación
// use plain CSS (scoped under .shell / .charla), so only its files are scanned.
export default {
  content: ["./src/modalities/{escalera,cuento}/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: { extend: {} },
  plugins: [],
};
