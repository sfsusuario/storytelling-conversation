import { STAGES, type RunEvent, type StageName } from "./types";

export interface SceneState {
  scene_id: string;
  level: number;
  persona: string;
  text?: string;
  image?: string | null;
  audio?: string | null;
  motion?: string | null;
  clip?: string | null;
  cached: Partial<Record<"image" | "audio" | "motion" | "clip", boolean>>;
  /** Live progress inside this scene's current slow step (diffusion steps, frames). */
  work?: Work | null;
}

export interface Work {
  stage: StageName;
  step: number;
  total: number; // 0 = indeterminate
  label: string;
  since: number; // ts when this scene started this stage's work
}

export interface RunState {
  runId: string | null;
  uploadId: string | null;
  status: "idle" | "running" | "done" | "error" | "cancelled";
  stage: StageName | null;
  details: Partial<Record<StageName, string>>;
  started: Partial<Record<StageName, number>>;
  ended: Partial<Record<StageName, number>>;
  scenes: SceneState[];
  logs: string[];
  now: number; // ts of the latest event, seconds since run start
  styleSet: string | null;
  /** Stage-wide work without a scene, e.g. loading a model. */
  loading: Work | null;
  result: { video: string | null; social: string; duration: number } | null;
  /** Cuento: the written story (title, outline, real source if any). */
  story: { title: string; outline: string; protagonist: string; source: { url: string; author: string; subreddit: string } | null } | null;
  error: string | null;
  /** Rerolls waiting for this run to finish, as "scene_id:kind". */
  queued: string[];
  /** Follow-up run that redoes the queued rerolls. */
  next: string | null;
}

export const initialRun: RunState = {
  runId: null,
  uploadId: null,
  status: "idle",
  stage: null,
  details: {},
  started: {},
  ended: {},
  scenes: [],
  logs: [],
  now: 0,
  styleSet: null,
  loading: null,
  result: null,
  story: null,
  error: null,
  queued: [],
  next: null,
};

const MAX_LOGS = 400;

/** Pure fold of the event stream; replaying the same events rebuilds the same state. */
export function runReducer(state: RunState, event: RunEvent | { type: "reset" }): RunState {
  if (event.type === "reset") return initialRun;
  const s: RunState = { ...state, now: Math.max(state.now, event.ts) };
  switch (event.type) {
    case "started":
      return { ...initialRun, runId: event.run_id, uploadId: event.upload_id, status: "running" };
    case "scenes":
      return {
        ...s,
        styleSet: event.style_set,
        scenes: event.scenes.map((x) => ({ ...x, cached: {} })),
      };
    case "stage": {
      const ended = { ...s.ended };
      if (s.stage && ended[s.stage] === undefined) ended[s.stage] = event.ts;
      return {
        ...s,
        stage: event.name,
        loading: null,
        ended,
        started: { ...s.started, [event.name]: event.ts },
        details: { ...s.details, [event.name]: event.detail },
      };
    }
    case "scene":
      return {
        ...s,
        scenes: s.scenes.map((sc) => {
          if (sc.scene_id !== event.scene_id) return sc;
          if (event.kind === "text") return { ...sc, text: event.text };
          return {
            ...sc,
            work: null,
            [event.kind]: event.path_url,
            cached: { ...sc.cached, [event.kind]: event.cached },
          };
        }),
      };
    case "progress": {
      const base = { stage: event.stage, step: event.step, total: event.total, label: event.label };
      if (event.scene_id === null) return { ...s, loading: { ...base, since: event.ts } };
      return {
        ...s,
        loading: s.loading?.stage === event.stage ? null : s.loading,
        scenes: s.scenes.map((sc) =>
          sc.scene_id === event.scene_id
            ? { ...sc, work: { ...base, since: sc.work?.stage === event.stage ? sc.work.since : event.ts } }
            : sc,
        ),
      };
    }
    case "log":
      return { ...s, logs: [...s.logs, event.line].slice(-MAX_LOGS) };
    case "story":
      return { ...s, story: { title: event.title, outline: event.outline, protagonist: event.protagonist, source: event.source } };
    case "done": {
      const ended = { ...s.ended };
      if (s.stage && ended[s.stage] === undefined) ended[s.stage] = event.ts;
      return {
        ...s,
        ended,
        status: "done",
        result: { video: event.video_url, social: event.social, duration: event.duration },
      };
    }
    case "error":
      return { ...s, status: "error", error: event.message };
    case "cancelled":
      return { ...s, status: "cancelled" };
    case "queued": {
      const key = `${event.scene_id}:${event.kind}`;
      return s.queued.includes(key) ? s : { ...s, queued: [...s.queued, key] };
    }
    case "next":
      return { ...s, next: event.run_id };
  }
}

/** Fraction of per-scene work finished in a stage (images/tts/render), else null. */
export function stageProgress(state: RunState, stage: StageName): number | null {
  const key = { images: "image", tts: "audio", motion: "motion", render: "clip" }[stage as string] as
    | "image"
    | "audio"
    | "motion"
    | "clip"
    | undefined;
  if (!key || state.scenes.length === 0) return null;
  // finished scenes plus the fraction of any scene mid-way through this stage
  const done = state.scenes.reduce((sum, sc) => {
    if (sc[key]) return sum + 1;
    const w = sc.work;
    return w && w.stage === stage && w.total > 0 ? sum + Math.min(1, w.step / w.total) : sum;
  }, 0);
  return done / state.scenes.length;
}

/**
 * Seconds left, from past stage durations per provider (`averages`, keyed by
 * stage + detail). Null when any remaining stage has no history yet.
 */
export function estimateRemaining(
  state: RunState,
  averages: Record<string, number>,
): number | null {
  if (state.status !== "running" || !state.stage) return null;
  let total = 0;
  const current = STAGES.indexOf(state.stage);
  for (const [i, stage] of STAGES.entries()) {
    if (i < current) continue;
    const avg = averages[stageKey(stage, state.details[stage])];
    if (avg === undefined) {
      if (i === current) return null;
      continue; // future stage detail not known yet; skip rather than guess
    }
    if (i === current) {
      const done = stageProgress(state, stage);
      const elapsed = state.now - (state.started[stage] ?? state.now);
      total += done !== null && done > 0 ? Math.max(0, avg * (1 - done)) : Math.max(0, avg - elapsed);
    } else total += avg;
  }
  return total;
}

export function stageKey(stage: StageName, detail?: string): string {
  return `${stage}:${detail ?? ""}`;
}

/** Durations of finished stages, to feed the running averages after a run. */
export function stageDurations(state: RunState): Record<string, number> {
  const out: Record<string, number> = {};
  for (const stage of STAGES) {
    const a = state.started[stage];
    const b = state.ended[stage];
    if (a !== undefined && b !== undefined) out[stageKey(stage, state.details[stage])] = b - a;
  }
  return out;
}
