import type { AppOptions, HistoryRun, Options, RunEvent, SystemStatus } from "./types";
import { apiUrl } from "../../remote";

export async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  options: () => fetch("/m/escalera/api/options").then((r) => json<AppOptions>(r)),
  system: () => fetch("/m/escalera/api/system").then((r) => json<SystemStatus>(r)),
  runs: () => fetch("/m/escalera/api/runs").then((r) => json<{ active: string | null; history: HistoryRun[] }>(r)),
  upload: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return fetch("/m/escalera/api/uploads", { method: "POST", body }).then((r) =>
      json<{ upload_id: string; url: string }>(r),
    );
  },
  createRun: (upload_id: string, options: Partial<Options>) =>
    fetch("/m/escalera/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upload_id, options }),
    }).then((r) => json<{ run_id: string }>(r)),
  cancel: (runId: string) => fetch(`/m/escalera/api/runs/${runId}/cancel`, { method: "POST" }),
  reroll: (runId: string, scene_id: string, kind: "image" | "motion", prompt?: string) =>
    fetch(`/m/escalera/api/runs/${runId}/reroll`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scene_id, kind, prompt }),
    }).then((r) => json<{ queued?: boolean; run_id?: string }>(r)),
  regenerateHistory: (name: string, force_from: string, motion: string) =>
    fetch(`/m/escalera/api/history/${encodeURIComponent(name)}/regenerate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force_from, motion }),
    }).then((r) => json<{ run_id: string }>(r)),
  retry: (runId: string) =>
    fetch(`/m/escalera/api/runs/${runId}/retry`, { method: "POST" }).then((r) => json<{ run_id: string }>(r)),
  deleteRun: (name: string) =>
    fetch(`/m/escalera/api/history/${encodeURIComponent(name)}`, { method: "DELETE" }).then((r) => json<{ deleted: string }>(r)),
  voicePreviewUrl: (p: { provider: string; voice: string; language: string; rate: string; pitch: string }) =>
    apiUrl(`/m/escalera/api/voice/preview?${new URLSearchParams(p)}`),
  musicPreviewUrl: (style_set: string, source: string) =>
    apiUrl(`/m/escalera/api/music/preview?${new URLSearchParams({ style_set, source })}`),
};

/**
 * Follow a run's SSE stream. EventSource reconnects by itself and sends
 * Last-Event-ID, so the backend resumes where the stream broke.
 */
export function followRun(runId: string, onEvent: (e: RunEvent) => void, onLost: () => void, base = "/m/escalera"): () => void {
  const source = new EventSource(`${base}/api/runs/${runId}/events`);
  source.onmessage = (msg) => {
    const event = JSON.parse(msg.data) as RunEvent;
    onEvent(event);
    if (event.type === "done" || event.type === "error" || event.type === "cancelled") source.close();
  };
  source.onerror = () => {
    // CLOSED means the server refused (e.g. unknown run after a restart).
    if (source.readyState === EventSource.CLOSED) onLost();
  };
  return () => source.close();
}

/** localStorage that never throws (private mode, blocked storage). */
export const store = {
  get<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : (JSON.parse(raw) as T);
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable: convenience only */
    }
  },
};
