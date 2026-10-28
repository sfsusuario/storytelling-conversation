import { describe, expect, it } from "vitest";
import { diffEdits, exportForClaude, parseClaudeReply } from "./StoryPreview";
import { initialRun, type SceneState } from "../escalera/runState";

const shot = { action: "the protagonist looks up", setting: "riverbank, morning", key_object: "", shot: "wide shot", character: "" };
const scenes: SceneState[] = [
  { scene_id: "scene_01", level: 1, persona: "Escena 1", text: "Tula miraba.", shot, cached: {} },
  { scene_id: "scene_02", level: 2, persona: "Escena 2", text: "Saltó.", shot, cached: {} },
];

describe("diffEdits", () => {
  it("sends only what changed", () => {
    const drafts = {
      scene_01: { ...shot, narration: "Tula miraba." },
      scene_02: { ...shot, narration: "Saltó alto.", character: "an old turtle" },
    };
    expect(diffEdits(scenes, drafts, ["Tula", "Tula"], ["a turtle", "a turtle"])).toEqual({
      scenes: { scene_02: { narration: "Saltó alto.", character: "an old turtle" } },
    });
    expect(diffEdits(scenes, drafts, ["Tula", "Tula nada"], ["a turtle", "  "]).title).toBe("Tula nada");
    expect(diffEdits(scenes, { scene_01: drafts.scene_01 }, ["T", "T"], ["p", "p"])).toEqual({});
  });
});

describe("Claude round trip", () => {
  it("exports the rules, the source URL and the script", () => {
    const state = {
      ...initialRun,
      scenes,
      story: { title: "Tula", outline: "o", protagonist: "a turtle", source: { url: "https://www.reddit.com/r/x/comments/1/t/", author: "a", subreddit: "x" } },
    };
    const text = exportForClaude(state, { scene_01: { ...shot, narration: "Tula miraba." } }, "Tula", "a turtle");
    expect(text).toContain("ONLY understands English");
    expect(text).toContain("https://www.reddit.com/r/x/comments/1/t/");
    const json = JSON.parse(text.slice(text.indexOf("script:\n") + 8));
    expect(json.scenes.map((s: { scene_id: string }) => s.scene_id)).toEqual(["scene_01", "scene_02"]);
    expect(json.scenes[1].narration).toBe("Saltó."); // a scene without a draft keeps the model's text
  });
  it("parses a fenced reply by scene_id and reports what changed", () => {
    const body = JSON.stringify({
      title: "Tula nada",
      scenes: [
        { scene_id: "scene_02", narration: "Saltó alto.", character: "an old turtle" },
        { scene_id: "scene_01", narration: "Tula miraba." },
      ],
    });
    const got = parseClaudeReply("```json\n" + body + "\n```", scenes);
    expect(got.title).toBe("Tula nada");
    expect(got.scenes.scene_02).toEqual({ ...shot, narration: "Saltó alto.", character: "an old turtle" });
    expect(got.scenes.scene_01.action).toBe(shot.action); // missing fields keep the current value
    expect([got.changed, got.same]).toEqual([[2], [1]]);
    expect(got.warnings).toEqual([]);
  });
  it("validates the reply before touching the form", () => {
    const ok = { scene_id: "scene_01", narration: "Otra." };
    const two = (a: object, b: object) => JSON.stringify({ scenes: [a, b] });
    // the text copied FOR Claude pasted back by mistake: its JSON is the current script
    const state = { ...initialRun, scenes, story: { title: "T", outline: "", protagonist: "p", source: null } };
    expect(() => parseClaudeReply(exportForClaude(state, {}, "T", "p"), scenes)).toThrow(/PARA Claude/);
    expect(() => parseClaudeReply("hola", scenes)).toThrow(/JSON/);
    expect(() => parseClaudeReply('{"scenes": [', scenes)).toThrow(/JSON inválido/);
    expect(() => parseClaudeReply('{"scenes":[{"narration":"x"}]}', scenes)).toThrow(/2 escenas/);
    expect(() => parseClaudeReply(two(ok, { scene_id: "scene_9", narration: "x" }), scenes)).toThrow(/scene_id inválido/);
    expect(() => parseClaudeReply(two(ok, ok), scenes)).toThrow(/dos veces/);
    expect(() => parseClaudeReply(two(ok, { scene_id: "scene_02", narration: 3 }), scenes)).toThrow(/debe ser texto/);
    expect(() => parseClaudeReply(two(ok, { scene_id: "scene_02", narration: " " }), scenes)).toThrow(/sin narración/);
    const same = two({ scene_id: "scene_01", narration: "Tula miraba." }, { scene_id: "scene_02", narration: "Saltó." });
    expect(() => parseClaudeReply(same, scenes)).toThrow(/idéntica/);
    // broken generator rules are applied but flagged
    const long = two({ scene_id: "scene_01", narration: "palabra ".repeat(40), action: "la tortuga mira" }, { scene_id: "scene_02", narration: "Saltó." });
    expect(parseClaudeReply(long, scenes).warnings).toEqual(["escena 1: narración de más de 35 palabras"]);
  });
});
