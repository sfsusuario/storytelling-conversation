import { describe, expect, it } from "vitest";
import { parseScript } from "./ScriptPaste";

const scene = (i: number) => ({ index: i, narration: `Escena ${i}.`, action: "the protagonist walks", setting: "a road, night", key_object: "", shot: "wide shot" });
const reply = (n = 4, extra = {}) => ({ title: "Tula", protagonist: "a turtle", caption: "c", hashtags: ["a", 3], scenes: Array.from({ length: n }, (_, i) => scene(i + 1)), ...extra });

describe("parseScript", () => {
  it("reads a fenced reply and fills what is optional", () => {
    const { script, warnings } = parseScript("Aquí tienes:\n```json\n" + JSON.stringify(reply(5)) + "\n```");
    expect(script.scenes).toHaveLength(5);
    expect(script.scenes[0].character).toBe("");
    expect(script.outline).toBe("");
    expect(script.hashtags).toEqual(["a"]);
    expect(warnings).toEqual([]);
  });
  it("refuses what the pipeline cannot use", () => {
    expect(() => parseScript("nada")).toThrow("objeto JSON");
    expect(() => parseScript("{ roto }")).toThrow("JSON inválido");
    expect(() => parseScript(JSON.stringify(reply(3)))).toThrow("de 4 a 8");
    expect(() => parseScript(JSON.stringify(reply(9)))).toThrow("de 4 a 8");
    expect(() => parseScript(JSON.stringify(reply(4, { title: "" })))).toThrow("title");
    expect(() => parseScript(JSON.stringify(reply(4, { protagonist: 1 })))).toThrow("texto");
    const noAction = reply();
    noAction.scenes[1] = { ...noAction.scenes[1], action: "" };
    expect(() => parseScript(JSON.stringify(noAction))).toThrow("sin \"action\"");
  });
  it("catches the prompt pasted by mistake and warns about Spanish image fields", () => {
    expect(() => parseScript('JSON shape: {"title": ""}')).toThrow("Esto es el prompt");
    const spanish = reply();
    spanish.scenes[2] = { ...spanish.scenes[2], setting: "camión" };
    expect(parseScript(JSON.stringify(spanish)).warnings).toEqual(["escena 3: campos de imagen que no parecen inglés"]);
  });
});
