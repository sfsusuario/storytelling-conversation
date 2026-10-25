import { Badge, Field, PlayButton, Select, Toggle } from "../escalera/components/ui";
import { MOTION_CHOICES, MotionPicker, PhotoPicker, Section, type Upload } from "../escalera/components/Wizard";
import { api } from "./api";
import type { AppOptions, StoryOptions, SystemStatus } from "./types";

type SetOpt = <K extends keyof StoryOptions>(key: K, value: StoryOptions[K]) => void;

const EXAMPLES: Record<string, string[]> = {
  infantil: ["Una tortuga que quiere volar", "El dragón que tenía miedo de la oscuridad", "La nube que no sabía llover"],
  general: ["Un faro que se enciende solo cada noche", "La última cafetería abierta de la galaxia", "El vecino que nunca duerme"],
};

const IMAGE_INFO: Record<string, string> = {
  auto: "Sin foto: SDXL local · con foto: FLUX Kontext",
  sdxl: "Local · personajes inventados · ~1 min por escena",
  "flux-kontext": "Local · tu foto como protagonista · ~12 min por escena",
};
const TEXT_INFO: Record<string, string> = {
  auto: "Ollama local si está activo; si no, Claude o Gemini",
  ollama: "Local y gratis",
  claude: "Nube · necesita ANTHROPIC_API_KEY",
  gemini: "Nube · necesita GOOGLE_API_KEY",
};

export function StoryForm({
  app,
  opts,
  setOpt,
  system,
  upload,
  onUpload,
  onClear,
  error,
  onStart,
}: {
  app: AppOptions;
  opts: StoryOptions;
  setOpt: SetOpt;
  system: SystemStatus | null;
  upload: Upload | null;
  onUpload: (u: Upload) => void;
  onClear: () => void;
  error: string | null;
  onStart: () => void;
}) {
  const tone = app.tones.find((t) => t.id === opts.tone) ?? app.tones[0];
  const voices = opts.tts_provider === "kokoro" ? app.voices.kokoro : app.voices.edge;
  const ready = Boolean(opts.premise.trim());
  const language = app.languages.find((l) => l.code === opts.language)?.name ?? opts.language;
  // LivePortrait animates a real face: only offered with a photo
  const motionChoices = upload ? MOTION_CHOICES : MOTION_CHOICES.filter((m) => m.value !== "liveportrait");
  const textReady = system ? (opts.text_provider === "auto" ? system.ollama || system.claude_key || system.google_key : opts.text_provider === "ollama" ? system.ollama : opts.text_provider === "claude" ? system.claude_key : system.google_key) : null;

  const setTone = (id: string) => {
    setOpt("tone", id);
    const t = app.tones.find((x) => x.id === id);
    if (t && !t.genres.some((g) => g.id === opts.genre)) setOpt("genre", t.genres[0].id);
  };

  return (
    <>
      <div className="card grid gap-6 sm:grid-cols-[236px_1fr]">
        <div>
          <PhotoPicker
            fit="crop"
            upload={upload}
            onUpload={onUpload}
            uploadFn={api.upload}
            onClear={onClear}
            label="Foto del protagonista (opcional)"
            empty="📷 Foto del protagonista (opcional)"
          />
          <p className="hint text-center">
            {upload ? "Tú serás el protagonista (FLUX Kontext, ~12 min por escena)" : "Sin foto: personajes inventados (SDXL local, ~1 min por escena)"}
          </p>
        </div>
        <div className="flex flex-col gap-5">
          <Field label="¿De qué va el cuento?">
            {(id) => (
              <>
                <textarea
                  id={id}
                  className="input text-lg"
                  rows={3}
                  maxLength={300}
                  placeholder='p. ej. "Una tortuga que quiere volar"'
                  value={opts.premise}
                  onChange={(e) => setOpt("premise", e.target.value)}
                />
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(EXAMPLES[opts.tone] ?? []).map((p) => (
                    <button key={p} type="button" className="btn-ghost px-2.5 py-1 text-xs" onClick={() => setOpt("premise", p)}>
                      {p}
                    </button>
                  ))}
                </div>
              </>
            )}
          </Field>
          <fieldset>
            <legend className="label">Tono</legend>
            <div className="grid grid-cols-2 gap-1 rounded-lg bg-stone-100 p-1 dark:bg-stone-800" role="radiogroup">
              {app.tones.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="radio"
                  aria-checked={opts.tone === t.id}
                  onClick={() => setTone(t.id)}
                  className={`truncate rounded-md px-2 py-1.5 text-xs font-medium transition ${
                    opts.tone === t.id ? "bg-white shadow dark:bg-stone-950" : "text-stone-500 hover:text-stone-900 dark:hover:text-stone-100"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </fieldset>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Género">
              {(id) => <Select id={id} value={opts.genre} onChange={(v) => setOpt("genre", v)} options={tone.genres.map((g) => ({ value: g.id, label: g.label }))} />}
            </Field>
            <Field label="Estilo visual">
              {(id) => <Select id={id} value={opts.style} onChange={(v) => setOpt("style", v)} options={app.styles.map((s) => ({ value: s.id, label: s.label }))} />}
            </Field>
          </div>
          <Field label={`Escenas: ${opts.scenes}`} hint="Unos 8-10 segundos por escena">
            {(id) => (
              <input id={id} type="range" min={4} max={8} value={opts.scenes} onChange={(e) => setOpt("scenes", Number(e.target.value))} className="w-full accent-orange-600" />
            )}
          </Field>
          <MotionPicker value={opts.motion} onChange={(v) => setOpt("motion", v)} system={system} choices={motionChoices} />
          {opts.motion === "rotate3d" && <p className="hint -mt-3">Una escena sin una figura clara se queda fija.</p>}
          <Toggle checked={opts.test_mode} onChange={(v) => setOpt("test_mode", v)} label="Modo prueba" hint="Imágenes de relleno: rápido, para probar el cuento y la voz" />
          <div className="mt-auto">
            {error && (
              <p role="alert" className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
                {error}
              </p>
            )}
            <button type="button" className="btn-primary w-full py-3 text-base" disabled={!ready} onClick={onStart}>
              📖 Crear cuento
            </button>
            {!ready && <p className="hint text-center">Escribe de qué va el cuento</p>}
          </div>
        </div>
      </div>

      <Section title="Voz" summary={[opts.voice, opts.subtitles ? "subtítulos" : "sin subtítulos"].join(" · ")}>
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
        <Field label="Motor de voz">
          {(id) => (
            <Select
              id={id}
              value={opts.tts_provider}
              onChange={(v) => {
                setOpt("tts_provider", v);
                const list = v === "kokoro" ? app.voices.kokoro : app.voices.edge;
                if (!list.includes(opts.voice)) setOpt("voice", list[0]);
              }}
              options={app.providers.tts.map((p) => ({ value: p, label: p === "kokoro" ? "kokoro (local)" : "edge (online)" }))}
            />
          )}
        </Field>
        <Toggle checked={opts.subtitles} onChange={(v) => setOpt("subtitles", v)} label="Subtítulos" />
      </Section>

      <Section title="Motores de IA" summary={`${opts.text_provider} · ${opts.image_provider}`}>
        <div className="grid gap-5 md:grid-cols-2">
          <Field label="Imágenes">
            {(id) => (
              <>
                <Select id={id} value={opts.image_provider} onChange={(v) => setOpt("image_provider", v)} options={app.providers.image.map((p) => ({ value: p, label: p }))} />
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <Badge ok={system ? system.xpu : null}>{system === null ? "comprobando…" : system.xpu ? "GPU Intel lista" : "GPU Intel no disponible"}</Badge>
                  <span className="hint mt-0">{IMAGE_INFO[opts.image_provider]}</span>
                </div>
              </>
            )}
          </Field>
          <Field label="Texto">
            {(id) => (
              <>
                <Select id={id} value={opts.text_provider} onChange={(v) => setOpt("text_provider", v)} options={app.providers.text.map((p) => ({ value: p, label: p }))} />
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <Badge ok={textReady}>{textReady === null ? "comprobando…" : textReady ? "disponible" : "no disponible"}</Badge>
                  <span className="hint mt-0">{TEXT_INFO[opts.text_provider]}</span>
                </div>
              </>
            )}
          </Field>
        </div>
        {opts.text_provider === "ollama" && system?.ollama_models.length ? (
          <Field label="Modelo de Ollama">
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

      <Section title="Avanzado" summary={`${language} · ${opts.width}×${opts.height}`}>
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Idioma">
            {(id) => <Select id={id} value={opts.language} onChange={(v) => setOpt("language", v)} options={app.languages.map((l) => ({ value: l.code, label: l.name }))} />}
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
            {(id) => <input id={id} type="number" className="input" value={opts.seed ?? ""} onChange={(e) => setOpt("seed", e.target.value === "" ? null : Number(e.target.value))} />}
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
                  { value: "540x960", label: "540×960 (mínimo TikTok)" },
                ]}
              />
            )}
          </Field>
          <Field label="FPS">
            {(id) => <Select id={id} value={String(opts.fps)} onChange={(v) => setOpt("fps", Number(v))} options={["24", "30", "60"].map((f) => ({ value: f, label: f }))} />}
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
    </>
  );
}
