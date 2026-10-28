import { useId, useRef, useState, type ReactNode } from "react";

export function Field({ label, hint, children }: { label: string; hint?: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="label">
        {label}
      </label>
      {children(id)}
      {hint && <p className="hint">{hint}</p>}
    </div>
  );
}

export function Select({
  id,
  value,
  onChange,
  options,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string; disabled?: boolean }[];
}) {
  return (
    <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
}) {
  const id = useId();
  return (
    <div className="flex items-start gap-3">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 ${
          checked ? "bg-orange-600" : "bg-stone-300 dark:bg-stone-700"
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${checked ? "left-[1.375rem]" : "left-0.5"}`}
        />
      </button>
      <label htmlFor={id} className="cursor-pointer">
        <span className="text-sm font-medium">{label}</span>
        {hint && <span className="hint block">{hint}</span>}
      </label>
    </div>
  );
}

/** Play/stop button for a remote audio sample (voice or music preview). */
export function PlayButton({ src, label }: { src: string; label: string }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "playing" | "error">("idle");
  const toggle = () => {
    if (state === "playing" || state === "loading") {
      audio.current?.pause();
      setState("idle");
      return;
    }
    const a = new Audio(src);
    audio.current = a;
    setState("loading");
    a.onplaying = () => setState("playing");
    a.onended = () => setState("idle");
    a.onerror = () => setState("error");
    a.play().catch(() => setState("error"));
  };
  return (
    <button type="button" className="btn-ghost shrink-0" onClick={toggle} aria-label={label} title={label}>
      {state === "loading" ? "⏳" : state === "playing" ? "⏹" : state === "error" ? "⚠️" : "🔊"}
      <span className="hidden sm:inline">{state === "error" ? "Error" : "Escuchar"}</span>
    </button>
  );
}

export function Badge({ ok, children }: { ok: boolean | null; children: ReactNode }) {
  const tone =
    ok === null
      ? "bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-300"
      : ok
        ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300"
        : "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300";
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>{children}</span>;
}

export function formatSeconds(s: number): string {
  if (!Number.isFinite(s)) return "—";
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return m > 0 ? `${m}m ${r.toString().padStart(2, "0")}s` : `${r}s`;
}

/** Copies text to the clipboard; the same label in every modality unless given. */
export function CopyButton({ text, label = "📋 Copiar descripción", className = "btn-ghost" }: { text: string; label?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className={className}
      onClick={() =>
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        })
      }
    >
      {copied ? "✓ Copiado" : label}
    </button>
  );
}
