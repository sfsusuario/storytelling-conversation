// The run events and system status are Escalera's: the story pipeline emits
// the same stages and scene events, so runState and ProgressView are shared.
export type { RunEvent, SystemStatus } from "../escalera/types";

/** Mirrors cuento.config.StoryOptions fields the backend accepts (CLIENT_OPTIONS). */
export interface StoryOptions {
  premise: string;
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
}

export interface AppOptions {
  tones: { id: string; label: string; genres: { id: string; label: string }[] }[];
  styles: { id: string; label: string }[];
  languages: { code: string; name: string }[];
  voices: { kokoro: string[]; edge: string[] };
  providers: { text: string[]; image: string[]; tts: string[]; motion: string[] };
  defaults: StoryOptions;
}
