import { useEffect, useState } from "react";
import { remote } from "./remote";

const probe = () => {
  try {
    return new File([""], "v.mp4", { type: "video/mp4" });
  } catch {
    return null;
  }
};

/** Phone (touch screen) whose browser can hand a video file to TikTok, WhatsApp… */
export const canShareVideo = (() => {
  const file = probe();
  return typeof navigator !== "undefined" && !!file && !!navigator.canShare?.({ files: [file] })
    && matchMedia("(pointer: coarse)").matches;
})();

type Props = {
  url: string;
  title?: string;
  text?: string;
  className?: string;
  /** Ask the server to copy the video from the PC now, so a later tap only downloads it from the server. */
  warm?: boolean;
};

/**
 * Shares the video file itself (not a link) through the phone's share sheet.
 * Renders nothing on desktop. The download can outlast the tap's permission
 * to open the sheet (Safari): then a second tap shares the file already here.
 */
export default function ShareButton({ url, title, text, className, warm }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  // bytes fetched so far and the total (0 when the server sends no Content-Length)
  const [progress, setProgress] = useState({ got: 0, total: 0 });
  // A one-byte ranged request: the server starts its copy and the phone downloads almost nothing.
  useEffect(() => {
    if (!warm || !remote || !canShareVideo || !url) return;
    const ctrl = new AbortController();
    fetch(url, { headers: { Range: "bytes=0-0" }, signal: ctrl.signal }).catch(() => {});
    return () => ctrl.abort();
  }, [warm, url]);
  if (!canShareVideo || !url) return null;

  const download = async (): Promise<Blob> => {
    const res = await fetch(url); // remote mode: remote.ts sends it to the server with the session
    if (!res.ok) throw new Error(String(res.status));
    const total = Number(res.headers.get("content-length")) || 0;
    const reader = res.body?.getReader();
    if (!reader) return res.blob();
    const chunks: BlobPart[] = [];
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      got += value.byteLength;
      setProgress({ got, total });
    }
    return new Blob(chunks, { type: "video/mp4" });
  };

  const share = async () => {
    try {
      let f = file;
      if (!f) {
        setState("loading");
        setProgress({ got: 0, total: 0 });
        const name = `${(title || "video").replace(/[^\w\- ]+/g, "").trim().slice(0, 60) || "video"}.mp4`;
        f = new File([await download()], name, { type: "video/mp4" });
        setFile(f);
      }
      await navigator.share({ files: [f], title, text });
      setState("idle");
    } catch (e) {
      const err = e as Error;
      if (err.name === "AbortError") setState("idle"); // closed the sheet
      else if (err.name === "NotAllowedError") setState("ready"); // tap again
      else setState("error");
    }
  };

  const loading = progress.total
    ? `⏳ Descargando ${Math.round((100 * progress.got) / progress.total)} %`
    : `⏳ Descargando ${(progress.got / 1e6).toFixed(1)} MB`;
  const label = { idle: "📤 Compartir", loading, ready: "📤 Tocar para compartir", error: "⚠ Reintentar" }[state];
  return (
    <button type="button" className={className} onClick={share} disabled={state === "loading"}>
      {label}
    </button>
  );
}
