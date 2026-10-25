import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
// order matters: Tailwind (Escalera) first, then the scoped plain-CSS sheets
import "./modalities/escalera/index.css";
import "./modalities/conversacion/styles.css";
import "./shell.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
