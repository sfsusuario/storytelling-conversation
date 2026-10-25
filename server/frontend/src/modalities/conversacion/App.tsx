import { useEffect, useState } from "react";
import { getJSON, type Defaults } from "./api";
import History from "../../History";
import BatchFlow from "./BatchFlow";
import VideoFlow from "./VideoFlow";
import { ErrorBox, Spinner } from "./ui";

export default function App() {
  const [tab, setTab] = useState<"video" | "batch" | "history">("video");
  const [prefill, setPrefill] = useState<{ topic: string; n: number } | undefined>();
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJSON<Defaults>("/m/conversacion/api/defaults").then(setDefaults).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="app">
      <header className="top">
        <h1>🎭 Charla</h1>
        <nav>
          <button className={tab === "video" ? "on" : ""} onClick={() => setTab("video")}>Crear video</button>
          <button className={tab === "batch" ? "on" : ""} onClick={() => setTab("batch")}>Lote automático</button>
          <button className={tab === "history" ? "on" : ""} onClick={() => setTab("history")}>📼 Historial</button>
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
            <div hidden={tab !== "video"}><VideoFlow defaults={defaults} prefill={prefill} /></div>
            <div hidden={tab !== "batch"}><BatchFlow defaults={defaults} /></div>
            {tab === "history" && (
              <History
                modalities={[]}
                only="conversacion"
                onOpen={() => setTab("video")}
                onReuse={(_, r) => {
                  if (r.kind === "prefill") setPrefill((p) => ({ topic: r.input, n: (p?.n ?? 0) + 1 }));
                  setTab("video");
                }}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}
