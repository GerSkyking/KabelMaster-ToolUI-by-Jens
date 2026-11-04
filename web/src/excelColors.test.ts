import { describe, expect, it } from "vitest";
import { cellColors, contrast } from "./excelColors";

const rgb = (hex: string): [number, number, number] => {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};

describe("cellColors", () => {
  it("liefert nichts ohne Farbe oder im Modus aus", () => {
    expect(cellColors(undefined, true, "adapted")).toEqual({});
    expect(cellColors(["#ffff00", ""], false, "off")).toEqual({});
  });
  it("Original lässt die Farben unverändert", () => {
    expect(cellColors(["#ffff00", "#0000ff"], true, "original")).toEqual({ background: "#ffff00", color: "#0000ff" });
  });
  it("dunkelt helle Füllungen im Dunkelmodus ab und lässt den Text lesbar", () => {
    const c = cellColors(["#ffff00", ""], true, "adapted");
    expect(c.background).toBeDefined();
    expect(contrast(rgb(c.background!), rgb("#17212c"))).toBeLessThan(3); // dunkel genug, kein grelles Gelb
    const text = c.color ?? "#e6edf3";
    expect(contrast(rgb(text), rgb(c.background!))).toBeGreaterThanOrEqual(4.5);
  });
  it("hellt zu dunkle Schrift im Dunkelmodus auf", () => {
    const c = cellColors(["", "#000080"], true, "adapted");
    expect(contrast(rgb(c.color!), rgb("#17212c"))).toBeGreaterThanOrEqual(3.5);
  });
  it("dunkelt weiße Schrift im Hellmodus ab", () => {
    const c = cellColors(["", "#ffffff"], false, "adapted");
    expect(contrast(rgb(c.color!), rgb("#ffffff"))).toBeGreaterThanOrEqual(3.5);
  });
  it("Füllung im Hellmodus bleibt, dunkle Füllung bekommt hellen Text", () => {
    expect(cellColors(["#ffff00", ""], false, "adapted").background).toBe("#ffff00");
    const dark = cellColors(["#1f3864", ""], false, "adapted");
    expect(contrast(rgb(dark.color ?? "#17202a"), rgb(dark.background!))).toBeGreaterThanOrEqual(4.5);
  });
});
