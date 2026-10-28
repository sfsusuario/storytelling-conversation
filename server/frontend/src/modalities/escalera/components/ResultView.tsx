import { useState } from "react";
import type { RunState } from "../runState";
import { ESCALERA_LABELS, RerollButtons, SceneViewer, type SceneLabels } from "./ProgressView";
import { CopyButton, formatSeconds } from "./ui";
import { apiUrl, downloadUrl } from "../../../remote";
import ShareButton from "../../../ShareButton";

const REGENERATE = [
  { stage: "text", label: "Textos" },
  { stage: "images", label: "Imágenes" },
  { stage: "tts", label: "Voz" },
  { stage: "motion", label: "Movimiento" },
  { stage: "render", label: "Render" },
];

export function ResultView({
  state,
  onRegenerate,
  onReroll,
  onNew,
  labels = ESCALERA_LABELS,
}: {
  state: RunState;
  onRegenerate: (stage: string) => void;
  onReroll: (sceneId: string, kind: "image" | "motion", prompt?: string) => void;
  onNew: () => void;
  labels?: SceneLabels;
}) {
  const result = state.result!;
  const [open, setOpen] = useState<string | null>(null);
  const opened = state.scenes.find((sc) => sc.scene_id === open);
  return (
    <section className="grid gap-6 lg:grid-cols-[minmax(0,380px)_1fr]" aria-labelledby="result-title">
      <div className="mx-auto w-full max-w-[380px]">
        {result.video && (
          <video src={apiUrl(result.video)} controls autoPlay className="aspect-[9/16] w-full rounded-2xl bg-black shadow-lg" />
        )}
      </div>
      <div className="space-y-5">
        <div className="card space-y-2">
          <h2 id="result-title" className="text-xl font-semibold">
            ✅ ¡Vídeo listo!
          </h2>
          <p className="text-sm text-stone-500">
            {formatSeconds(result.duration)} de vídeo · generado en {formatSeconds(state.now)}
            {state.styleSet && ` · ${labels.setLabel(state.styleSet)}`}
          </p>
          <div className="flex flex-wrap gap-2 pt-2">
            {result.video && <ShareButton className="btn-primary" url={result.video} text={result.social} />}
            {result.video && (
              <a className="btn-primary" href={downloadUrl(result.video)} download={labels.download}>
                ⬇ Descargar MP4
              </a>
            )}
            <button type="button" className="btn-ghost" onClick={onNew}>
              ＋ Nuevo vídeo
            </button>
          </div>
        </div>

        {result.social && (
          <div className="card space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">📣 Texto para redes</h3>
              <CopyButton text={result.social} />
            </div>
            <p className="whitespace-pre-wrap text-sm text-stone-700 dark:text-stone-300">{result.social}</p>
          </div>
        )}

        <div className="card space-y-3">
          <h3 className="font-semibold">🔁 Regenerar desde una etapa</h3>
          <p className="hint mt-0">Reutiliza la caché de las etapas anteriores y rehace la elegida y las siguientes.</p>
          <div className="flex flex-wrap gap-2">
            {REGENERATE.map((r) => (
              <button key={r.stage} type="button" className="btn-ghost" onClick={() => onRegenerate(r.stage)}>
                {r.label}
              </button>
            ))}
          </div>
        </div>

        <p className="hint mb-0">Pulsa una escena para verla o pedir otra imagen o movimiento.</p>
        {opened && <SceneViewer scene={opened} original={labels.original(state, opened)} onClose={() => setOpen(null)} onReroll={onReroll} labels={labels} />}
        <div className={labels.gridResult}>
          {state.scenes.map((sc) => (
            <figure key={sc.scene_id} className="overflow-hidden rounded-lg border border-stone-200 dark:border-stone-800">
              {sc.image && (
                <button type="button" onClick={() => setOpen(sc.scene_id)} className="block w-full" aria-label={`Ver o regenerar ${labels.title(sc)}`}>
                  <img src={apiUrl(sc.image)} alt="" className="aspect-[9/16] w-full object-cover hover:brightness-110" loading="lazy" />
                </button>
              )}
              <figcaption className="space-y-0.5 p-1 text-center text-xs">
                <div className="truncate">{labels.title(sc)}</div>
                <div className="flex justify-center">
                  <RerollButtons scene={sc} onReroll={onReroll} labels={labels} />
                </div>
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}
