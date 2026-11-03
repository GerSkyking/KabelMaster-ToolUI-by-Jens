import { describe, expect, it } from "vitest";
import { analyze, plausibility, computeLength, excelLetter, formatNumber, parseNumber, shortDate } from "./cable";

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

  it("ignores cables without target meters", () => {
    const r = analyze(rows, { ...mapping }, { ignoreShort: false, minLength: 0, ignoreNoTarget: true });
    expect(r.ignored).toBe(0);
    const zero = [...rows, { Kabel: "e", QS: "3x1,5", Soll: 0, Ist: null }, { Kabel: "f", QS: "3x1,5", Soll: null, Ist: null }];
    const r2 = analyze(zero, mapping, { ignoreShort: false, minLength: 0, ignoreNoTarget: true });
    expect(r2.ignored).toBe(2);
    expect(r2.total.total).toBe(4);
  });

  it("groups by route regardless of direction", () => {
    const m = { ...mapping, target1: "Z1", target2: "Z2" };
    const data = [
      { Kabel: "a", QS: "x", Soll: 10, Ist: 10, Z1: "A", Z2: "B" },
      { Kabel: "b", QS: "x", Soll: 10, Ist: null, Z1: "B", Z2: "A" },
      { Kabel: "c", QS: "x", Soll: 10, Ist: null, Z1: "A", Z2: "C" },
    ];
    const r = analyze(data, m, { ignoreShort: false, minLength: 0 }, "route");
    expect(r.groups.map((g) => [g.label, g.total, g.done])).toEqual([["A ↔ B", 2, 1], ["A ↔ C", 1, 0]]);
  });

  it("warns about implausible entries", () => {
    expect(plausibility(10, 5, 5)).toMatch(/gleich/);
    expect(plausibility(10, 0, 10.5)).toBeNull();
    expect(plausibility(10, 0, 14)).toMatch(/\+40 %/);
    expect(plausibility(null, 0, 14)).toBeNull();
    expect(plausibility(10, null, null)).toBeNull();
  });

  it("ignores short ends", () => {
    const r = analyze(rows, mapping, { ignoreShort: true, minLength: 5 });
    expect(r.ignored).toBe(1);
    expect(r.total.total).toBe(3);
    expect(r.total.metersTotal).toBe(60);
  });
});
