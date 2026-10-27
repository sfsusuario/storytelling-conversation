import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import History from "../../History";
import { json } from "../escalera/api";
import { ProgressView, type SceneLabels } from "../escalera/components/ProgressView";
import { ResultView } from "../escalera/components/ResultView";
import { Badge } from "../escalera/components/ui";
import type { Upload } from "../escalera/components/Wizard";
import { initialRun, runReducer, stageDurations } from "../escalera/runState";
import { STAGE_LABELS } from "../escalera/types";
import { api, follow, store } from "./api";
import { StoryPreview } from "./StoryPreview";
import { StoryForm } from "./Wizard";
import type { AppOptions, StoryOptions, SystemStatus } from "./types";

type Averages = Record<string, { avg: number; n: number }>;

function SystemChip({ system }: { system: SystemStatus | null }) {
  if (!system) return <Badge ok={null}>comprobando equipo…</Badge>;
  return (
    <div className="flex flex-wrap justify-end gap-1.5" aria-label="Estado del equipo">
      <Badge ok={system.ollama}>Ollama</Badge>
      <Badge ok={system.kokoro}>Kokoro</Badge>
      <Badge ok={system.xpu}>GPU Intel</Badge>
    </div>
  );
}

/** Same run machinery and views as Escalera; only the form and the scene
 * labels (no levels, no personas) are the story's own. */
export default function App() {
  const [app, setApp] = useState<AppOptions | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [opts, setOpts] = useState<StoryOptions | null>(null);
  const [upload, setUpload] = useState<Upload | null>(() => store.get("upload", null));
  const [tab, setTab] = useState<"create" | "history">("create");
  const [run, dispatch] = useReducer(runReducer, initialRun);
  const [startError, setStartError] = useState<string | null>(null);
  const [averages, setAverages] = useState<Averages>(() => store.get("stageAverages", {}));
  const stopFollow = useRef<(() => void) | null>(null);

  const attach = useCallback((runId: string) => {
    stopFollow.current?.();
    dispatch({ type: "reset" });
    store.set("activeRun", runId);
    stopFollow.current = follow(runId, dispatch, () => {
      store.set("activeRun", null);
      dispatch({ type: "reset" });
    });
  }, []);

  useEffect(() => {
    api
      .options()
      .then((o) => {
        setApp(o);
        setOpts({ ...o.defaults, ...store.get<Partial<StoryOptions>>("opts", {}), force: false, force_from: null });
      })
      .catch((e: Error) => setLoadError(e.message));
    api.system().then(setSystem).catch(() => setSystem(null));
    // Reattach to a run in progress (reload, another device) or to the last one shown.
    api
      .runs()
      .then((r) => {
        const runId = r.active ?? store.get<string | null>("activeRun", null);
        if (runId) attach(runId);
      })
      .catch(() => {});
    return () => stopFollow.current?.();
  }, [attach]);

  // Learn per-provider stage durations for future ETAs.
  useEffect(() => {
    if (run.status !== "done") return;
    setAverages((prev) => {
      const next = { ...prev };
      for (const [key, secs] of Object.entries(stageDurations(run))) {
        const old = next[key];
        next[key] = old ? { avg: (old.avg * Math.min(old.n, 4) + secs) / (Math.min(old.n, 4) + 1), n: old.n + 1 } : { avg: secs, n: 1 };
      }
      store.set("stageAverages", next);
      return next;
    });
  }, [run.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const setOpt = <K extends keyof StoryOptions>(key: K, value: StoryOptions[K]) =>
    setOpts((prev) => {
      const next = { ...prev!, [key]: value };
      store.set("opts", next);
      return next;
    });

  const start = async (extra: Partial<StoryOptions> = {}) => {
    if (!opts) return;
    const uploadId = upload?.id ?? "";
    setStartError(null);
    try {
      const sent = { ...opts, premise: opts.premise.trim(), ...extra };
      const { run_id } = await api.createRun(uploadId, sent);
      store.set("lastRequest", { uploadId, opts: sent });
      attach(run_id);
    } catch (e) {
      setStartError((e as Error).message);
    }
  };

  // Re-run with the last run's options, without forcing: every finished stage
  // and scene is cached, so only what failed (or was rerolled) is redone.
  const rerun = async (extra: Partial<StoryOptions> = {}) => {
    const last = store.get<{ uploadId: string; opts: StoryOptions } | null>("lastRequest", null);
    const plain = { force: false, force_from: null, reroll_images: [], reroll_motion: [], ...extra };
    if (!last) return start(plain);
    setStartError(null);
    try {
      const { run_id } = await api.createRun(last.uploadId, { ...last.opts, ...plain });
      attach(run_id);
    } catch (e) {
      setStartError((e as Error).message);
    }
  };
  const retry = async () => {
    setStartError(null);
    try {
      if (!run.runId) throw new Error("unknown run");
      attach((await api.retry(run.runId)).run_id);
    } catch (e) {
      if ((e as Error).message.includes("unknown run")) return rerun();
      setStartError((e as Error).message);
    }
  };
  const reroll = async (sceneId: string, kind: "image" | "motion") => {
    setStartError(null);
    try {
      if (!run.runId) throw new Error("unknown run");
      const r = await api.reroll(run.runId, sceneId, kind);
      if (r.run_id) attach(r.run_id);
    } catch (e) {
      if ((e as Error).message.includes("unknown run")) return rerun(kind === "image" ? { reroll_images: [sceneId] } : { reroll_motion: [sceneId] });
      setStartError((e as Error).message);
    }
  };

  // The run handed queued rerolls to a follow-up run: follow that one.
  useEffect(() => {
    if (run.next) attach(run.next);
  }, [run.next, attach]);

  const newStory = () => {
    stopFollow.current?.();
    store.set("activeRun", null);
    dispatch({ type: "reset" });
  };

  // "Otra versión" from the history: the backend regenerates the story in its
  // own folder (same premise and photo, new text and images)
  const regenerateFromHistory = async (url: string, body: unknown) => {
    setStartError(null);
    setTab("create");
    try {
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      attach((await json<{ run_id: string }>(res)).run_id);
    } catch (e) {
      setStartError((e as Error).message);
    }
  };

  if (loadError)
    return (
      <main className="mx-auto max-w-xl p-8">
        <div role="alert" className="card text-red-700">
          No se pudo conectar con el servidor ({loadError}). Arranca el estudio con <code>run-ui.ps1</code>.
        </div>
      </main>
    );
  if (!app || !opts) return <main className="p-8 text-stone-500">Cargando…</main>;

  const busy = run.status === "running";
  const showRun = run.status !== "idle";
  const labels: SceneLabels = {
    badge: (sc) => String(sc.level),
    title: (sc) => sc.persona,
    canRerollImage: (sc) => Boolean(sc.image),
    original: () => upload?.url ?? null,
    setLabel: (s) => s,
    gridProgress: "grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4",
    gridResult: "grid grid-cols-4 gap-2 sm:grid-cols-8",
    download: "cuento.mp4",
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-stone-200 bg-white/80 backdrop-blur dark:border-stone-800 dark:bg-stone-950/80">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-6">
            <h1 className="text-lg font-bold">
              📖 <span className="text-orange-600">Cuento ilustrado</span>
            </h1>
            <nav className="flex gap-1" aria-label="Secciones">
              {(["create", "history"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTab(t)}
                  aria-current={tab === t ? "page" : undefined}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                    tab === t ? "bg-stone-200 dark:bg-stone-800" : "text-stone-500 hover:text-stone-900 dark:hover:text-stone-100"
                  }`}
                >
                  {t === "create" ? "Crear" : "Historial"}
                  {t === "create" && busy && <span className="ml-1.5 inline-block h-2 w-2 animate-pulse rounded-full bg-orange-500" />}
                </button>
              ))}
            </nav>
          </div>
          <SystemChip system={system} />
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">
        {tab === "create" && showRun && startError && (
          <p role="alert" className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
            {startError}
          </p>
        )}
        {tab === "history" ? (
          // the shared history, styled for the dark shell: give it that background
          <div className="rounded-2xl" style={{ background: "var(--s-bg)", color: "var(--s-text)" }}>
            <History
              modalities={[]}
              only="cuento"
              onOpen={() => setTab("create")}
              onReuse={(_, r) => {
                if (r.kind === "regenerate") regenerateFromHistory(r.url, r.body);
              }}
            />
          </div>
        ) : showRun && run.status === "done" && run.result && !run.result.video ? (
          // "Solo el guion": the text is written; continue reuses it from the cache
          <StoryPreview state={run} onContinue={() => start({ preview: false })} onAnother={() => start({ preview: true, force_from: "text" })} onBack={newStory} />
        ) : showRun && run.status === "done" && run.result ? (
          <ResultView state={run} onNew={newStory} onRegenerate={(stage) => start({ force_from: stage })} onReroll={reroll} labels={labels} />
        ) : showRun ? (
          <>
            <ProgressView
              state={run}
              averages={Object.fromEntries(Object.entries(averages).map(([k, v]) => [k, v.avg]))}
              onCancel={() => run.runId && api.cancel(run.runId)}
              onReroll={reroll}
              labels={labels}
            />
            {!busy && (
              <div className="mt-4 flex gap-2">
                <button type="button" className="btn-primary" onClick={retry}>
                  ↻ Reintentar{run.stage ? ` desde ${STAGE_LABELS[run.stage]}` : ""}
                </button>
                <button type="button" className="btn-ghost" onClick={newStory}>
                  Volver a la configuración
                </button>
                <span className="self-center text-xs text-stone-500">Lo ya generado se reutiliza; solo se rehace lo que falló.</span>
              </div>
            )}
          </>
        ) : (
          <div className="mx-auto max-w-3xl space-y-4">
            <StoryForm
              app={app}
              opts={opts}
              setOpt={setOpt}
              system={system}
              upload={upload}
              onUpload={(u) => {
                setUpload(u);
                store.set("upload", u);
              }}
              onClear={() => {
                setUpload(null);
                store.set("upload", null);
              }}
              error={startError}
              onStart={() => start({ preview: false })}
              onPreview={() => start({ preview: true })}
            />
          </div>
        )}
      </main>
    </div>
  );
}
