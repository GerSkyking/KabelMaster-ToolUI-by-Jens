import { describe, expect, it } from "vitest";
import { analyze, computeLength, excelLetter, formatNumber, parseNumber, shortDate } from "./cable";

const mapping = {
  cable_id: "Kabel", cross_section: "QS", target_length: "Soll", start: "Von", end: "Bis", pulled_length: "Ist",
};

describe("cable", () => {
  it("parses numbers", () => {
    expect(parseNumber("12,5")).toBe(12.5);
    expect(parseNumber("7 m")).toBe(7);
    expect(parseNumber(null)).toBeNull();
    expect(parseNumber("abc")).toBeNull();
  });

  it("computes absolute length", () => {
    expect(computeLength(120, "100,5")).toBe(19.5);
    expect(computeLength(10, null)).toBeNull();
    expect(formatNumber(12.5)).toBe("12,5");
  });

  it("formats the date as TT.MM.JJ", () => {
    expect(shortDate(new Date(2026, 11, 30))).toBe("30.12.26");
    expect(shortDate(new Date(2027, 0, 5))).toBe("05.01.27");
  });

  it("names excel columns", () => {
    expect([0, 25, 26, 27].map(excelLetter)).toEqual(["A", "Z", "AA", "AB"]);
  });

  const rows = [
    { Kabel: "a", QS: "3x1,5", Soll: 10, Ist: 10 },
    { Kabel: "b", QS: "3x1,5", Soll: 1, Ist: null },
    { Kabel: "c", QS: "5x2,5", Soll: 20, Ist: null },
    { Kabel: "d", QS: "5x2,5", Soll: 30, Ist: 0 },
  ];

  it("analyzes per cross section", () => {
    const r = analyze(rows, mapping, { ignoreShort: false, minLength: 0 });
    expect([r.total.total, r.total.done]).toEqual([4, 1]);
    expect(r.groups.map((g) => g.label)).toEqual(["3x1,5", "5x2,5"]);
  });

  it("ignores short ends", () => {
    const r = analyze(rows, mapping, { ignoreShort: true, minLength: 5 });
    expect(r.ignored).toBe(1);
    expect(r.total.total).toBe(3);
    expect(r.total.metersTotal).toBe(60);
  });
});
