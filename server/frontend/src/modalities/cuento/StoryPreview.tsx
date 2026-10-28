import { useState } from "react";
import { CopyButton } from "../escalera/components/ui";
import type { RunState, SceneState } from "../escalera/runState";
import type { Shot } from "../escalera/types";
import type { StoryEdits } from "./types";

type SceneDraft = Shot & { narration: string };
const EMPTY_SHOT: Shot = { action: "", setting: "", key_object: "", shot: "", character: "" };
// field -> (label, hint); every field but the narration is read by the image model, in English
const SHOT_FIELDS: [keyof Shot, string, string][] = [
  ["character", "Personaje principal en esta escena", "Aspecto del personaje aquí (en inglés); vacío = el protagonista del cuento"],
  ["action", "Acción", "Qué hace el personaje, o la cosa vista, en inglés"],
  ["setting", "Lugar y momento", "p. ej. forest edge, night"],
  ["key_object", "Objeto clave", "El detalle del que depende la escena; vacío si ninguno"],
  ["shot", "Cámara y encuadre", "Distancia, luz y ambiente: wide shot, medium shot, close-up…"],
];

const draftOf = (sc: SceneState): SceneDraft => ({ ...EMPTY_SHOT, ...(sc.shot ?? {}), narration: sc.text ?? "" });

/** What Claude (or any LLM) gets with the script: the image model's limits, so the fix keeps working. */
const CLAUDE_INSTRUCTIONS = `You are improving the script of a short illustrated vertical video. Return ONLY a JSON object with the same shape as "script" below, same number of scenes and the same "scene_id" values.
Rules the generator depends on:
- "narration": keep its language and point of view, one or two sentences read aloud, 35 words at most, no quotes, emojis, markdown or stage directions; one tense; every scene moves the story forward and the last one closes it.
- The image fields are read by an image model that ONLY understands English and cannot draw text, letters, signs, names or speech bubbles; it draws one still picture per scene.
- "character": the main character's look in this scene, in English, 12 words at most (article + age or species + gender + one distinctive garment or trait, like "a tired man in a grey hoodie"); "" means the script's "protagonist". Keep it consistent across scenes unless the story changes the look.
- "action": present tense, 12 words at most; either "the protagonist" doing one concrete visible thing, or, when the scene is about something seen (a creature, a door, what a photo shows), THAT thing itself, large in frame, without the protagonist.
- "setting": place and time of day, 8 words at most. "key_object": the one object or detail the narration hinges on, 5 words at most, or "".
- "shot": camera distance, light and mood, 8 words at most; mostly "wide shot" or "medium shot", "close-up" only for a small detail.
- Consecutive scenes must differ in place, distance or what is in frame. The picture shows only what that scene's narration says.
- "protagonist" and "title" may be improved too (title 6 words at most, in the narration's language).`;

/** The text copied for Claude: instructions, the real story's URL (if any) and the current script. */
export function exportForClaude(state: RunState, drafts: Record<string, SceneDraft>, title: string, protagonist: string): string {
  const script = {
    title,
    protagonist,
    scenes: state.scenes.map((sc) => ({ scene_id: sc.scene_id, ...(drafts[sc.scene_id] ?? draftOf(sc)) })),
  };
  const source = state.story?.source ? `\nThe story adapts this real post (keep its events and ending): ${state.story.source.url}\n` : "";
  const outline = state.story?.outline ? `\nOutline: ${state.story.outline}\n` : "";
  return `${CLAUDE_INSTRUCTIONS}\n${source}${outline}\nscript:\n${JSON.stringify(script, null, 2)}`;
}

type ClaudeReply = { title?: string; protagonist?: string; scenes: Record<string, SceneDraft> };

/** Claude's answer (JSON, with or without a code fence) matched to the scenes by scene_id or position. Throws a Spanish message on a bad reply. */
export function parseClaudeReply(text: string, scenes: SceneState[]): ClaudeReply {
  const raw = text.trim();
  let data: unknown;
  try {
    data = JSON.parse(raw.slice(raw.indexOf("{"), raw.lastIndexOf("}") + 1));
  } catch {
    throw new Error("No es un JSON válido: pega solo la respuesta de Claude.");
  }
  const obj = data as { title?: unknown; protagonist?: unknown; scenes?: unknown };
  const list = Array.isArray(obj.scenes) ? (obj.scenes as Record<string, unknown>[]) : null;
  if (!list || list.length !== scenes.length) throw new Error(`El JSON debe traer ${scenes.length} escenas en "scenes".`);
  const str = (v: unknown) => (typeof v === "string" ? v.trim() : "");
  const out: ClaudeReply = { scenes: {} };
  if (str(obj.title)) out.title = str(obj.title);
  if (str(obj.protagonist)) out.protagonist = str(obj.protagonist);
  scenes.forEach((sc, i) => {
    const got = list.find((x) => x.scene_id === sc.scene_id) ?? list[i];
    const before = draftOf(sc);
    const keys = Object.keys(before) as (keyof SceneDraft)[];
    out.scenes[sc.scene_id] = { ...before, ...Object.fromEntries(keys.filter((k) => k in got).map((k) => [k, str(got[k])])) };
    if (!out.scenes[sc.scene_id].narration) throw new Error(`La escena ${i + 1} viene sin narración.`);
  });
  return out;
}

/** Only what the user changed, so the backend keeps the model's text for the rest. */
export function diffEdits(scenes: SceneState[], drafts: Record<string, SceneDraft>, title: [string, string], protagonist: [string, string]): StoryEdits {
  const edits: StoryEdits = {};
  if (title[1].trim() && title[1] !== title[0]) edits.title = title[1];
  if (protagonist[1].trim() && protagonist[1] !== protagonist[0]) edits.protagonist = protagonist[1];
  for (const sc of scenes) {
    const before = draftOf(sc);
    const after = drafts[sc.scene_id];
    if (!after) continue;
    const changed = Object.fromEntries((Object.keys(after) as (keyof SceneDraft)[]).filter((k) => after[k] !== before[k]).map((k) => [k, after[k]]));
    if (Object.keys(changed).length) edits.scenes = { ...(edits.scenes ?? {}), [sc.scene_id]: changed };
  }
  return edits;
}

/** A preview run ended: the script is written, nothing rendered yet. The
 * user reviews (and edits) narration, storyboard and characters, then continues. */
export function StoryPreview({ state, onContinue, onAnother, onBack }: { state: RunState; onContinue: (edits: StoryEdits) => void; onAnother: () => void; onBack: () => void }) {
  const story = state.story;
  const social = state.result?.social ?? "";
  const [title, setTitle] = useState(story?.title ?? "");
  const [protagonist, setProtagonist] = useState(story?.protagonist ?? "");
  const [drafts, setDrafts] = useState<Record<string, SceneDraft>>(() => Object.fromEntries(state.scenes.map((sc) => [sc.scene_id, draftOf(sc)])));
  const [open, setOpen] = useState<string | null>(null);
  const [paste, setPaste] = useState<{ text: string; error: string | null } | null>(null);
  const setField = (id: string, key: keyof SceneDraft, value: string) => setDrafts((d) => ({ ...d, [id]: { ...d[id], [key]: value } }));
  const edits = diffEdits(state.scenes, drafts, [story?.title ?? "", title], [story?.protagonist ?? "", protagonist]);
  const dirty = Object.keys(edits).length > 0;
  const applyPaste = () => {
    if (!paste) return;
    try {
      const got = parseClaudeReply(paste.text, state.scenes);
      setDrafts(got.scenes);
      if (got.title) setTitle(got.title);
      if (got.protagonist) setProtagonist(got.protagonist);
      setPaste(null);
    } catch (e) {
      setPaste({ ...paste, error: (e as Error).message });
    }
  };

  return (
    <section className="mx-auto max-w-3xl space-y-4" aria-labelledby="preview-title">
      <div className="card space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="preview-title" className="text-xl font-semibold">
            📝 Revisa el guion
          </h2>
          <div className="flex items-center gap-1.5" aria-label="Mejorar con Claude">
            <CopyButton text={exportForClaude(state, drafts, title, protagonist)} label="📋 Copiar para Claude" className="btn-ghost px-2.5 py-1 text-xs" />
            <button type="button" className="btn-ghost px-2.5 py-1 text-xs" onClick={() => setPaste({ text: "", error: null })}>
              📥 Pegar respuesta de Claude
            </button>
          </div>
        </div>
        <p className="hint">«Copiar» lleva al portapapeles las instrucciones, la URL de la historia y el guion en JSON para pedirle a Claude que lo mejore; luego pega aquí su respuesta.</p>
        {story?.outline && <p className="text-sm text-stone-500">{story.outline}</p>}
        {story?.source && (
          <p className="text-xs text-stone-500">
            Basado en{" "}
            <a className="underline" href={story.source.url} target="_blank" rel="noreferrer">
              u/{story.source.author} en r/{story.source.subreddit}
            </a>
          </p>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="label">Título</span>
            <input className="input" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">Protagonista (en inglés, para las imágenes)</span>
            <input className="input" value={protagonist} maxLength={300} onChange={(e) => setProtagonist(e.target.value)} />
          </label>
        </div>
        <ol className="space-y-2">
          {state.scenes.map((sc) => {
            const d = drafts[sc.scene_id] ?? draftOf(sc);
            const expanded = open === sc.scene_id;
            return (
              <li key={sc.scene_id} className="rounded-lg bg-stone-50 p-3 text-sm dark:bg-stone-800">
                <div className="flex gap-3">
                  <span className="w-5 shrink-0 pt-2 font-bold text-orange-600">{sc.level}</span>
                  <label className="block grow">
                    <span className="sr-only">Narración de la escena {sc.level}</span>
                    <textarea className="input" rows={2} maxLength={600} value={d.narration} onChange={(e) => setField(sc.scene_id, "narration", e.target.value)} />
                  </label>
                  <button type="button" className="btn-ghost self-start px-2 py-1 text-xs" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : sc.scene_id)}>
                    {expanded ? "▴ Imagen" : "▾ Imagen"}
                  </button>
                </div>
                {expanded && (
                  <div className="mt-3 grid gap-2 pl-8 sm:grid-cols-2">
                    {SHOT_FIELDS.map(([key, label, hint]) => (
                      <label key={key} className={`block ${key === "character" || key === "action" ? "sm:col-span-2" : ""}`}>
                        <span className="label">{label}</span>
                        <input
                          className="input"
                          value={d[key]}
                          maxLength={400}
                          placeholder={key === "character" ? protagonist : undefined}
                          onChange={(e) => setField(sc.scene_id, key, e.target.value)}
                        />
                        <span className="hint block">{hint}</span>
                      </label>
                    ))}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
        <div className="flex flex-wrap gap-2 pt-2">
          <button type="button" className="btn-primary" onClick={() => onContinue(edits)}>
            🎬 {dirty ? "Guardar cambios y continuar" : "Continuar"}: imágenes, voz y video
          </button>
          <button type="button" className="btn-ghost" onClick={onAnother}>
            🎲 Otro guion
          </button>
          <button type="button" className="btn-ghost" onClick={onBack}>
            Volver
          </button>
        </div>
        <p className="hint mb-0">Al continuar se usa este guion con tus cambios; «Otro guion» lo escribe de nuevo.</p>
      </div>
      {paste && (
        <div role="dialog" aria-modal="true" aria-labelledby="paste-title" className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setPaste(null)}>
          <div className="card w-full max-w-2xl space-y-3" onClick={(e) => e.stopPropagation()}>
            <h3 id="paste-title" className="font-semibold">
              📥 Respuesta de Claude
            </h3>
            <textarea
              className="input font-mono text-xs"
              rows={14}
              autoFocus
              placeholder='{ "title": ..., "protagonist": ..., "scenes": [ ... ] }'
              value={paste.text}
              onChange={(e) => setPaste({ text: e.target.value, error: null })}
            />
            {paste.error && (
              <p role="alert" className="rounded-lg bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
                {paste.error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-ghost" onClick={() => setPaste(null)}>
                Cancelar
              </button>
              <button type="button" className="btn-primary" disabled={!paste.text.trim()} onClick={applyPaste}>
                Aplicar al guion
              </button>
            </div>
            <p className="hint mb-0">Sustituye los campos del formulario; nada se genera hasta que pulses «Continuar».</p>
          </div>
        </div>
      )}
      {social && (
        <div className="card space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold">📣 Texto para redes</h3>
            <CopyButton text={social} />
          </div>
          <p className="whitespace-pre-wrap text-sm text-stone-700 dark:text-stone-300">{social}</p>
        </div>
      )}
    </section>
  );
}
