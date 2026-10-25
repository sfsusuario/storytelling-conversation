import { useEffect, useMemo, useState } from "react";
import { lastOf, mmss, postJSON, useElapsed, useJob, type Defaults, type Turn } from "./api";
import { CopyButton, ErrorBox, IdeasModal, LogPanel, Spinner, Stepper } from "./ui";

const STEPS = ["Tema", "Guion", "Voz", "Video", "Listo"];
type Step = "topic" | "script" | "render" | "done";

type ScriptResult = { draft: string; title: string; turns: Turn[]; social: string };
type VideoResult = { video_url: string | null; title: string; social: string; folder: string };

export default function VideoFlow({ defaults }: { defaults: Defaults }) {
  const [step, setStep] = useState<Step>("topic");
  const [topic, setTopic] = useState("");
  const [demo, setDemo] = useState(false);
  const [engine, setEngine] = useState(defaults.tts_engine);
  const [feedback, setFeedback] = useState("");
  const [showIdeas, setShowIdeas] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // ⚙ Ajustes: everything else keeps the backend defaults
  const [language, setLanguage] = useState(defaults.language);
  const [maxTurns, setMaxTurns] = useState(defaults.max_turns);
  const [provider, setProvider] = useState(defaults.text_provider);
  const [model, setModel] = useState(defaults.text_model);
  const [subtitles, setSubtitles] = useState(defaults.subtitles);
  const [watermark, setWatermark] = useState(defaults.watermark);
  const [bgVolume, setBgVolume] = useState(defaults.bg_volume);

  const [scriptJob, setScriptJob] = useState<string | null>(null);
  const [renderJob, setRenderJob] = useState<string | null>(null);
  const [eta, setEta] = useState<number | null>(null);
  const [auto, setAuto] = useState(false); // approve the script as soon as it is written
  const script = useJob(scriptJob);
  const render = useJob(renderJob);

  const scriptResult = lastOf(script.events, "result") as unknown as ScriptResult | undefined;
  const scriptError = lastOf(script.events, "error")?.text ?? null;
  const videoResult = lastOf(render.events, "result") as unknown as VideoResult | undefined;
  const renderError = lastOf(render.events, "error")?.text ?? null;
  const rendering = step === "render" && !render.done;
  const elapsed = useElapsed(rendering);

  const renderOptions = () => ({
    tts_engine: engine,
    subtitles,
    watermark,
    bg_volume: bgVolume,
  });

  const writeScript = async (withFeedback = "") => {
    setError(null);
    setScriptJob(null);
    try {
      const { job } = await postJSON<{ job: string }>("api/video/script", {
        topic,
        demo,
        feedback: withFeedback,
        options: {
          language,
          max_turns: maxTurns,
          text_provider: provider,
          text_model: model,
          ...renderOptions(),
        },
      });
      setScriptJob(job);
      setStep("script");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const approve = async () => {
    if (!scriptResult) return;
    setError(null);
    try {
      const res = await postJSON<{ job: string; eta: number | null }>(
        `api/video/${scriptResult.draft}/approve`,
        { options: renderOptions() },
      );
      setEta(res.eta);
      setRenderJob(res.job);
      setStep("render");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  // per-turn progress from the render job's events
  const progress = useMemo(() => {
    const audio = new Set<number>();
    const clips = new Set<number>();
    let stage = "voice";
    for (const e of render.events) {
      if (e.kind === "audio" && e.turn) audio.add(e.turn);
      if (e.kind === "clip" && e.turn) clips.add(e.turn);
      if (e.kind === "stage" && e.stage) stage = e.stage;
    }
    return { audio, clips, stage };
  }, [render.events]);

  useEffect(() => {
    if (videoResult && step === "render") setStep("done");
  }, [videoResult, step]);

  // Modo automático: chain script -> voice -> video without stopping
  useEffect(() => {
    if (!auto || step !== "script") return;
    if (scriptError) setAuto(false);
    else if (scriptResult) {
      setAuto(false);
      approve();
    }
  }, [auto, step, scriptResult, scriptError]); // eslint-disable-line react-hooks/exhaustive-deps

  const current =
    step === "topic" ? 0 : step === "script" ? 1 : step === "done" ? 4 : progress.stage === "voice" ? 2 : 3;
  const turns = scriptResult?.turns ?? [];
  const pct = turns.length
    ? Math.round(((progress.audio.size + progress.clips.size) / (2 * turns.length)) * 100)
    : 0;

  const restart = () => {
    setStep("topic");
    setScriptJob(null);
    setRenderJob(null);
    setFeedback("");
    setError(null);
    setAuto(false);
  };

  return (
    <section>
      <Stepper steps={STEPS} current={current} />
      <ErrorBox message={error} />

      {step === "topic" && (
        <div className="card">
          <label className="big-label" htmlFor="topic">¿De qué hablan Rick y Morty?</label>
          <textarea
            id="topic"
            className="topic"
            rows={3}
            placeholder='p. ej. "los pulpos tienen tres corazones" o una URL de noticia'
            value={topic}
            disabled={demo}
            onChange={(e) => setTopic(e.target.value)}
          />
          <div className="row">
            <button className="ghost" onClick={() => setShowIdeas(true)}>💡 Ideas</button>
            <label className="check">
              <input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} />
              Guion de ejemplo (sin LLM)
            </label>
            <div className="spacer" />
            <div className="segmented" aria-label="Motor de voz">
              {defaults.engines.map((e) => (
                <button key={e} className={engine === e ? "on" : ""} onClick={() => setEngine(e)}>
                  {e === "edge" ? "⚡ edge (rápido)" : e === "chatterbox" ? "🎭 chatterbox (voz clonada)" : e}
                </button>
              ))}
            </div>
          </div>

          <details className="settings">
            <summary>⚙ Ajustes</summary>
            <div className="grid">
              <label>
                Idioma
                <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                  {defaults.languages.map((l) => (
                    <option key={l.code} value={l.code}>{l.name}</option>
                  ))}
                </select>
              </label>
              <label>
                Máx. turnos: {maxTurns}
                <input type="range" min={4} max={16} value={maxTurns}
                  onChange={(e) => setMaxTurns(Number(e.target.value))} />
              </label>
              <label>
                Guionista
                <select value={provider} onChange={(e) => {
                  setProvider(e.target.value);
                  if (e.target.value === "ollama") setModel(defaults.ollama_default);
                  else setModel(defaults.text_model);
                }}>
                  <option value="auto">auto (Claude → Gemini → Ollama)</option>
                  <option value="claude">Claude</option>
                  <option value="gemini">Gemini</option>
                  <option value="ollama">Ollama (local)</option>
                </select>
              </label>
              {provider === "ollama" && (
                <label>
                  Modelo
                  <select value={model} onChange={(e) => setModel(e.target.value)}>
                    {[defaults.ollama_default, ...defaults.ollama_models.filter((m) => m !== defaults.ollama_default)]
                      .map((m) => <option key={m}>{m}</option>)}
                  </select>
                </label>
              )}
              <label>
                Marca de agua
                <input value={watermark} onChange={(e) => setWatermark(e.target.value)} />
              </label>
              <label>
                Ambiente del fondo: {bgVolume.toFixed(2)}
                <input type="range" min={0} max={0.6} step={0.01} value={bgVolume}
                  onChange={(e) => setBgVolume(Number(e.target.value))} />
              </label>
              <label className="check">
                <input type="checkbox" checked={subtitles} onChange={(e) => setSubtitles(e.target.checked)} />
                Subtítulos
              </label>
            </div>
          </details>

          <div className="actions">
            <button className="ghost big" disabled={!demo && !topic.trim()} onClick={() => writeScript()}>
              📝 Escribir guion y revisar
            </button>
            <button
              className="primary big"
              disabled={!demo && !topic.trim()}
              title="Guion, voces y video de una vez, sin pararse a revisar"
              onClick={() => {
                setAuto(true);
                writeScript();
              }}
            >
              ⚡ Modo automático
            </button>
          </div>
        </div>
      )}

      {step === "script" && (
        <div className="card">
          {!scriptResult && !scriptError && (
            <Spinner label={auto ? "⚡ Modo automático: escribiendo el guion (luego voces y video)…" : "Escribiendo el guion…"} />
          )}
          <ErrorBox message={scriptError} />
          {scriptResult && (
            <>
              <h2 className="title">{scriptResult.title}</h2>
              <div className="chat">
                {scriptResult.turns.map((t, i) => (
                  <div key={i} className={`bubble ${t.speaker}`}>
                    <span className="who">{t.speaker} · {t.emotion.replace("_", " / ")}</span>
                    {t.line}
                  </div>
                ))}
              </div>
              <textarea rows={2} placeholder='Para regenerar: "más corto", "cambia el final"…'
                value={feedback} onChange={(e) => setFeedback(e.target.value)} disabled={demo} />
            </>
          )}
          <LogPanel events={script.events} />
          <div className="actions">
            <button className="ghost" onClick={restart}>← Cambiar tema</button>
            <button className="ghost" disabled={!script.done || demo} onClick={() => writeScript(feedback)}>
              🔄 Regenerar
            </button>
            <button className="primary big" disabled={!scriptResult} onClick={approve}>
              ✅ Aprobar y crear video
            </button>
          </div>
        </div>
      )}

      {step === "render" && (
        <div className="card">
          <h2 className="title">
            {progress.stage === "voice" ? "🎙 Generando voces" : "🎬 Montando el video"}
          </h2>
          <div className="bar"><div style={{ width: `${pct}%` }} /></div>
          <p className="muted">
            {mmss(elapsed)} transcurridos
            {eta ? ` · ~${mmss(Math.max(0, eta - elapsed))} restantes (estimado ${mmss(eta)})` : ""}
          </p>
          <div className="chips">
            {turns.map((t, i) => {
              const n = i + 1;
              const state = progress.clips.has(n) ? "clip" : progress.audio.has(n) ? "audio" : "";
              return (
                <div key={n} className={`chip ${t.speaker} ${state}`} title={t.line}>
                  <b>{n}</b>
                  <span>{state === "clip" ? "🎬" : state === "audio" ? "🎙" : "…"}</span>
                </div>
              );
            })}
          </div>
          <p className="legend">🎙 voz lista · 🎬 clip listo</p>
          <ErrorBox message={renderError} />
          <LogPanel events={render.events} />
          {renderError && (
            <div className="actions">
              <button className="ghost" onClick={() => setStep("script")}>← Volver al guion</button>
            </div>
          )}
        </div>
      )}

      {step === "done" && videoResult && (
        <div className="card done">
          <div className="result">
            {videoResult.video_url && (
              <video src={videoResult.video_url} controls autoPlay className="player" />
            )}
            <div className="meta">
              <h2 className="title">{videoResult.title}</h2>
              <p className="muted">Listo en {mmss(elapsed)}</p>
              <label>Descripción para redes</label>
              <pre className="social">{videoResult.social}</pre>
              <div className="row">
                <CopyButton text={videoResult.social} label="📋 Copiar descripción" />
                {videoResult.video_url && (
                  <a className="ghost button" href={videoResult.video_url} download>⬇ Descargar</a>
                )}
              </div>
              <p className="muted small">Carpeta: {videoResult.folder}</p>
              <button className="primary" onClick={restart}>➕ Otro video</button>
            </div>
          </div>
        </div>
      )}

      {showIdeas && (
        <IdeasModal
          areas={defaults.areas}
          onClose={() => setShowIdeas(false)}
          onPick={(t) => {
            setTopic(t);
            setDemo(false);
            setShowIdeas(false);
          }}
        />
      )}
    </section>
  );
}
