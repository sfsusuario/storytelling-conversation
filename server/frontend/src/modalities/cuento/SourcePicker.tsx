import { useEffect, useRef, useState } from "react";
import { Select } from "../escalera/components/ui";
import { api } from "./api";
import type { Preset, SourceList, SourceStory } from "./types";

const PAGE = 8;
const PERIOD_LABELS: Record<string, string> = { week: "Esta semana", month: "Este mes" };

/** Real stories from Reddit (public RSS, cached by the backend). Picking one
 * fills the premise and the source; the LLM adapts it in Spanish. */
export function SourcePicker({ onPick, onClose }: { onPick: (story: SourceStory, preset: Preset | null) => void; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [subreddit, setSubreddit] = useState("shortscarystories");
  const [custom, setCustom] = useState("");
  const [period, setPeriod] = useState("week");
  const [list, setList] = useState<SourceList | null>(null);
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    ref.current?.showModal();
    api.sources().then((s) => setPresets(s.presets)).catch(() => {});
  }, []);

  const load = async (refresh = false) => {
    const sub = custom.trim().replace(/^\/?r\//, "") || subreddit;
    setBusy(true);
    setError(null);
    try {
      setList(await api.stories(sub, period, refresh));
      setPage(0);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    load();
  }, [subreddit, period]); // eslint-disable-line react-hooks/exhaustive-deps

  const stories = list?.stories ?? [];
  const shown = stories.slice(page * PAGE, page * PAGE + PAGE);
  const preset = presets.find((p) => p.subreddit.toLowerCase() === (list?.subreddit ?? subreddit).toLowerCase()) ?? null;

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && ref.current?.close()}
      aria-label="Historias reales de Reddit"
      className="w-[min(760px,95vw)] max-h-[92vh] rounded-xl bg-white p-0 text-stone-900 backdrop:bg-black/70 dark:bg-stone-900 dark:text-stone-100"
    >
      <div className="space-y-4 p-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">📰 Historias reales de Reddit</h2>
          <button type="button" onClick={() => ref.current?.close()} className="rounded-lg px-2 text-lg text-stone-400 hover:text-stone-900 dark:hover:text-white" aria-label="Cerrar">
            ✕
          </button>
        </div>
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto_auto]">
          <Select
            id="source-preset"
            value={custom ? "" : subreddit}
            onChange={(v) => {
              setCustom("");
              setSubreddit(v);
            }}
            options={[...presets.map((p) => ({ value: p.subreddit, label: `${p.label} · r/${p.subreddit}` })), ...(custom ? [{ value: "", label: `r/${custom}` }] : [])]}
          />
          <input
            className="input"
            placeholder="o escribe otro: r/…"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
            aria-label="Otro subreddit"
          />
          <Select id="source-period" value={period} onChange={setPeriod} options={Object.entries(PERIOD_LABELS).map(([value, label]) => ({ value, label }))} />
          <button type="button" className="btn-ghost" onClick={() => load(true)} disabled={busy} title="Pide la lista nueva a Reddit (una petición por minuto)">
            ↻ Actualizar
          </button>
        </div>
        {list?.stale && (
          <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
            Reddit limita las peticiones: se muestra la lista guardada{list.retry_in ? ` (reintenta en ${list.retry_in} s)` : ""}.
          </p>
        )}
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
            {error}
          </p>
        )}
        {busy && !list && <p className="text-sm text-stone-500">Buscando historias…</p>}
        {list && stories.length === 0 && !busy && <p className="text-sm text-stone-500">Sin historias con texto aquí (o ya las usaste todas).</p>}
        <ul className="max-h-[52vh] space-y-2 overflow-auto pr-1">
          {shown.map((s) => (
            <li key={s.url} className="rounded-lg border border-stone-200 p-3 dark:border-stone-700">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="font-semibold leading-snug">{s.title}</h3>
                  <p className="text-xs text-stone-500">
                    r/{s.subreddit} · u/{s.author} · {s.words} palabras
                  </p>
                  <p className="mt-1 line-clamp-2 text-sm text-stone-600 dark:text-stone-300">{s.excerpt}</p>
                </div>
                <button
                  type="button"
                  className="btn-primary shrink-0"
                  onClick={() => {
                    onPick(s, preset);
                    ref.current?.close();
                  }}
                >
                  Usar esta
                </button>
              </div>
            </li>
          ))}
        </ul>
        {stories.length > PAGE && (
          <div className="flex items-center justify-between text-xs text-stone-500">
            <span>
              {page * PAGE + 1}–{Math.min(stories.length, (page + 1) * PAGE)} de {stories.length}
            </span>
            <button type="button" className="btn-ghost" onClick={() => setPage((p) => ((p + 1) * PAGE >= stories.length ? 0 : p + 1))}>
              Otras →
            </button>
          </div>
        )}
      </div>
    </dialog>
  );
}
