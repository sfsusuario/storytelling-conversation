import { useEffect, useState } from "react";
import { api } from "../api";
import type { HistoryRun } from "../types";
import { CopyButton, formatSeconds } from "./ui";
import { MOTION_CHOICES } from "./Wizard";
import { apiUrl, downloadUrl } from "../../../remote";
import ShareButton from "../../../ShareButton";

const REGENERATE_FROM = [
  { value: "render", label: "Solo volver a montar (render)" },
  { value: "motion", label: "Movimiento" },
  { value: "tts", label: "Voz" },
  { value: "images", label: "Imágenes" },
  { value: "text", label: "Textos (todo de nuevo)" },
];

/** Re-run a past video in its own folder from one stage on; earlier stages are kept. */
function Regenerate({ run, onStarted }: { run: HistoryRun; onStarted: (runId: string) => void }) {
  const [from, setFrom] = useState("render");
  const [motion, setMotion] = useState("rotate3d");
  const [error, setError] = useState<string | null>(null);
  const go = () => {
    setError(null);
    api
      .regenerateHistory(run.name, from, motion)
      .then((r) => onStarted(r.run_id))
      .catch((e: Error) => setError(e.message));
  };
  const select = "rounded-lg border border-stone-300 bg-white px-2 py-1 text-sm dark:border-stone-700 dark:bg-stone-900";
  return (
    <div className="space-y-2 rounded-lg border border-stone-200 p-3 dark:border-stone-800">
      <h4 className="text-sm font-semibold">🔁 Volver a generar</h4>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label className="flex items-center gap-1">
          Desde
          <select className={select} value={from} onChange={(e) => setFrom(e.target.value)}>
            {REGENERATE_FROM.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          Movimiento
          <select className={select} value={motion} onChange={(e) => setMotion(e.target.value)}>
            {MOTION_CHOICES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn-primary px-3 py-1" onClick={go}>
          Regenerar
        </button>
      </div>
      <p className="hint mt-0">Se conserva todo lo anterior al paso elegido; solo se rehace ese paso y los siguientes.</p>
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    </div>
  );
}

export function History({ onStarted }: { onStarted: (runId: string) => void }) {
  const [runs, setRuns] = useState<HistoryRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<HistoryRun | null>(null);

  const load = () =>
    api
      .runs()
      .then((r) => setRuns(r.history))
      .catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const remove = async (run: HistoryRun) => {
    if (!window.confirm(`¿Eliminar el vídeo “${run.phrase}” y todos sus archivos? No se puede deshacer.`)) return;
    try {
      await api.deleteRun(run.name);
      setOpen(null);
      setRuns((prev) => prev?.filter((r) => r.name !== run.name) ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (error) return <p role="alert" className="text-red-600">{error}</p>;
  if (!runs) return <p className="text-stone-500">Cargando historial…</p>;
  if (runs.length === 0)
    return <p className="card text-center text-stone-500">Todavía no hay vídeos. Crea el primero en la pestaña «Crear».</p>;

  return (
    <section aria-label="Historial">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{runs.length} vídeos generados</h2>
        <button type="button" className="btn-ghost" onClick={load}>
          🔄 Actualizar
        </button>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {runs.map((run) => {
          const thumb = run.scenes.at(-1)?.image ?? run.scenes[0]?.image;
          return (
            <div key={run.name} className="group relative">
            <button
              type="button"
              onClick={() => setOpen(run)}
              className="w-full overflow-hidden rounded-xl border border-stone-200 bg-white text-left transition hover:shadow-md dark:border-stone-800 dark:bg-stone-900"
            >
              <div className="relative aspect-[9/16] bg-stone-200 dark:bg-stone-800">
                {thumb && <img src={apiUrl(thumb)} alt="" className="h-full w-full object-cover transition group-hover:scale-105" loading="lazy" />}
                <span className="absolute inset-0 grid place-items-center text-4xl text-white opacity-0 drop-shadow transition group-hover:opacity-100">
                  ▶
                </span>
                {run.test_mode && <span className="absolute left-2 top-2 rounded bg-amber-500 px-1.5 text-xs text-white">prueba</span>}
              </div>
              <div className="p-2">
                <div className="truncate text-sm font-medium">“{run.phrase}”</div>
                <div className="truncate text-xs text-stone-500">
                  {new Date(run.mtime * 1000).toLocaleString()} · {run.style_set}
                </div>
              </div>
            </button>
            <button
              type="button"
              onClick={() => remove(run)}
              title="Eliminar"
              aria-label={`Eliminar “${run.phrase}”`}
              className="absolute right-2 top-2 rounded-md bg-black/50 px-1.5 py-0.5 text-sm text-white opacity-70 transition hover:bg-red-600 hover:opacity-100 focus:opacity-100"
            >
              🗑
            </button>
            </div>
          );
        })}
      </div>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`Vídeo: ${open.phrase}`}
          className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4"
          onClick={() => setOpen(null)}
        >
          <div className="card grid max-h-full w-full max-w-4xl gap-5 overflow-auto md:grid-cols-[minmax(0,320px)_1fr]" onClick={(e) => e.stopPropagation()}>
            {open.video_url && <video src={apiUrl(open.video_url)} controls autoPlay className="aspect-[9/16] w-full rounded-xl bg-black" />}
            <div className="space-y-3">
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-lg font-semibold">“{open.phrase}”</h3>
                <button type="button" className="btn-ghost px-2 py-1" onClick={() => setOpen(null)} aria-label="Cerrar">
                  ✕
                </button>
              </div>
              <p className="text-sm text-stone-500">
                {open.style_set} · {open.language} · {open.duration ? formatSeconds(open.duration) : "?"} · voz {open.voice}
              </p>
              <ol className="space-y-1 text-sm">
                {open.scenes.map((s) => (
                  <li key={s.scene_id}>
                    <b>N{s.level} {s.persona}:</b> <i>{s.text}</i>
                  </li>
                ))}
              </ol>
              {open.social && (
                <div className="space-y-2 rounded-lg bg-stone-100 p-3 dark:bg-stone-800">
                  <div className="flex justify-end">
                    <CopyButton text={open.social} />
                  </div>
                  <p className="whitespace-pre-wrap text-sm">{open.social}</p>
                </div>
              )}
              <Regenerate run={open} onStarted={onStarted} />
              <div className="flex flex-wrap gap-2">
                {open.video_url && <ShareButton className="btn-primary" url={open.video_url} title={open.name} text={open.social} />}
                {open.video_url && (
                  <a className="btn-primary" href={downloadUrl(open.video_url)} download={`${open.name}.mp4`}>
                    ⬇ Descargar
                  </a>
                )}
                <button type="button" className="btn-ghost text-red-600" onClick={() => remove(open)}>
                  🗑 Eliminar
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
