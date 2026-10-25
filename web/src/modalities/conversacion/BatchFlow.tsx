import { useMemo, useState } from "react";
import { getJSON, lastOf, mmss, postJSON, useElapsed, useJob, type Defaults } from "./api";
import { CopyButton, ErrorBox, LogPanel, Spinner } from "./ui";

type Item = { index: number; topic: string; ok: boolean; title: string; error: string; video_url: string | null };
type BatchResult = { folder: string; publish_text: string; items: Item[] };
type Card = { index: number; topic: string; status: "running" | "ok" | "fail"; stage: string; error?: string };

const STAGE_LABEL: Record<string, string> = {
  script: "📝 guion",
  voice: "🎙 voces",
  timeline: "🎬 montaje",
  render: "🎬 montaje",
  done: "✓",
};

export default function BatchFlow({ defaults }: { defaults: Defaults }) {
  const [count, setCount] = useState(3);
  const [source, setSource] = useState("bank");
  const [area, setArea] = useState(defaults.areas[0] ?? "");
  const [model, setModel] = useState(defaults.ollama_default);
  const [engine, setEngine] = useState(defaults.tts_engine);
  const [topics, setTopics] = useState("");
  const [proposing, setProposing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const job = useJob(jobId);
  const running = !!jobId && !job.done;
  const elapsed = useElapsed(running);
  const theme = area === defaults.areas[0] ? defaults.batch_theme : area;

  const propose = async () => {
    setProposing(true);
    setError(null);
    try {
      const q = new URLSearchParams({ count: String(count), source, theme, model });
      const list = await getJSON<string[]>(`/m/conversacion/api/topics?${q}`);
      setTopics(list.join("\n"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setProposing(false);
    }
  };

  const start = async () => {
    setError(null);
    setStopping(false);
    try {
      const { job } = await postJSON<{ job: string }>("/m/conversacion/api/batch", {
        count,
        source,
        theme,
        model,
        tts_engine: engine,
        language: defaults.language,
        topics: topics.split("\n").map((t) => t.trim()).filter(Boolean),
      });
      setJobId(job);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const stop = async () => {
    if (!jobId) return;
    setStopping(true);
    await postJSON(`/m/conversacion/api/batch/${jobId}/stop`).catch(() => undefined);
  };

  // one card per video, from the batch's events
  const cards = useMemo(() => {
    const list: Card[] = [];
    for (const e of job.events) {
      const cur = list[list.length - 1];
      if (e.kind === "video") list.push({ index: e.index ?? 0, topic: e.topic ?? "", status: "running", stage: "script" });
      else if (e.kind === "stage" && cur && e.stage) cur.stage = e.stage;
      else if (e.kind === "video_ok" && cur) cur.status = "ok";
      else if (e.kind === "video_fail" && cur) Object.assign(cur, { status: "fail", error: e.error });
    }
    return list;
  }, [job.events]);
  const total = (job.events.find((e) => e.kind === "video")?.total as number | undefined) ?? 0;
  const result = lastOf(job.events, "result") as unknown as BatchResult | undefined;
  const fatal = lastOf(job.events, "error")?.text ?? null;
  const urls = new Map(result?.items.map((i) => [i.index, i.video_url]) ?? []);

  return (
    <section>
      <ErrorBox message={error} />
      {!jobId && (
        <div className="card">
          <p className="muted">
            Genera varios videos seguidos: elige temas, escribe cada guion con Ollama, pone las voces y
            renderiza. Al final tendrás los videos numerados y <b>publicar.txt</b> con títulos y descripciones.
          </p>
          <div className="grid">
            <label>
              Videos: {count}
              <input type="range" min={1} max={10} value={count} onChange={(e) => setCount(Number(e.target.value))} />
            </label>
            <label>
              Temas de
              <select value={source} onChange={(e) => setSource(e.target.value)}>
                <option value="bank">Banco de datos verificados</option>
                <option value="ollama">Ollama (revísalos)</option>
              </select>
            </label>
            <label>
              Área
              <select value={area} onChange={(e) => setArea(e.target.value)}>
                {defaults.areas.map((a) => <option key={a}>{a}</option>)}
              </select>
            </label>
            <label>
              Motor de voz
              <select value={engine} onChange={(e) => setEngine(e.target.value)}>
                {defaults.engines.map((e) => <option key={e}>{e}</option>)}
              </select>
            </label>
            <label>
              Guionista (Ollama)
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                {[defaults.ollama_default, ...defaults.ollama_models.filter((m) => m !== defaults.ollama_default)]
                  .map((m) => <option key={m}>{m}</option>)}
              </select>
            </label>
          </div>
          <label className="big-label">Temas <span className="muted">(uno por línea; vacío = se eligen solos)</span></label>
          <textarea rows={5} value={topics} onChange={(e) => setTopics(e.target.value)} />
          <div className="actions">
            <button className="ghost" onClick={propose} disabled={proposing}>
              {proposing ? "Buscando…" : "🎲 Proponer temas"}
            </button>
            <button className="primary big" onClick={start}>🎬 Generar {count} videos</button>
          </div>
        </div>
      )}

      {jobId && (
        <div className="card">
          <div className="row">
            <h2 className="title">
              {running ? `Lote en marcha · ${cards.filter((c) => c.status !== "running").length}/${total || "?"}` : "Lote terminado"}
            </h2>
            <div className="spacer" />
            <span className="muted">{mmss(elapsed)}</span>
            {running && (
              <button className="ghost" onClick={stop} disabled={stopping}>
                {stopping ? "Se detendrá tras este video" : "⏹ Detener"}
              </button>
            )}
          </div>
          {running && cards.length === 0 && <Spinner label="Eligiendo temas…" />}
          <ul className="cards">
            {cards.map((c) => (
              <li key={c.index} className={`vcard ${c.status}`}>
                <span className="num">{String(c.index).padStart(2, "0")}</span>
                <div>
                  <div>{c.topic}</div>
                  <div className="muted small">
                    {c.status === "running" && <><span className="spinner small" /> {STAGE_LABEL[c.stage] ?? c.stage}</>}
                    {c.status === "ok" && (urls.get(c.index)
                      ? <a href={urls.get(c.index) ?? "#"} target="_blank" rel="noreferrer">✓ ver video</a>
                      : "✓ listo")}
                    {c.status === "fail" && `✗ ${c.error}`}
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <ErrorBox message={fatal} />
          <LogPanel events={job.events} />
          {result && (
            <>
              <label className="big-label">📣 publicar.txt</label>
              <pre className="social">{result.publish_text || "(ningún video terminado)"}</pre>
              <div className="row">
                {result.publish_text && <CopyButton text={result.publish_text} label="📋 Copiar todo" />}
                <span className="muted small">Carpeta: {result.folder}</span>
              </div>
            </>
          )}
          {job.done && (
            <div className="actions">
              <button className="primary" onClick={() => { setJobId(null); setTopics(""); }}>➕ Nuevo lote</button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
