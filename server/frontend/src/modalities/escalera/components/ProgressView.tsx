import { useEffect, useRef, useState } from "react";
import { estimateRemaining, stageProgress, type RunState, type SceneState, type Work } from "../runState";
import { STAGES, STAGE_LABELS } from "../types";
import { formatSeconds } from "./ui";
import { apiUrl } from "../../../remote";

/** What a scene is called and laid out: Escalera (levels + personas) by
 * default; a sibling modality (Cuento) passes its own. */
export interface SceneLabels {
  badge: (sc: SceneState) => string;
  title: (sc: SceneState) => string;
  canRerollImage: (sc: SceneState) => boolean;
  /** "Foto original" tab source for a scene; null hides the tab */
  original: (state: RunState, sc: SceneState) => string | null;
  setLabel: (styleSet: string) => string;
  gridProgress: string;
  gridResult: string;
  download: string;
}

export const ESCALERA_LABELS: SceneLabels = {
  badge: (sc) => `N${sc.level}`,
  title: (sc) => `N${sc.level} · ${sc.persona}`,
  canRerollImage: (sc) => sc.level > 1,
  original: (state, sc) => (sc.level > 1 ? (state.scenes[0]?.image ?? null) : null),
  setLabel: (s) => `set ${s}`,
  gridProgress: "grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5",
  gridResult: "grid grid-cols-3 gap-2 sm:grid-cols-5",
  download: "escalator.mp4",
};

/** Seconds since run start, ticking locally between server events. */
function useRunClock(state: RunState): number {
  const anchor = useRef({ ts: state.now, wall: Date.now() });
  const [, tick] = useState(0);
  if (anchor.current.ts !== state.now) anchor.current = { ts: state.now, wall: Date.now() };
  useEffect(() => {
    if (state.status !== "running") return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [state.status]);
  return state.status === "running" ? anchor.current.ts + (Date.now() - anchor.current.wall) / 1000 : state.now;
}

function Stepper({ state, now }: { state: RunState; now: number }) {
  const current = state.stage ? STAGES.indexOf(state.stage) : -1;
  return (
    <ol className="grid grid-cols-3 gap-2 sm:grid-cols-6" aria-label="Etapas">
      {STAGES.map((stage, i) => {
        const started = state.started[stage];
        const ended = state.ended[stage];
        const status =
          ended !== undefined ? "done" : i === current ? (state.status === "running" ? "active" : "stopped") : "todo";
        const progress = stageProgress(state, stage);
        const seconds = started === undefined ? null : (ended ?? now) - started;
        return (
          <li key={stage} className="min-w-0">
            <div className="mb-1 h-1.5 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  status === "done" ? "bg-emerald-500" : status === "active" ? "bg-orange-500" : status === "stopped" ? "bg-red-500" : ""
                } ${status === "active" && progress === null ? "animate-pulse" : ""}`}
                style={{ width: status === "done" ? "100%" : status === "todo" ? "0%" : `${Math.max(8, (progress ?? 0.5) * 100)}%` }}
              />
            </div>
            <div className={`truncate text-xs font-medium sm:text-sm ${status === "todo" ? "text-stone-400" : ""}`}>
              {status === "done" ? "✓ " : ""}
              {STAGE_LABELS[stage]}
            </div>
            <div className="truncate text-xs text-stone-500" title={state.details[stage]}>
              {seconds !== null ? formatSeconds(seconds) : ""}
              {state.details[stage] ? ` · ${state.details[stage]}` : ""}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

const WORK_LABELS: Record<string, string> = { images: "Imagen", motion: "Movimiento" };

/** Live bar for a scene mid-way through a slow step, with its own ETA. */
function WorkBar({ work, now }: { work: Work; now: number }) {
  const known = work.total > 0;
  const fraction = known ? Math.min(1, work.step / work.total) : 0;
  const elapsed = Math.max(0, now - work.since);
  const eta = known && work.step > 0 && fraction < 1 ? (elapsed / work.step) * (work.total - work.step) : null;
  return (
    <div className="absolute inset-x-0 bottom-0 bg-black/70 p-2 text-white" role="status">
      <div className="flex justify-between gap-2 text-[11px]">
        <span className="truncate">
          {WORK_LABELS[work.stage] ?? work.stage}: {known ? `${work.step}/${work.total} ${work.label}` : `${work.label}…`}
        </span>
        <span className="shrink-0">{eta !== null ? `~${formatSeconds(eta)}` : formatSeconds(elapsed)}</span>
      </div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-white/20">
        <div
          className={`h-full rounded-full bg-orange-500 transition-all duration-300 ${known ? "" : "w-1/3 animate-pulse"}`}
          style={known ? { width: `${fraction * 100}%` } : undefined}
        />
      </div>
    </div>
  );
}

type View = "image" | "video" | "original";
type Reroll = (sceneId: string, kind: "image" | "motion", prompt?: string) => void;

/** Discreet per-scene "another variation" buttons for a card footer. */
export function RerollButtons({
  scene,
  onReroll,
  queued = [],
  labels = ESCALERA_LABELS,
}: {
  scene: SceneState;
  onReroll: Reroll;
  queued?: string[];
  labels?: SceneLabels;
}) {
  const btn = "rounded px-1.5 py-0.5 text-[11px] text-stone-500 hover:bg-stone-100 hover:text-orange-600 dark:hover:bg-stone-800";
  const item = (kind: "image" | "motion", label: string, title: string) =>
    queued.includes(`${scene.scene_id}:${kind}`) ? (
      <span key={kind} className="px-1.5 py-0.5 text-[11px] text-amber-600" title="Se rehará en cuanto termine la escena en curso">
        ⏳ {label} en cola
      </span>
    ) : (
      <button key={kind} type="button" className={btn} title={title} onClick={() => onReroll(scene.scene_id, kind)}>
        🎲 {label}
      </button>
    );
  return (
    <div className="flex flex-wrap justify-center gap-1">
      {labels.canRerollImage(scene) && scene.image && item("image", "imagen", "Otra imagen para esta escena")}
      {scene.motion && item("motion", "movimiento", "Otro movimiento para esta escena")}
    </div>
  );
}

/** Full-size viewer for one scene: its image, its video (final clip with voice,
 * else the motion loop) and the original photo, usable while others render. */
export function SceneViewer({
  scene,
  original,
  onClose,
  onReroll,
  labels = ESCALERA_LABELS,
}: {
  scene: SceneState;
  original: string | null;
  onClose: () => void;
  onReroll?: Reroll;
  labels?: SceneLabels;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const video = scene.clip ?? scene.motion;
  const [view, setView] = useState<View>(video ? "video" : "image");
  // Escalera hands out the prompt it used: editable for the next image
  const [prompt, setPrompt] = useState(scene.prompt ?? "");
  const edited = scene.prompt !== undefined && prompt.trim() !== "" && prompt.trim() !== scene.prompt.trim();
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  const tabs: [View, string, string | null | undefined][] = [
    ["image", "Imagen", scene.image],
    ["video", scene.clip ? "Vídeo" : "Movimiento", video],
    ["original", "Foto original", original],
  ];
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && ref.current?.close()}
      aria-label={`Escena ${labels.title(scene)}`}
      className="max-h-[95vh] max-w-[95vw] rounded-xl bg-stone-950 p-3 text-white backdrop:bg-black/80"
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex gap-1" role="tablist">
          {tabs.map(([key, label, url]) =>
            url ? (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={view === key}
                onClick={() => setView(key)}
                className={`rounded-lg px-3 py-1 text-sm ${view === key ? "bg-white/20 font-semibold" : "text-stone-400 hover:text-white"}`}
              >
                {label}
              </button>
            ) : null,
          )}
        </div>
        <button type="button" onClick={() => ref.current?.close()} className="rounded-lg px-2 text-lg text-stone-400 hover:text-white" aria-label="Cerrar">
          ✕
        </button>
      </div>
      {view === "video" && video ? (
        <video key={video} src={apiUrl(video)} controls autoPlay loop className="max-h-[85vh] max-w-full rounded-lg" />
      ) : (
        <img src={apiUrl(view === "original" ? original : scene.image)} alt="" className="max-h-[85vh] max-w-full rounded-lg object-contain" />
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-stone-300">{labels.title(scene)}</p>
        {onReroll && (
          <div className="flex gap-2">
            {labels.canRerollImage(scene) && (
              <button
                type="button"
                className="rounded-lg bg-white/15 px-3 py-1 text-sm hover:bg-white/25"
                onClick={() => onReroll(scene.scene_id, "image", edited ? prompt.trim() : undefined)}
              >
                {edited ? "🎨 Imagen con este prompt" : "🎲 Otra imagen"}
              </button>
            )}
            {scene.motion && (
              <button type="button" className="rounded-lg bg-white/15 px-3 py-1 text-sm hover:bg-white/25" onClick={() => onReroll(scene.scene_id, "motion")}>
                🎲 Otro movimiento
              </button>
            )}
          </div>
        )}
      </div>
      {onReroll && labels.canRerollImage(scene) && scene.prompt !== undefined && (
        <label className="mt-2 block text-xs text-stone-400">
          Prompt de la imagen (edítalo para afinarla)
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            maxLength={2000}
            rows={3}
            className="mt-1 block w-full min-w-0 rounded-lg bg-white/10 p-2 text-sm text-white"
          />
        </label>
      )}
      {onReroll && (
        <p className="mt-1 text-xs text-stone-400">
          Rehace solo esta escena en cuanto termine la que está en curso; si ya tiene movimiento, también lo rehace. Luego sigue con lo demás.
        </p>
      )}
    </dialog>
  );
}

function SceneCard({
  scene,
  now,
  onOpen,
  onReroll,
  queued,
  labels,
}: {
  scene: SceneState;
  now: number;
  onOpen: () => void;
  onReroll?: Reroll;
  queued: string[];
  labels: SceneLabels;
}) {
  const step = scene.clip ? "clip" : scene.motion ? "motion" : scene.audio ? "audio" : scene.image ? "image" : scene.text ? "text" : "waiting";
  const label = { waiting: "En espera", text: "Texto listo", image: "Imagen lista", audio: "Voz lista", motion: "Movimiento listo", clip: "Clip listo" }[step];
  const cached = scene.cached.image || scene.cached.audio;
  return (
    <article className="overflow-hidden rounded-xl border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
      <div className="relative aspect-[9/16] bg-stone-100 dark:bg-stone-800">
        {scene.image ? (
          <button type="button" onClick={onOpen} className="group h-full w-full" aria-label={`Ver escena ${labels.title(scene)}`}>
            <img src={apiUrl(scene.image)} alt="" className="h-full w-full object-cover transition group-hover:brightness-110" loading="lazy" />
            {(scene.clip || scene.motion) && (
              <span className="absolute inset-0 m-auto flex h-12 w-12 items-center justify-center rounded-full bg-black/55 text-xl text-white opacity-80 group-hover:opacity-100" aria-hidden>
                ▶
              </span>
            )}
          </button>
        ) : (
          <div className="flex h-full items-center justify-center">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-stone-300 border-t-orange-500" aria-hidden />
          </div>
        )}
        <span className="absolute left-2 top-2 rounded-md bg-black/60 px-2 py-0.5 text-xs font-bold text-white">{labels.badge(scene)}</span>
        {cached && <span className="absolute right-2 top-2 rounded-md bg-sky-600/90 px-2 py-0.5 text-xs text-white">caché</span>}
        {scene.work && <WorkBar work={scene.work} now={now} />}
      </div>
      <div className="space-y-2 p-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="truncate text-sm font-semibold">{scene.persona}</h3>
          <span className={`shrink-0 text-xs ${step === "clip" ? "text-emerald-600" : "text-stone-500"}`}>{label}</span>
        </div>
        <p className="min-h-[2.5rem] text-xs italic text-stone-600 dark:text-stone-400">
          {scene.text ? `“${scene.text}”` : "…"}
        </p>
        {scene.audio && <audio controls preload="none" src={apiUrl(scene.audio)} className="h-8 w-full" aria-label={`Voz de ${scene.persona}`} />}
        {onReroll && <RerollButtons scene={scene} onReroll={onReroll} queued={queued} labels={labels} />}
      </div>
    </article>
  );
}

export function ProgressView({
  state,
  averages,
  onCancel,
  onReroll,
  labels = ESCALERA_LABELS,
}: {
  state: RunState;
  averages: Record<string, number>;
  onCancel: () => void;
  onReroll?: Reroll;
  labels?: SceneLabels;
}) {
  const now = useRunClock(state);
  const [showLog, setShowLog] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const opened = state.scenes.find((sc) => sc.scene_id === open);
  const logRef = useRef<HTMLPreElement>(null);
  const eta = estimateRemaining({ ...state, now }, averages);
  const doneStages = STAGES.filter((s) => state.ended[s] !== undefined).length;

  useEffect(() => {
    if (showLog) logRef.current?.scrollTo(0, logRef.current.scrollHeight);
  }, [state.logs.length, showLog]);

  return (
    <section className="space-y-6" aria-labelledby="progress-title">
      <div className="card space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 id="progress-title" className="text-lg font-semibold">
              {state.status === "running" ? "Generando tu vídeo…" : state.status === "cancelled" ? "Cancelado" : "Error"}
            </h2>
            <p className="text-sm text-stone-500" aria-live="polite">
              {state.stage ? `${STAGE_LABELS[state.stage]} (${doneStages + 1}/${STAGES.length})` : "Preparando…"} · {formatSeconds(now)} transcurridos
              {eta !== null && ` · quedan ~${formatSeconds(eta)}`}
              {state.styleSet && ` · ${labels.setLabel(state.styleSet)}`}
            </p>
          </div>
          {state.status === "running" && (
            <button type="button" className="btn-ghost text-red-600" onClick={onCancel}>
              ✕ Cancelar
            </button>
          )}
        </div>
        <Stepper state={state} now={now} />
        {state.loading && state.status === "running" && (
          <p className="flex items-center gap-2 text-sm text-stone-600 dark:text-stone-300" role="status">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-stone-300 border-t-orange-500" aria-hidden />
            {state.loading.label[0].toUpperCase() + state.loading.label.slice(1)}… {formatSeconds(now - state.loading.since)}
            <span className="text-xs text-stone-500">(la primera vez puede tardar más)</span>
          </p>
        )}
        {state.error && (
          <div role="alert" className="whitespace-pre-wrap rounded-lg bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
            {state.error}
          </div>
        )}
      </div>

      {opened && <SceneViewer scene={opened} original={labels.original(state, opened)} onClose={() => setOpen(null)} onReroll={onReroll} labels={labels} />}
      {state.scenes.length > 0 && (
        <div className={labels.gridProgress}>
          {state.scenes.map((sc) => (
            <SceneCard key={sc.scene_id} scene={sc} now={now} onOpen={() => setOpen(sc.scene_id)} onReroll={onReroll} queued={state.queued} labels={labels} />
          ))}
        </div>
      )}

      <div className="card">
        <button type="button" className="text-sm font-medium" aria-expanded={showLog} onClick={() => setShowLog(!showLog)}>
          {showLog ? "▾" : "▸"} Registro detallado ({state.logs.length} líneas)
        </button>
        {showLog && (
          <pre ref={logRef} className="mt-3 max-h-72 overflow-auto rounded-lg bg-stone-950 p-3 text-xs leading-relaxed text-stone-200">
            {state.logs.join("\n")}
          </pre>
        )}
      </div>
    </section>
  );
}
