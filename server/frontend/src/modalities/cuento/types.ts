// The run events and system status are Escalera's: the story pipeline emits
// the same stages and scene events, so runState and ProgressView are shared.
export type { RunEvent, SystemStatus } from "../escalera/types";

/** Mirrors cuento.config.StoryOptions fields the backend accepts (CLIENT_OPTIONS). */
export interface StoryOptions {
  premise: string;
  source: string; // Reddit post URL the story adapts ("" = invented)
  preview: boolean; // stop after the text: review the script first
  tone: string;
  genre: string;
  style: string;
  scenes: number;
  seed: number | null;
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
  test_mode: boolean;
  force: boolean;
  force_from: string | null;
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

export interface Preset {
  subreddit: string;
  label: string;
  tone: string;
  genre: string;
}

export interface SourceStory {
  url: string;
  title: string;
  author: string;
  subreddit: string;
  words: number;
  excerpt: string;
}

export interface SourceList {
  subreddit: string;
  period: string;
  fetched_at: number;
  stories: SourceStory[];
  stale: boolean;
  retry_in: number | null;
}

export interface AppOptions {
  tones: { id: string; label: string; genres: { id: string; label: string }[] }[];
  styles: { id: string; label: string }[];
  languages: { code: string; name: string }[];
  voices: { kokoro: string[]; edge: string[] };
  providers: { text: string[]; image: string[]; tts: string[]; motion: string[] };
  defaults: StoryOptions;
}
