import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./remote"; // first: in remote mode it points fetch/EventSource at the server
import App from "./App";
import RemoteGate from "./RemoteGate";
// order matters: Tailwind (Escalera) first, then the scoped plain-CSS sheets
import "./modalities/escalera/index.css";
import "./modalities/conversacion/styles.css";
import "./shell.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RemoteGate>
      <App />
    </RemoteGate>
  </StrictMode>,
);
