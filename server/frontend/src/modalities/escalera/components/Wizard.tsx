import { useState, type DragEvent, type ReactNode } from "react";
import { api } from "../api";
import type { AppOptions, Options, SystemStatus } from "../types";
import { Badge, Field, PlayButton, Select, Toggle } from "./ui";
import { apiUrl } from "../../../remote";

export interface Upload {
  id: string;
  url: string;
}

type SetOpt = <K extends keyof Options>(key: K, value: Options[K]) => void;

interface PanelProps {
  opts: Options;
  setOpt: SetOpt;
  app: AppOptions;
  system: SystemStatus | null;
}

const PHRASE_EXAMPLES = ["Tengo hambre", "Apaga eso", "No me apetece", "Llego tarde"];

/** Collapsed-by-default group; the summary shows current values so it rarely needs opening. */
export function Section({ title, summary, children }: { title: string; summary: string; children: ReactNode }) {
  return (
    <details className="group rounded-xl border border-stone-200 dark:border-stone-800">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 marker:hidden">
        <span className="font-medium">{title}</span>
        <span className="flex min-w-0 items-center gap-2 text-xs text-stone-500">
          <span className="truncate">{summary}</span>
          <span className="transition group-open:rotate-90" aria-hidden>
            ▸
          </span>
        </span>
      </summary>
      <div className="space-y-5 border-t border-stone-200 px-4 py-4 dark:border-stone-800">{children}</div>
    </details>
  );
}

export function PhotoPicker({
  fit,
  upload,
  onUpload,
  uploadFn = api.upload,
  onClear,
  label = "Retrato: arrastra una foto o haz clic para elegirla",
  empty = "📷 Arrastra tu foto aquí o haz clic",
}: {
  fit: string;
  upload: Upload | null;
  onUpload: (u: Upload) => void;
  uploadFn?: (file: File) => Promise<{ upload_id: string; url: string }>;
  /** optional photo: renders a "Quitar foto" button */
  onClear?: () => void;
  label?: string;
  empty?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  const send = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const res = await uploadFn(file);
      onUpload({ id: res.upload_id, url: res.url });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    send(e.dataTransfer.files[0]);
  };

  return (
    <div>
      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        aria-label={label}
        className={`relative mx-auto flex aspect-[9/16] max-h-[420px] w-full max-w-[236px] cursor-pointer items-center justify-center overflow-hidden rounded-2xl border-2 border-dashed transition ${
          drag ? "border-orange-500 bg-orange-50 dark:bg-orange-950/30" : "border-stone-300 dark:border-stone-700"
        }`}
      >
        {upload ? (
          <img src={apiUrl(upload.url)} alt="Retrato subido" className={`h-full w-full ${fit === "crop" ? "object-cover" : "object-contain"}`} />
        ) : (
          <span className="px-4 text-center text-sm text-stone-500">
            {busy ? "Subiendo…" : empty}
          </span>
        )}
        <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={(e) => send(e.target.files?.[0])} />
        {upload && <span className="absolute bottom-2 left-2 rounded-md bg-black/60 px-2 py-0.5 text-xs text-white">Cambiar foto</span>}
      </label>
      {upload && onClear && (
        <div className="mt-2 text-center">
          <button type="button" className="btn-ghost px-2.5 py-1 text-xs" onClick={onClear}>
            ✕ Quitar foto
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-2 text-center text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}

export function EssentialFields({ opts, setOpt, app }: Pick<PanelProps, "opts" | "setOpt" | "app">) {
  const set = app.style_sets.find((s) => s.name === opts.style_set);
  const styleHint =
    opts.style_set === "random" ? "Un set completo elegido al azar" : opts.style_set === "mix" ? "Un personaje distinto por nivel" : set?.personas.join(" → ");
  return (
    <div className="space-y-5">
      <Field label="Frase">
        {(id) => (
          <>
            <input
              id={id}
              className="input text-lg"
              placeholder='p. ej. "Apaga eso"'
              value={opts.phrase}
              maxLength={140}
              onChange={(e) => setOpt("phrase", e.target.value)}
            />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {PHRASE_EXAMPLES.map((p) => (
                <button key={p} type="button" className="btn-ghost px-2.5 py-1 text-xs" onClick={() => setOpt("phrase", p)}>
                  {p}
                </button>
              ))}
            </div>
          </>
        )}
      </Field>
      <Field label="Estilo" hint={styleHint}>
        {(id) => (
          <Select
            id={id}
            value={opts.style_set}
            onChange={(v) => setOpt("style_set", v)}
            options={[
              { value: "random", label: "🎲 Al azar" },
              { value: "mix", label: "🔀 Mezcla" },
              ...app.style_sets.map((s) => ({ value: s.name, label: s.label[0].toUpperCase() + s.label.slice(1) })),
            ]}
          />
        )}
      </Field>
    </div>
  );
}

export const MOTION_CHOICES = [
  { value: "none", label: "Fija", hint: "Imagen fija, lo más rápido" },
  { value: "rotate3d", label: "Rotación 3D", hint: "Separa al personaje del fondo y la cámara gira a su alrededor · ~1,5 min por escena" },
  { value: "liveportrait", label: "Cara viva", hint: "Anima la cara (LivePortrait) · ~7 min por escena en CPU" },
];

export function MotionPicker({
  value,
  onChange,
  system,
  choices = MOTION_CHOICES,
}: {
  value: string;
  onChange: (v: string) => void;
  system: SystemStatus | null;
  choices?: typeof MOTION_CHOICES;
}) {
  const ready: Record<string, boolean | null> = {
    none: true,
    rotate3d: true,
    liveportrait: system ? system.liveportrait : null,
  };
  const current = choices.find((m) => m.value === value) ?? choices[0];
  return (
    <fieldset>
      <legend className="label">Movimiento</legend>
      <div className={`grid ${choices.length === 2 ? "grid-cols-2" : "grid-cols-3"} gap-1 rounded-lg bg-stone-100 p-1 dark:bg-stone-800`} role="radiogroup">
        {choices.map((m) => (
          <button
            key={m.value}
            type="button"
            role="radio"
            aria-checked={value === m.value}
            onClick={() => onChange(m.value)}
            className={`truncate rounded-md px-2 py-1.5 text-xs font-medium transition ${
              value === m.value ? "bg-white shadow dark:bg-stone-950" : "text-stone-500 hover:text-stone-900 dark:hover:text-stone-100"
            }`}
          >
            {m.label}
            {ready[m.value] === false && " ⚠"}
          </button>
        ))}
      </div>
      <p className="hint">
        {current.hint}
        {ready[current.value] === false &&
          (current.value === "liveportrait" ? " · no instalado: ejecuta setup-liveportrait.ps1" : " · GPU no disponible")}
      </p>
    </fieldset>
  );
}

export function VoiceMusicPanel({ opts, setOpt, app }: PanelProps) {
  const voices = opts.tts_provider === "kokoro" ? app.voices.kokoro : app.voices.edge;
  const summary = [opts.voice, opts.subtitles ? "subtítulos" : "sin subtítulos"].join(" · ");
  return (
    <Section title="Voz" summary={summary}>
      <Field label="Voz del narrador">
        {(id) => (
          <div className="flex gap-2">
            <Select id={id} value={opts.voice} onChange={(v) => setOpt("voice", v)} options={voices.map((v) => ({ value: v, label: v }))} />
            <PlayButton
              label="Escuchar voz"
              src={api.voicePreviewUrl({ provider: opts.tts_provider, voice: opts.voice, language: opts.language, rate: opts.voice_rate, pitch: opts.voice_pitch })}
            />
          </div>
        )}
      </Field>
      <Toggle checked={opts.subtitles} onChange={(v) => setOpt("subtitles", v)} label="Subtítulos" />
    </Section>
  );
}

const ENGINE_INFO: Record<string, string> = {
  "auto:text": "Ollama local si está activo; si no, Claude o Gemini",
  "ollama:text": "Local y gratis · ~30-60 s",
  "claude:text": "Nube · necesita ANTHROPIC_API_KEY",
  "gemini:text": "Nube · necesita GOOGLE_API_KEY",
  "auto:image": "FLUX Kontext local si está instalado; si no, Gemini",
  "flux-kontext:image": "Local · mejor calidad · ~12-15 min por imagen",
  "sdxl-face:image": "Local · rápido · ~1 min por imagen",
  "gemini:image": "Nube · ~15 s por imagen · necesita GOOGLE_API_KEY",
  "kokoro:tts": "Local en CPU · segundos",
  "edge:tts": "Online · voces neurales de Microsoft",
};

function engineReady(kind: string, provider: string, s: SystemStatus | null): boolean | null {
  if (!s) return null;
  const table: Record<string, boolean> = {
    "auto:text": s.ollama || s.claude_key || s.google_key,
    "ollama:text": s.ollama,
    "claude:text": s.claude_key,
    "gemini:text": s.google_key,
    "auto:image": s.xpu || s.google_key,
    "flux-kontext:image": s.xpu,
    "sdxl-face:image": s.xpu,
    "gemini:image": s.google_key,
    "kokoro:tts": s.kokoro,
    "edge:tts": true,
  };
  return table[`${provider}:${kind}`] ?? null;
}

export function EnginesPanel({ opts, setOpt, app, system }: PanelProps) {
  const engine = (kind: "text" | "image" | "tts", key: "text_provider" | "image_provider" | "tts_provider", label: string) => {
    const value = opts[key];
    const ready = engineReady(kind, value, system);
    return (
      <Field label={label}>
        {(id) => (
          <>
            <Select
              id={id}
              value={value}
              onChange={(v) => {
                setOpt(key, v);
                if (key === "tts_provider") {
                  const list = v === "kokoro" ? app.voices.kokoro : app.voices.edge;
                  if (!list.includes(opts.voice)) setOpt("voice", list[0]);
                }
              }}
              options={app.providers[kind].map((p) => ({ value: p, label: p }))}
            />
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Badge ok={ready}>{ready === null ? "comprobando…" : ready ? "disponible" : "no disponible"}</Badge>
              <span className="hint mt-0">{ENGINE_INFO[`${value}:${kind}`]}</span>
            </div>
          </>
        )}
      </Field>
    );
  };

  return (
    <Section title="Motores de IA" summary={`${opts.text_provider} · ${opts.image_provider} · ${opts.tts_provider}`}>
      <div className="grid gap-5 md:grid-cols-3">
        {engine("text", "text_provider", "Texto")}
        {engine("image", "image_provider", "Imágenes")}
        {engine("tts", "tts_provider", "Voz")}
      </div>
      {opts.text_provider === "ollama" && system?.ollama_models.length ? (
        <Field label="Modelo de Ollama" hint="gpt-oss:20b: mejor estilo por nivel (~3 min); qwen3:8b: ~20 s pero más repetitivo">
          {(id) => (
            <Select
              id={id}
              // the backend swaps a non-Ollama model name for its Ollama default
              value={system.ollama_models.includes(opts.text_model) ? opts.text_model : app.defaults.text_model}
              onChange={(v) => setOpt("text_model", v)}
              options={[
                { value: app.defaults.text_model, label: `Por defecto (${app.defaults.text_model})` },
                ...system.ollama_models.filter((m) => !m.includes("embed")).map((m) => ({ value: m, label: m })),
              ]}
            />
          )}
        </Field>
      ) : null}
    </Section>
  );
}

export function AdvancedPanel({ opts, setOpt, app }: PanelProps) {
  const language = app.languages.find((l) => l.code === opts.language)?.name ?? opts.language;
  return (
    <Section title="Avanzado" summary={`${opts.stages} escenas · ${language} · ${opts.width}×${opts.height}`}>
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        <Field label={`Escenas: ${opts.stages}`}>
          {(id) => (
            <input
              id={id}
              type="range"
              min={2}
              max={5}
              value={opts.stages}
              onChange={(e) => setOpt("stages", Number(e.target.value))}
              className="w-full accent-orange-600"
            />
          )}
        </Field>
        <Field label="Idioma">
          {(id) => (
            <Select id={id} value={opts.language} onChange={(v) => setOpt("language", v)} options={app.languages.map((l) => ({ value: l.code, label: l.name }))} />
          )}
        </Field>
        <Field label="Encuadre">
          {(id) => (
            <Select
              id={id}
              value={opts.fit}
              onChange={(v) => setOpt("fit", v)}
              options={[
                { value: "crop", label: "Llenar pantalla" },
                { value: "blur", label: "Fondo difuminado" },
                { value: "pad", label: "Bandas negras" },
              ]}
            />
          )}
        </Field>
        <Field label="Marca de agua" hint="Vacío = sin marca">
          {(id) => <input id={id} className="input" value={opts.watermark} onChange={(e) => setOpt("watermark", e.target.value)} />}
        </Field>
        <Field label="Seed" hint="Vacío = aleatorio">
          {(id) => (
            <input
              id={id}
              type="number"
              className="input"
              value={opts.seed ?? ""}
              onChange={(e) => setOpt("seed", e.target.value === "" ? null : Number(e.target.value))}
            />
          )}
        </Field>
        <Field label="Resolución">
          {(id) => (
            <Select
              id={id}
              value={`${opts.width}x${opts.height}`}
              onChange={(v) => {
                const [w, h] = v.split("x").map(Number);
                setOpt("width", w);
                setOpt("height", h);
              }}
              options={[
                { value: "1080x1920", label: "1080×1920 (Full HD)" },
                { value: "720x1280", label: "720×1280 (HD, rápido)" },
                { value: "576x1024", label: "576×1024 (ligero)" },
                { value: "540x960", label: "540×960 (mínimo TikTok)" },
                { value: "1080x1080", label: "1080×1080 (cuadrado)" },
              ]}
            />
          )}
        </Field>
        <Field label="FPS">
          {(id) => (
            <Select id={id} value={String(opts.fps)} onChange={(v) => setOpt("fps", Number(v))} options={["24", "30", "60"].map((f) => ({ value: f, label: f }))} />
          )}
        </Field>
        <Field label="Velocidad de voz" hint="p. ej. -8%">
          {(id) => <input id={id} className="input" value={opts.voice_rate} onChange={(e) => setOpt("voice_rate", e.target.value)} />}
        </Field>
        <Field label="Tono de voz" hint="Solo edge-tts">
          {(id) => <input id={id} className="input" value={opts.voice_pitch} onChange={(e) => setOpt("voice_pitch", e.target.value)} />}
        </Field>
      </div>
      <Toggle checked={opts.force} onChange={(v) => setOpt("force", v)} label="Ignorar caché" hint="Regenera todo desde cero" />
    </Section>
  );
}
