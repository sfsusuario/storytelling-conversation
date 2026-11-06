import { useEffect, useState } from "react";
import { getJSON, postJSON, type Idea, type JobEvent } from "./api";

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

/** The LLM's answer (JSON, with or without a code fence) as an object; the
 * backend validates turns, speakers and emotions. Throws a Spanish message. */
export function parsePastedScript(text: string): Record<string, unknown> {
  const raw = text.trim();
  if (raw.includes("Responde solo con un objeto JSON")) throw new Error("Esto es el prompt. Pégaselo a tu modelo y aquí pega lo que responda.");
  const start = raw.indexOf("{");
  if (start < 0) throw new Error("La respuesta no trae un objeto JSON.");
  try {
    return JSON.parse(raw.slice(start, raw.lastIndexOf("}") + 1));
  } catch (e) {
    throw new Error(`JSON inválido: ${(e as Error).message}`);
  }
}

/** Skip the local model: copy the prompt into any LLM and paste its answer. */
export function ScriptPasteModal({
  promptBody,
  onUse,
  onClose,
}: {
  promptBody: unknown | null; // null: no topic yet, only pasting
  onUse: (script: Record<string, unknown>) => Promise<void>;
  onClose: () => void;
}) {
  const [prompt, setPrompt] = useState<string | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (promptBody)
      postJSON<{ prompt: string }>("/m/conversacion/api/video/script-prompt", promptBody)
        .then((r) => setPrompt(r.prompt))
        .catch((e: Error) => setPromptError(e.message));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const use = async () => {
    setError(null);
    setBusy(true);
    try {
      await onUse(parsePastedScript(text));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Pegar guion">
        <header>
          <h2>📋 Pegar guion</h2>
          <button className="ghost" onClick={onClose} aria-label="Cerrar">✕</button>
        </header>
        <p className="hint">Escribe el guion con Claude u otro modelo y pégalo aquí. No se usa ningún LLM.</p>
        <div className="row">
          {prompt ? (
            <CopyButton text={prompt} label="📋 Copiar prompt" />
          ) : promptError ? (
            <ErrorBox message={`No se pudo preparar el prompt: ${promptError}`} />
          ) : promptBody ? (
            <Spinner label="Preparando el prompt…" />
          ) : (
            <span className="hint">Para copiar el prompt, cierra y escribe antes el tema. Si ya tienes el guion, pégalo.</span>
          )}
        </div>
        {prompt && (
          <details className="settings">
            <summary>Ver el prompt</summary>
            <textarea className="topic" rows={6} readOnly value={prompt} aria-label="Prompt para el modelo" />
          </details>
        )}
        <textarea
          className="topic"
          rows={12}
          aria-label="Respuesta del modelo"
          placeholder='{ "title": ..., "turns": [ { "speaker": "rick", "emotion": ..., "line": ... } ], "caption": ..., "hashtags": [...] }'
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setError(null);
          }}
        />
        <ErrorBox message={error} />
        <footer>
          <button className="ghost" onClick={onClose}>Cancelar</button>
          <button className="primary" disabled={!text.trim() || busy} onClick={use}>
            Usar este guion
          </button>
        </footer>
      </div>
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
