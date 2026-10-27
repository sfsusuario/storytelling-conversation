import { CopyButton } from "../escalera/components/ui";
import type { RunState } from "../escalera/runState";

/** A preview run ended: the script is written, nothing rendered yet. */
export function StoryPreview({ state, onContinue, onAnother, onBack }: { state: RunState; onContinue: () => void; onAnother: () => void; onBack: () => void }) {
  const story = state.story;
  const social = state.result?.social ?? "";
  return (
    <section className="mx-auto max-w-3xl space-y-4" aria-labelledby="preview-title">
      <div className="card space-y-3">
        <h2 id="preview-title" className="text-xl font-semibold">
          📝 {story?.title ?? "Guion"}
        </h2>
        {story?.outline && <p className="text-sm text-stone-500">{story.outline}</p>}
        {story?.source && (
          <p className="text-xs text-stone-500">
            Basado en{" "}
            <a className="underline" href={story.source.url} target="_blank" rel="noreferrer">
              u/{story.source.author} en r/{story.source.subreddit}
            </a>
          </p>
        )}
        <ol className="space-y-2">
          {state.scenes.map((sc) => (
            <li key={sc.scene_id} className="flex gap-3 rounded-lg bg-stone-50 p-3 text-sm dark:bg-stone-800">
              <span className="w-5 shrink-0 font-bold text-orange-600">{sc.level}</span>
              <span>{sc.text ?? "…"}</span>
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap gap-2 pt-2">
          <button type="button" className="btn-primary" onClick={onContinue}>
            🎬 Continuar: imágenes, voz y video
          </button>
          <button type="button" className="btn-ghost" onClick={onAnother}>
            🎲 Otro guion
          </button>
          <button type="button" className="btn-ghost" onClick={onBack}>
            Volver
          </button>
        </div>
        <p className="hint mb-0">Al continuar se usa este guion tal cual; «Otro guion» lo escribe de nuevo.</p>
      </div>
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
