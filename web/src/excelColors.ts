// Excel-Zellfarben für die Anzeige: Original oder an Hell-/Dunkelmodus angepasst (damit Text lesbar bleibt).
import { useEffect, useState } from "react";

export const STYLE_KEY = "__style";
export type ColorMode = "adapted" | "original" | "off";
export type CellStyle = [string, string]; // [Hintergrund, Schrift] als #rrggbb oder ""
export type RowStyle = Record<string, CellStyle>;

const PAGE_BG = { light: "#ffffff", dark: "#17212c" };

type RGB = [number, number, number];

function parse(hex: string): RGB | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const toHex = ([r, g, b]: RGB) => "#" + [r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("");

function toHsl([r, g, b]: RGB): [number, number, number] {
  const R = r / 255, G = g / 255, B = b / 255;
  const max = Math.max(R, G, B), min = Math.min(R, G, B), l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === R ? (G - B) / d + (G < B ? 6 : 0) : max === G ? (B - R) / d + 2 : (R - G) / d + 4;
  return [h / 6, s, l];
}

function fromHsl([h, s, l]: [number, number, number]): RGB {
  if (s === 0) return [l * 255, l * 255, l * 255];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = (t: number) => {
    const x = t < 0 ? t + 1 : t > 1 ? t - 1 : t;
    return x < 1 / 6 ? p + (q - p) * 6 * x : x < 1 / 2 ? q : x < 2 / 3 ? p + (q - p) * (2 / 3 - x) * 6 : p;
  };
  return [f(h + 1 / 3) * 255, f(h) * 255, f(h - 1 / 3) * 255];
}

/** Relative Helligkeit nach WCAG */
function luminance([r, g, b]: RGB): number {
  const c = [r, g, b].map((v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}

export function contrast(a: RGB, b: RGB): number {
  const la = luminance(a), lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

export interface CssColors { background?: string; color?: string }

/**
 * Farben einer Zelle für die Anzeige. `adapted`: im Dunkelmodus werden helle Füllungen abgedunkelt (Farbton bleibt),
 * zu dunkle Schriftfarben aufgehellt; im Hellmodus werden helle Schriftfarben abgedunkelt. Der Text bleibt immer lesbar.
 */
export function cellColors(style: CellStyle | undefined, dark: boolean, mode: ColorMode): CssColors {
  if (!style || mode === "off") return {};
  const bg = parse(style[0]), fg = parse(style[1]);
  if (!bg && !fg) return {};
  if (mode === "original") return { background: bg ? toHex(bg) : undefined, color: fg ? toHex(fg) : undefined };

  let bgOut: RGB | null = bg;
  if (bg && dark) {
    const [h, s, l] = toHsl(bg);
    bgOut = fromHsl([h, Math.min(s, 0.65), 0.12 + l * 0.2]); // 0,12 .. 0,32: bleibt unterscheidbar, ist aber dunkel
  }
  const base = parse(bgOut ? toHex(bgOut) : PAGE_BG[dark ? "dark" : "light"])!;
  let fgOut: RGB | null = fg;
  if (fg) {
    const [h, s, l] = toHsl(fg);
    if (dark && l < 0.7) fgOut = fromHsl([h, s, 0.72]);
    else if (!dark && l > 0.8) fgOut = fromHsl([h, s, 0.3]);
  }
  if (!fgOut || contrast(fgOut, base) < 3.5) {
    if (!bgOut && !fgOut) return {};
    // Standardtext der Seite beibehalten, solange er auf der Füllung lesbar ist; sonst Schwarz/Weiß
    const pageText = parse(dark ? "#e6edf3" : "#17202a")!;
    const text = contrast(pageText, base) >= 4.5 ? undefined : luminance(base) > 0.4 ? "#111111" : "#f4f4f4";
    return { background: bgOut ? toHex(bgOut) : undefined, color: fgOut && !bgOut && contrast(fgOut, base) >= 3.5 ? toHex(fgOut) : text };
  }
  return { background: bgOut ? toHex(bgOut) : undefined, color: toHex(fgOut) };
}

export function styleOf(data: Record<string, unknown>, column: string): CellStyle | undefined {
  const s = data[STYLE_KEY] as RowStyle | undefined;
  const v = s?.[column];
  return Array.isArray(v) ? v : undefined;
}

export function hasColors(rows: { data: Record<string, unknown> }[]): boolean {
  return rows.some((r) => !!r.data[STYLE_KEY]);
}

/** true, wenn das System den Dunkelmodus nutzt (reagiert auf Wechsel) */
export function useDark(): boolean {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => typeof matchMedia === "function" && matchMedia(query).matches);
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const m = matchMedia(query);
    const on = () => setDark(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return dark;
}
