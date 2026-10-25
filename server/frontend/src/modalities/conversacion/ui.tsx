import { useEffect, useState } from "react";
import { getJSON, type Idea, type JobEvent } from "./api";

export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="stepper">
      {steps.map((label, i) => (
        <li key={label} className={i < current ? "done" : i === current ? "active" : ""}>
          <span className="dot">{i < current ? "✓" : i + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  );
}

export function CopyButton({ text, label = "Copiar" }: { text: string; label?: string }) {
  const [ok, setOk] = useState(false);
  return (
    <button
      className="ghost"
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setOk(true);
          setTimeout(() => setOk(false), 1500);
        });
      }}
    >
      {ok ? "✓ Copiado" : label}
    </button>
  );
}

export function LogPanel({ events }: { events: JobEvent[] }) {
  const lines = events.filter((e) => e.text).map((e) => e.text);
  return (
    <details className="log">
      <summary>Ver detalle ({lines.length} líneas)</summary>
      <pre>{lines.slice(-300).join("\n")}</pre>
    </details>
  );
}

export function ErrorBox({ message }: { message: string | null }) {
  return message ? <div className="error">⚠ {message}</div> : null;
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="spinner-row">
      <span className="spinner" /> {label}
    </div>
  );
}

/** Modal idea picker: verified bank facts or fresh Ollama ideas. */
export function IdeasModal({
  areas,
  onPick,
  onClose,
}: {
  areas: string[];
  onPick: (topic: string) => void;
  onClose: () => void;
}) {
  const [source, setSource] = useState("bank");
  const [area, setArea] = useState(areas[0] ?? "");
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = (exclude: Idea[] = []) => {
    setLoading(true);
    setError(null);
    const q = new URLSearchParams({ source, area });
    exclude.forEach((i) => q.append("exclude", i.topic));
    getJSON<Idea[]>(`/m/conversacion/api/ideas?${q}`)
      .then((list) => {
        setIdeas(list);
        setSelected(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => load(), [source, area]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Lluvia de ideas">
        <header>
          <h2>💡 Lluvia de ideas</h2>
          <button className="ghost" onClick={onClose} aria-label="Cerrar">✕</button>
        </header>
        <div className="row">
          <div className="segmented">
            <button className={source === "bank" ? "on" : ""} onClick={() => setSource("bank")}>
              Datos verificados
            </button>
            <button className={source === "ollama" ? "on" : ""} onClick={() => setSource("ollama")}>
              Ideas nuevas (Ollama)
            </button>
          </div>
          <select value={area} onChange={(e) => setArea(e.target.value)} aria-label="Área">
            {areas.map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </div>
        {source === "ollama" && (
          <p className="hint">Las ideas de un modelo local pueden traer datos falsos: revísalas.</p>
        )}
        <ErrorBox message={error} />
        {loading ? (
          <Spinner label={source === "ollama" ? "Pidiendo ideas al modelo (~30 s)…" : "Buscando…"} />
        ) : (
          <ul className="ideas">
            {ideas.map((idea) => (
              <li key={idea.topic}>
                <button
                  className={selected === idea.topic ? "idea on" : "idea"}
                  onClick={() => setSelected(idea.topic)}
                  onDoubleClick={() => onPick(idea.topic)}
                >
                  {idea.label}
                </button>
              </li>
            ))}
          </ul>
        )}
        <footer>
          <button className="ghost" onClick={() => load(ideas)} disabled={loading}>
            🎲 Otras ideas
          </button>
          <button className="primary" disabled={!selected} onClick={() => selected && onPick(selected)}>
            Usar este tema
          </button>
        </footer>
      </div>
    </div>
  );
}
