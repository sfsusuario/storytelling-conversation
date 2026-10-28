export const STAGES = ["text", "images", "tts", "timeline", "motion", "render"] as const;
export type StageName = (typeof STAGES)[number];

export const STAGE_LABELS: Record<StageName, string> = {
  text: "Textos",
  images: "Imágenes",
  tts: "Voz",
  timeline: "Línea de tiempo",
  motion: "Movimiento",
  render: "Render",
};

/** Mirrors PipelineOptions fields the backend accepts (web.CLIENT_OPTIONS). */
export interface Options {
  phrase: string;
  style_set: string;
  seed: number | null;
  stages: number;
  styles: string[] | null;
  voice: string;
  voice_rate: string;
  voice_pitch: string;
  language: string;
  width: number;
  height: number;
  fps: number;
  fit: string;
  watermark: string;
  subtitles: boolean;
  music_volume: number;
  music_source: string;
  test_mode: boolean;
  force: boolean;
  force_from: string | null;
  reencode_concat: boolean;
  text_provider: string;
  text_model: string;
  image_provider: string;
  image_model: string;
  tts_provider: string;
  motion: string;
  reroll_images: string[];
  reroll_motion: string[];
  /** The user's own prompt for a scene's image reroll, by scene id. */
  image_prompts?: Record<string, string>;
}

export interface StyleSet {
  name: string;
  label: string;
  personas: string[];
}

export interface AppOptions {
  style_sets: StyleSet[];
  languages: { code: string; name: string }[];
  voices: { kokoro: string[]; edge: string[] };
  providers: { text: string[]; image: string[]; tts: string[]; motion: string[] };
  defaults: Options;
}

export interface SystemStatus {
  ffmpeg: boolean;
  encoder: string;
  ollama: boolean;
  ollama_models: string[];
  kokoro: boolean;
  xpu: boolean;
  liveportrait: boolean;
  claude_key: boolean;
  google_key: boolean;
}

export interface HistoryRun {
  name: string;
  phrase: string;
  style_set: string;
  language: string | null;
  duration: number | null;
  test_mode: boolean;
  voice: string;
  social: string;
  mtime: number;
  video_url: string | null;
  scenes: { scene_id: string; level: number; persona: string; text: string; image: string | null }[];
}

/** Events streamed by web.Run over SSE (pipeline.run_pipeline + run lifecycle). */
export type RunEvent = { ts: number } & (
  | { type: "started"; run_id: string; upload_id: string }
  | { type: "scenes"; style_set: string; output_dir: string; scenes: { scene_id: string; level: number; persona: string }[] }
  | { type: "stage"; index: number; total: number; name: StageName; detail: string }
  | { type: "scene"; scene_id: string; kind: "text"; text: string }
  | { type: "scene"; scene_id: string; kind: "image" | "audio" | "motion" | "clip"; cached: boolean; path_url: string | null; prompt?: string }
  | { type: "progress"; stage: StageName; scene_id: string | null; step: number; total: number; label: string }
  | { type: "log"; line: string }
  // Cuento only: the written story, before the images (a preview run ends right after it)
  | { type: "story"; title: string; outline: string; protagonist: string; source: { url: string; author: string; subreddit: string } | null }
  | { type: "done"; video_url: string | null; social: string; output_dir: string; duration: number }
  | { type: "error"; message: string; kind: string }
  | { type: "cancelled" }
  | { type: "queued"; scene_id: string; kind: "image" | "motion" }
  // the running pipeline took a queued reroll: it is redone right now
  | { type: "rerolling"; scene_id: string; kind: "image" | "motion" }
  | { type: "next"; run_id: string }
);
