import { useEffect, useState } from "react";
import { getJSON, type Defaults } from "./api";
import BatchFlow from "./BatchFlow";
import VideoFlow from "./VideoFlow";
import { ErrorBox, Spinner } from "./ui";

export default function App() {
  const [tab, setTab] = useState<"video" | "batch">("video");
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJSON<Defaults>("api/defaults").then(setDefaults).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="app">
      <header className="top">
        <h1>🎭 Charla</h1>
        <nav>
          <button className={tab === "video" ? "on" : ""} onClick={() => setTab("video")}>Crear video</button>
          <button className={tab === "batch" ? "on" : ""} onClick={() => setTab("batch")}>Lote automático</button>
        </nav>
        <span className="muted small" title="Ejecuta .\run-gradio.ps1 para todos los ajustes (chroma, voces, historial, TikTok)">
          Modo avanzado: run-gradio.ps1
        </span>
      </header>
      <main>
        <ErrorBox message={error} />
        {!defaults && !error && <Spinner label="Cargando…" />}
        {/* both stay mounted so switching tabs never loses a running job */}
        {defaults && (
          <>
            <div hidden={tab !== "video"}><VideoFlow defaults={defaults} /></div>
            <div hidden={tab !== "batch"}><BatchFlow defaults={defaults} /></div>
          </>
        )}
      </main>
    </div>
  );
}
