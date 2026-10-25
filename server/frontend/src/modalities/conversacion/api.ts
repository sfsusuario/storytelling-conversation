import { useEffect, useState } from "react";

export type Defaults = {
  engines: string[];
  tts_engine: string;
  languages: { code: string; name: string }[];
  language: string;
  max_turns: number;
  text_provider: string;
  text_model: string;
  ollama_models: string[];
  ollama_default: string;
  subtitles: boolean;
  watermark: string;
  bg_volume: number;
  areas: string[];
  batch_theme: string;
};

export type Turn = { speaker: "rick" | "morty"; emotion: string; line: string };
export type Idea = { label: string; topic: string };

/** One server-sent progress event (see classify() in src/charla/web.py). */
export type JobEvent = {
  kind: string; // log | stage | audio | clip | video | video_ok | video_fail | result | error | end
  text?: string;
  stage?: string;
  turn?: number;
  index?: number;
  total?: number;
  topic?: string;
  error?: string;
  name?: string;
  [key: string]: unknown;
};

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const getJSON = <T,>(url: string) => fetch(url).then((r) => handle<T>(r));

export const postJSON = <T,>(url: string, body: unknown = {}) =>
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r));

/** Follows a background job: every event so far, plus done when it ended. */
export function useJob(jobId: string | null): { events: JobEvent[]; done: boolean } {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [done, setDone] = useState(false);
  useEffect(() => {
    setEvents([]);
    setDone(false);
    if (!jobId) return;
    const source = new EventSource(`/m/conversacion/api/jobs/${jobId}/events`);
    source.onmessage = (msg) => {
      const event = JSON.parse(msg.data) as JobEvent;
      if (event.kind === "end") {
        source.close(); // otherwise EventSource reconnects and replays
        setDone(true);
        return;
      }
      setEvents((prev) => [...prev, event]);
    };
    source.onerror = () => {
      source.close();
      setDone(true);
    };
    return () => source.close();
  }, [jobId]);
  return { events, done };
}

export function lastOf(events: JobEvent[], kind: string): JobEvent | undefined {
  for (let i = events.length - 1; i >= 0; i--) if (events[i].kind === kind) return events[i];
  return undefined;
}

export function useElapsed(running: boolean): number {
  const [start, setStart] = useState(0);
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (!running) return;
    const t0 = Date.now();
    setStart(t0);
    setNow(t0);
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);
  return Math.max(0, Math.round((now - start) / 1000));
}

export const mmss = (s: number) =>
  `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
