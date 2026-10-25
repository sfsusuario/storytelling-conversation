import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { LOGIN_EVENT, remote } from "./remote";

type Status = { authenticated: boolean; worker_online?: boolean };

/** Remote mode only: password screen, then the studio with a badge telling
 * whether the home PC is connected (off = history from the server's copy). */
export default function RemoteGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    fetch("/auth/status")
      .then((r) => r.json() as Promise<Status>)
      .then(setStatus)
      .catch(() => setError("No se pudo contactar con el servidor."));

  useEffect(() => {
    if (!remote) return;
    refresh();
    const timer = setInterval(refresh, 20000);
    const onLogin = () => setStatus({ authenticated: false });
    window.addEventListener(LOGIN_EVENT, onLogin);
    return () => {
      clearInterval(timer);
      window.removeEventListener(LOGIN_EVENT, onLogin);
    };
  }, []);

  if (!remote) return <>{children}</>;

  const login = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const res = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!res.ok) {
      setError(res.status === 401 ? "Contraseña incorrecta." : `Error ${res.status}.`);
      return;
    }
    setPassword("");
    refresh();
  };

  if (!status) return <div className="shell gate">{error ?? "Conectando…"}</div>;
  if (!status.authenticated) {
    return (
      <div className="shell gate">
        <form onSubmit={login}>
          <h1>🎬 Storytelling Studio</h1>
          <input type="password" autoComplete="current-password" placeholder="Contraseña" autoFocus
            value={password} onChange={(e) => setPassword(e.target.value)} />
          <button type="submit" disabled={!password}>Entrar</button>
          {error && <p className="gate-error">{error}</p>}
        </form>
      </div>
    );
  }
  return (
    <>
      {children}
      <div className={`gate-pc ${status.worker_online ? "on" : "off"}`}
        title={status.worker_online ? "El worker del PC está conectado" : "Puedes ver, descargar y compartir el historial; crear videos necesita el PC"}>
        {status.worker_online ? "🟢 PC conectado" : "🔴 PC apagado · solo historial"}
      </div>
    </>
  );
}
