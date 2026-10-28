import { describe, expect, it } from "vitest";
import { estimateRemaining, initialRun, runReducer, stageDurations, stageProgress } from "./runState";
import type { RunEvent } from "./types";

const events: RunEvent[] = [
  { ts: 0, type: "started", run_id: "r1", upload_id: "u1" },
  {
    ts: 0.1,
    type: "scenes",
    style_set: "military",
    output_dir: "output/x",
    scenes: [
      { scene_id: "scene_01", level: 1, persona: "Recruit" },
      { scene_id: "scene_02", level: 2, persona: "Sergeant" },
    ],
  },
  { ts: 0.2, type: "stage", index: 1, total: 5, name: "text", detail: "ollama: qwen3:8b" },
  { ts: 5, type: "scene", scene_id: "scene_02", kind: "text", text: "¡Hambre!" },
  { ts: 5.1, type: "stage", index: 2, total: 5, name: "images", detail: "flux-kontext" },
  { ts: 6, type: "scene", scene_id: "scene_01", kind: "image", cached: true, path_url: "/files/a.png" },
];

const fold = (evs: RunEvent[]) => evs.reduce(runReducer, initialRun);

describe("runReducer", () => {
  it("builds scenes, stages and timings from the stream", () => {
    const s = fold(events);
    expect(s.status).toBe("running");
    expect(s.stage).toBe("images");
    expect(s.scenes[1].text).toBe("¡Hambre!");
    expect(s.scenes[0].image).toBe("/files/a.png");
    expect(s.scenes[0].cached.image).toBe(true);
    expect(s.ended.text).toBeCloseTo(5.1);
    expect(stageProgress(s, "images")).toBe(0.5);
  });

  it("replaying the same events yields the same state (reconnect)", () => {
    expect(fold([...events])).toEqual(fold(events));
  });

  it("closes the last stage on done and records durations", () => {
    const s = fold([
      ...events,
      { ts: 9, type: "done", video_url: "/files/final.mp4", social: "hi", output_dir: "o", duration: 30 },
    ]);
    expect(s.status).toBe("done");
    expect(s.result?.video).toBe("/files/final.mp4");
    const d = stageDurations(s);
    expect(Object.keys(d)).toEqual(["text:ollama: qwen3:8b", "images:flux-kontext"]);
    expect(d["text:ollama: qwen3:8b"]).toBeCloseTo(4.9);
    expect(d["images:flux-kontext"]).toBeCloseTo(3.9);
  });

  it("keeps the written story (Cuento) and a textless done as a preview", () => {
    const s = fold([
      ...events,
      { ts: 5.5, type: "story", title: "T", outline: "O", protagonist: "P", source: { url: "u", author: "a", subreddit: "s" } },
      { ts: 6, type: "done", video_url: null, social: "hi", output_dir: "o", duration: 0 },
    ]);
    expect(s.story?.title).toBe("T");
    expect(s.story?.source?.author).toBe("a");
    expect(s.status).toBe("done");
    expect(s.result?.video).toBeNull();
  });

  it("marks errors and cancellations", () => {
    expect(fold([...events, { ts: 7, type: "error", message: "boom", kind: "X" }]).error).toBe("boom");
    expect(fold([...events, { ts: 7, type: "cancelled" }]).status).toBe("cancelled");
  });
});

describe("progress events", () => {
  const loading: RunEvent = { ts: 5.2, type: "progress", stage: "images", scene_id: null, step: 0, total: 0, label: "cargando flux-kontext" };
  const step = (ts: number, n: number): RunEvent => ({ ts, type: "progress", stage: "images", scene_id: "scene_02", step: n, total: 24, label: "pasos" });

  it("tracks model loading, then per-scene steps with their start time", () => {
    let s = fold([...events, loading]);
    expect(s.loading?.label).toBe("cargando flux-kontext");
    s = [step(30, 6), step(60, 12)].reduce(runReducer, s);
    expect(s.loading).toBeNull();
    expect(s.scenes[1].work).toMatchObject({ step: 12, total: 24, since: 30 });
    // scene_01 done (1) + scene_02 half (0.5) over 2 scenes
    expect(stageProgress(s, "images")).toBe(0.75);
  });

  it("clears the scene's work when its image arrives", () => {
    const s = fold([...events, step(30, 12), { ts: 70, type: "scene", scene_id: "scene_02", kind: "image", cached: false, path_url: "/b.png" }]);
    expect(s.scenes[1].work).toBeNull();
    expect(stageProgress(s, "images")).toBe(1);
  });
});

describe("estimateRemaining", () => {
  it("uses per-scene progress for the current stage", () => {
    const s = fold(events);
    // images avg 100s, half the scenes done -> 50s left
    expect(estimateRemaining(s, { "images:flux-kontext": 100 })).toBe(50);
  });

  it("returns null without history for the current stage", () => {
    expect(estimateRemaining(fold(events), {})).toBeNull();
  });
});

describe("queued rerolls", () => {
  it("tracks queued rerolls once and the follow-up run", () => {
    const q: RunEvent = { ts: 7, type: "queued", scene_id: "scene_02", kind: "image" };
    const s = fold([...events, q, q, { ts: 8, type: "next", run_id: "r2" }]);
    expect(s.queued).toEqual(["scene_02:image"]);
    expect(s.next).toBe("r2");
    expect(s.status).toBe("running");
  });

  it("drops a reroll from the queue once the run takes it, and keeps the image prompt", () => {
    const s = fold([
      ...events,
      { ts: 7, type: "queued", scene_id: "scene_02", kind: "image" },
      { ts: 8, type: "rerolling", scene_id: "scene_02", kind: "image" },
      { ts: 9, type: "scene", scene_id: "scene_02", kind: "image", cached: false, path_url: "/x.png", prompt: "a red dragon" },
    ]);
    expect(s.queued).toEqual([]);
    expect(s.scenes.find((x) => x.scene_id === "scene_02")?.prompt).toBe("a red dragon");
  });
});
