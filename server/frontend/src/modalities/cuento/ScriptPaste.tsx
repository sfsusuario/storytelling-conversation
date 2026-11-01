import { useEffect, useRef, useState } from "react";
import { CopyButton } from "../escalera/components/ui";
import { api } from "./api";
import type { StoryOptions, StoryScript } from "./types";

const MIN_SCENES = 4;
const MAX_SCENES = 8;
const PROMPT_MARK = "JSON shape:";
const IMAGE_FIELDS = ["action", "setting", "key_object", "shot", "character"] as const;

/** The LLM's answer (JSON, with or without a code fence) as a script. Throws
 * a Spanish message on what would fail; image fields that do not look English
 * come back as warnings, because the image model only reads English. */
export function parseScript(text: string): { script: StoryScript; warnings: string[] } {
  const raw = text.trim();
  if (raw.includes(PROMPT_MARK)) throw new Error("Esto es el prompt. Pégaselo a tu modelo y aquí pega lo que responda.");
  const start = raw.indexOf("{");
  if (start < 0) throw new Error("La respuesta no trae un objeto JSON.");
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(raw.slice(start, raw.lastIndexOf("}") + 1));
  } catch (e) {
    throw new Error(`JSON inválido: ${(e as Error).message}`);
  }
  const str = (v: unknown, where: string) => {
    if (v === undefined || v === null) return "";
    if (typeof v !== "string") throw new Error(`${where} debe ser texto.`);
    return v.trim();
  };
  const list = data.scenes;
  if (!Array.isArray(list) || list.length < MIN_SCENES || list.length > MAX_SCENES)
    throw new Error(`"scenes" debe ser una lista de ${MIN_SCENES} a ${MAX_SCENES} escenas.`);
  const warnings: string[] = [];
  const scenes = list.map((x: Record<string, unknown> | null, i) => {
    if (!x || typeof x !== "object" || Array.isArray(x)) throw new Error(`La escena ${i + 1} no es un objeto.`);
    const where = (k: string) => `Escena ${i + 1}: "${k}"`;
    const scene = {
      narration: str(x.narration, where("narration")),
      action: str(x.action, where("action")),
      setting: str(x.setting, where("setting")),
      key_object: str(x.key_object, where("key_object")),
      shot: str(x.shot, where("shot")),
      character: str(x.character, where("character")),
    };
    if (!scene.narration) throw new Error(`La escena ${i + 1} viene sin narración.`);
    if (!scene.action) throw new Error(`La escena ${i + 1} viene sin "action": es lo que dibuja la imagen.`);
    if (IMAGE_FIELDS.some((k) => /[áéíóúñ¿¡]/i.test(scene[k]))) warnings.push(`escena ${i + 1}: campos de imagen que no parecen inglés`);
    return scene;
  });
  const title = str(data.title, '"title"');
  const protagonist = str(data.protagonist, '"protagonist"');
  if (!title) throw new Error('Falta "title".');
  if (!protagonist) throw new Error('Falta "protagonist": se usa en todas las imágenes.');
  const tags = data.hashtags;
  return {
    script: {
      title,
      protagonist,
      outline: str(data.outline, '"outline"'),
      caption: str(data.caption, '"caption"'),
      hashtags: Array.isArray(tags) ? tags.filter((t): t is string => typeof t === "string") : [],
      scenes,
    },
    warnings,
  };
}

/** Skip the local model: copy the prompt into any LLM and paste its answer. */
export function ScriptPaste({
  ideaOptions,
  hasPhoto,
  onPaste,
  onClose,
}: {
  ideaOptions: Partial<StoryOptions> | null;
  hasPhoto: boolean;
  onPaste: (script: StoryScript) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  useEffect(() => {
    ref.current?.showModal();
    if (ideaOptions)
      api
        .scriptPrompt(ideaOptions, hasPhoto)
        .then((r) => setPrompt(r.prompt))
        .catch((e: Error) => setPromptError(e.message));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const apply = (force: boolean) => {
    try {
      const parsed = parseScript(text);
      setError(null);
      setWarnings(parsed.warnings);
      if (parsed.warnings.length && !force) return;
      onPaste(parsed.script);
      ref.current?.close();
    } catch (e) {
      setError((e as Error).message);
      setWarnings([]);
    }
  };

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="script-paste-title"
      className="w-[min(760px,95vw)] max-h-[92vh] rounded-xl bg-white p-0 text-stone-900 backdrop:bg-black/70 dark:bg-stone-900 dark:text-stone-100"
    >
      <div className="space-y-3 p-5">
        <h2 id="script-paste-title" className="text-lg font-semibold">
          📋 Pegar guion
        </h2>
        <p className="text-sm text-stone-600 dark:text-stone-300">Escribe el guion con Claude u otro modelo y pégalo aquí. Ollama no se usa.</p>
        <div className="flex flex-wrap items-center gap-2">
          {prompt ? (
            <CopyButton text={prompt} label="📋 Copiar prompt" />
          ) : promptError ? (
            <p role="alert" className="text-sm text-red-700 dark:text-red-300">
              No se pudo preparar el prompt: {promptError}
            </p>
          ) : ideaOptions ? (
            <span className="text-sm text-stone-500">Preparando el prompt…</span>
          ) : (
            <span className="text-sm text-stone-500">Para copiar el prompt, cierra y escribe antes la idea, tu texto o elige una historia. Si ya tienes el guion, pégalo.</span>
          )}
        </div>
        {prompt && (
          <details className="text-xs text-stone-500">
            <summary className="cursor-pointer">Ver el prompt</summary>
            <textarea className="input mt-2 font-mono text-xs" rows={6} readOnly value={prompt} aria-label="Prompt para el modelo" />
          </details>
        )}
        <label className="block">
          <span className="label">Respuesta del modelo</span>
          <textarea
            className="input font-mono text-xs"
            rows={12}
            placeholder='{ "title": ..., "protagonist": ..., "scenes": [ ... ] }'
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setError(null);
              setWarnings([]);
            }}
          />
        </label>
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
            {error}
          </p>
        )}
        {warnings.length > 0 && (
          <p role="status" className="rounded-lg bg-amber-50 p-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
            Revisa: {warnings.join("; ")}. Las imágenes solo entienden inglés.
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={() => ref.current?.close()}>
            Cancelar
          </button>
          <button type="button" className="btn-primary" disabled={!text.trim()} onClick={() => apply(warnings.length > 0)}>
            {warnings.length > 0 ? "Usarlo igualmente" : "Usar este guion"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
