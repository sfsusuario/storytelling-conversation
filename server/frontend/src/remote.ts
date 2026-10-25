/**
 * Remote mode: the web is on Netlify (storytelling.fierro.dev) and the API on
 * the server (VITE_API_BASE), which relays every call to the worker on the
 * home PC. Locally VITE_API_BASE is empty and every path stays same-origin,
 * so the modalities keep calling "/api/..." and "/m/..." unchanged.
 */
export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
export const remote = API_BASE !== "";

const RELAYED = /^\/(api|m|media|files|auth)\//;

/** URL for <img>/<video>/<a>: the server's in remote mode, as-is locally. */
export const apiUrl = (u: string | null | undefined): string =>
  u && remote && RELAYED.test(u) ? API_BASE + u : u ?? "";

/** Cross-origin links ignore `download`: the server sends it as an attachment. */
export const downloadUrl = (u: string): string =>
  remote ? `${apiUrl(u)}${u.includes("?") ? "&" : "?"}dl=1` : u;

export const LOGIN_EVENT = "studio:login";

if (remote) {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    if (typeof input !== "string" || !RELAYED.test(input)) return nativeFetch(input, init);
    const res = await nativeFetch(API_BASE + input, { ...init, credentials: "include" });
    if (res.status === 401 && !input.startsWith("/auth/")) window.dispatchEvent(new Event(LOGIN_EVENT));
    return res;
  };
  const NativeEventSource = window.EventSource;
  window.EventSource = class extends NativeEventSource {
    constructor(url: string | URL, init?: EventSourceInit) {
      super(typeof url === "string" ? apiUrl(url) : url, { ...init, withCredentials: true });
    }
  };
}
