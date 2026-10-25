import { useState } from "react";

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

type Props = { url: string; title?: string; text?: string; className?: string };

/**
 * Shares the video file itself (not a link) through the phone's share sheet.
 * Renders nothing on desktop. The download can outlast the tap's permission
 * to open the sheet (Safari): then a second tap shares the file already here.
 */
export default function ShareButton({ url, title, text, className }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  if (!canShareVideo || !url) return null;

  const share = async () => {
    try {
      let f = file;
      if (!f) {
        setState("loading");
        const res = await fetch(url); // remote mode: remote.ts sends it to the server with the session
        if (!res.ok) throw new Error(String(res.status));
        const name = `${(title || "video").replace(/[^\w\- ]+/g, "").trim().slice(0, 60) || "video"}.mp4`;
        f = new File([await res.blob()], name, { type: "video/mp4" });
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

  const label = { idle: "📤 Compartir", loading: "⏳ Preparando…", ready: "📤 Tocar para compartir", error: "⚠ Reintentar" }[state];
  return (
    <button type="button" className={className} onClick={share} disabled={state === "loading"}>
      {label}
    </button>
  );
}
