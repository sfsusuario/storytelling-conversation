import { useEffect, useState, type ComponentType } from "react";
import History, { type Reuse } from "./History";
import ConversacionApp from "./modalities/conversacion/App";
import EscaleraApp from "./modalities/escalera/App";

export type Modality = { id: string; name: string; icon: string; description: string };

/** UI of each modality, by the id the backend registers it with
 * (src/studio/modalities.py). A new modality = one entry here. */
const SECTIONS: Record<string, { component: ComponentType; className: string }> = {
  conversacion: { component: ConversacionApp, className: "charla" },
  escalera: { component: EscaleraApp, className: "escalera" },
};

const HISTORY = "historial";

export default function App() {
  const [modalities, setModalities] = useState<Modality[]>([]);
  // active tab lives in the URL hash (#escalera, #historial): bookmarkable, survives reload
  const [tab, setTabState] = useState(() => decodeURIComponent(location.hash.slice(1)));
  const [opened, setOpened] = useState<Set<string>>(new Set()); // sections stay mounted once opened
  const [remount, setRemount] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);

  const setTab = (t: string) => {
    setTabState(t);
    history.replaceState(null, "", `${location.search}#${t}`);
  };

  useEffect(() => {
    fetch("/api/modalities")
      .then(async (r) => {
        const body = await r.json().catch(() => null);
        // e.g. 503 from the public server when the PC (worker) is off
        if (!r.ok || !Array.isArray(body)) throw new Error(body?.detail ?? `Error ${r.status}`);
        return body as Modality[];
      })
      .then((list) => {
        setModalities(list);
        setTabState((t) => (t === HISTORY || list.some((m) => m.id === t) ? t : list[0]?.id ?? HISTORY));
      })
      .catch((e: Error) => {
        setError(e.message.startsWith("Failed") ? "No se pudo contactar con el servidor del estudio." : e.message);
        setTabState(HISTORY); // the server's copy of the history still works with the PC off
      });
  }, []);

  useEffect(() => {
    if (tab && tab !== HISTORY) setOpened((s) => (s.has(tab) ? s : new Set(s).add(tab)));
  }, [tab]);

  // "Otra versión": open the modality with the same input, or let it re-run
  // the video itself and remount its section (it resumes the active run).
  const reuse = async (mid: string, r: Reuse) => {
    setError(null);
    if (r.kind === "regenerate") {
      const res = await fetch(r.url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(r.body),
      });
      if (!res.ok) {
        setError(res.status === 409 ? "Ya se está generando un video en esa modalidad." : `No se pudo regenerar (${res.status}).`);
        return;
      }
      history.replaceState(null, "", `#${mid}`);
    } else {
      // the modality reads ?topic= when it mounts
      history.replaceState(null, "", `?${new URLSearchParams({ topic: r.input })}#${mid}`);
    }
    setRemount((m) => ({ ...m, [mid]: (m[mid] ?? 0) + 1 }));
    setTabState(mid);
  };

  return (
    <div className="shell">
      <header className="shell-bar">
        <span className="shell-brand">🎬 Storytelling Studio</span>
        <nav>
          {modalities.map((m) => (
            <button key={m.id} className={tab === m.id ? "on" : ""} onClick={() => setTab(m.id)} title={m.description}>
              {m.icon} {m.name}
            </button>
          ))}
          <button className={tab === HISTORY ? "on" : ""} onClick={() => setTab(HISTORY)}>
            📼 Historial
          </button>
        </nav>
      </header>
      {error && <div className="shell-error">⚠ {error}</div>}
      <main className="shell-main">
        {modalities.map((m) => {
          const section = SECTIONS[m.id];
          if (!section || !opened.has(m.id)) return null;
          const Section = section.component;
          return (
            <section key={`${m.id}-${remount[m.id] ?? 0}`} className={`shell-pane ${section.className}`} hidden={tab !== m.id}>
              <Section />
            </section>
          );
        })}
        <section className="shell-pane" hidden={tab !== HISTORY}>
          {tab === HISTORY && <History modalities={modalities} onOpen={setTab} onReuse={reuse} />}
        </section>
      </main>
    </div>
  );
}
