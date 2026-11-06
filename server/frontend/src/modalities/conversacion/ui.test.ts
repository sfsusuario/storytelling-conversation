import { describe, expect, it } from "vitest";
import { parsePastedScript } from "./ui";

describe("parsePastedScript", () => {
  it("reads JSON inside a code fence", () => {
    expect(parsePastedScript('```json\n{"title": "T", "turns": []}\n```')).toEqual({ title: "T", turns: [] });
  });
  it("rejects the prompt, text without JSON and broken JSON", () => {
    expect(() => parsePastedScript("Responde solo con un objeto JSON con esta forma: {}")).toThrow(/prompt/);
    expect(() => parsePastedScript("hola")).toThrow(/no trae/);
    expect(() => parsePastedScript('{"title": ')).toThrow(/JSON inválido/);
  });
});
