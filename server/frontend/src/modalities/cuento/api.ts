import { followRun, json, store as rawStore } from "../escalera/api";
import { apiUrl } from "../../remote";
import type { AppOptions, Preset, RunEvent, SourceList, StoryOptions, SystemStatus } from "./types";

const BASE = "/m/cuento";

export const api = {
  options: () => fetch(`${BASE}/api/options`).then((r) => json<AppOptions>(r)),
  system: () => fetch(`${BASE}/api/system`).then((r) => json<SystemStatus>(r)),
  sources: () => fetch(`${BASE}/api/sources`).then((r) => json<{ presets: Preset[]; periods: string[] }>(r)),
  stories: (subreddit: string, period: string, refresh = false) =>
    fetch(`${BASE}/api/sources/${encodeURIComponent(subreddit)}/stories?${new URLSearchParams({ period, refresh: refresh ? "1" : "0" })}`).then((r) =>
      json<SourceList>(r),
    ),
  runs: () => fetch(`${BASE}/api/runs`).then((r) => json<{ active: string | null }>(r)),
  upload: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return fetch(`${BASE}/api/uploads`, { method: "POST", body }).then((r) => json<{ upload_id: string; url: string }>(r));
  },
  createRun: (upload_id: string, options: Partial<StoryOptions>) =>
    fetch(`${BASE}/api/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upload_id, options }),
    }).then((r) => json<{ run_id: string }>(r)),
  cancel: (runId: string) => fetch(`${BASE}/api/runs/${runId}/cancel`, { method: "POST" }),
  reroll: (runId: string, scene_id: string, kind: "image" | "motion") =>
    fetch(`${BASE}/api/runs/${runId}/reroll`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scene_id, kind }),
    }).then((r) => json<{ queued?: boolean; run_id?: string }>(r)),
  retry: (runId: string) => fetch(`${BASE}/api/runs/${runId}/retry`, { method: "POST" }).then((r) => json<{ run_id: string }>(r)),
  voicePreviewUrl: (p: { provider: string; voice: string; language: string; rate: string; pitch: string }) =>
    apiUrl(`${BASE}/api/voice/preview?${new URLSearchParams(p)}`),
};

export const follow = (runId: string, onEvent: (e: RunEvent) => void, onLost: () => void) => followRun(runId, onEvent, onLost, BASE);

/** Escalera's localStorage helper with prefixed keys, so the two modalities never collide. */
export const store = {
  get: <T,>(key: string, fallback: T): T => rawStore.get(`cuento.${key}`, fallback),
  set: (key: string, value: unknown) => rawStore.set(`cuento.${key}`, value),
};
