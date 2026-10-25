import { useEffect, useState } from "react";
import type { Modality } from "./App";
import { apiUrl, downloadUrl } from "./remote";
import ShareButton from "./ShareButton";

export type Reuse =
  | { kind: "prefill"; input: string } // open the modality with the same input
  | { kind: "regenerate"; url: string; body: unknown }; // the modality re-runs it itself

type Run = {
  modality: string;
  modality_name: string;
  modality_icon: string;
  name: string;
  title: string;
  subtitle: string;
  created: string;
  duration: number | null;
  video_url: string | null;
  thumb_url: string | null;
  social: string;
  meta: Record<string, string | number | null>;
  delete_url: string | null;
  reuse: Reuse | null;
};

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString("es", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const fmtDur = (s: number | null) => (s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "");

/** Every modality's finished videos in one list (GET /api/history). */
export default function History({
  modalities,
  onOpen,
  onReuse,
  only,
}: {
  modalities: Modality[];
  only?: string; // one modality's own history: fixed filter, no chips
  onOpen: (id: string) => void;
  onReuse: (modality: string, reuse: Reuse) => void;
}) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [filter, setFilter] = useState(only ?? "");
  const [playing, setPlaying] = useState<Run | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRuns(null);
    fetch(`/api/history${filter ? `?modality=${filter}` : ""}`)
      .then((r) => r.json())
      .then((body) => setRuns(Array.isArray(body) ? (body as Run[]) : []))
      .catch(() => setRuns([]));
  }, [filter, reload]);

  const copy = (run: Run) =>
    navigator.clipboard.writeText(run.social).then(() => {
      setCopied(run.name);
      setTimeout(() => setCopied(null), 1500);
    });

  const remove = async (run: Run) => {
    if (!run.delete_url || !confirm(`¿Borrar "${run.title}"? Se elimina el video y su carpeta.`)) return;
    setError(null);
    const res = await fetch(run.delete_url, { method: "DELETE" });
    if (!res.ok) setError(`No se pudo borrar (${res.status}).`);
    setPlaying(null);
    setReload((n) => n + 1);
  };

  return (
    <div className="h-wrap">
      <div className="h-chips">
        {!only && <button className={filter === "" ? "on" : ""} onClick={() => setFilter("")}>Todos</button>}
        {!only && modalities.map((m) => (
          <button key={m.id} className={filter === m.id ? "on" : ""} onClick={() => setFilter(m.id)}>
            {m.icon} {m.name}
          </button>
        ))}
        <span className="h-muted">{runs ? `${runs.length} videos` : "Cargando…"}</span>
      </div>
      {error && <div className="shell-error">⚠ {error}</div>}
      {runs && runs.length === 0 && <p className="h-muted">Todavía no hay videos terminados.</p>}
      <ul className="h-grid">
        {runs?.map((run) => (
          <li key={`${run.modality}/${run.name}`} className="h-card">
            <button className="h-thumb" onClick={() => setPlaying(run)} aria-label={`Ver ${run.title}`}>
              {run.thumb_url && <img src={apiUrl(run.thumb_url)} alt="" loading="lazy" />}
              <span className="h-badge">{run.modality_icon} {run.modality_name}</span>
              {run.duration ? <span className="h-dur">{fmtDur(run.duration)}</span> : null}
            </button>
            <div className="h-info">
              <b title={run.title}>{run.title}</b>
              {run.subtitle && <span className="h-muted h-small h-clamp">{run.subtitle}</span>}
              <span className="h-muted h-small">{fmtDate(run.created)}</span>
              <div className="h-actions">
                {run.social && (
                  <button onClick={() => copy(run)}>{copied === run.name ? "✓ Copiado" : "📋 Texto"}</button>
                )}
                {run.video_url && <a className="h-button" href={downloadUrl(run.video_url)} download title="Descargar">⬇</a>}
                {run.video_url && <ShareButton url={run.video_url} title={run.title} text={run.social} />}
                {run.delete_url && <button onClick={() => remove(run)} title="Borrar">🗑</button>}
                {run.reuse ? (
                  <button onClick={() => onReuse(run.modality, run.reuse!)} title="Otra versión con la misma entrada">
                    ♻ Otra versión
                  </button>
                ) : (
                  <button onClick={() => onOpen(run.modality)}>Abrir {run.modality_name}</button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {playing && (
        <div className="h-backdrop" onClick={() => setPlaying(null)}>
          <div className="h-player" onClick={(e) => e.stopPropagation()}>
            {playing.video_url && <video src={apiUrl(playing.video_url)} controls autoPlay />}
            <div className="h-info">
              <span className="h-badge h-static">{playing.modality_icon} {playing.modality_name}</span>
              <h3>{playing.title}</h3>
              <ul className="h-meta">
                {Object.entries(playing.meta).filter(([, v]) => v !== null && v !== "").map(([k, v]) => (
                  <li key={k}><span className="h-muted">{k}</span> {String(v)}</li>
                ))}
              </ul>
              {playing.social && <pre>{playing.social}</pre>}
              <div className="h-actions">
                {playing.video_url && <ShareButton url={playing.video_url} title={playing.title} text={playing.social} />}
                {playing.social && <button onClick={() => copy(playing)}>{copied === playing.name ? "✓ Copiado" : "📋 Copiar texto"}</button>}
                {playing.reuse && <button onClick={() => onReuse(playing.modality, playing.reuse!)}>♻ Otra versión</button>}
                {playing.delete_url && <button onClick={() => remove(playing)}>🗑 Borrar</button>}
                <button onClick={() => setPlaying(null)}>Cerrar</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
