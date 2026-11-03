import { useEffect, useMemo, useRef, useState } from "react";

/** Dropdown mit Checkboxen: mehrere Querschnitte wählen, alle/keine, mit Suche. selected = null bedeutet "alle". */
export function SectionFilter({ options, selected, onChange, noun = "Querschnitt", nounPlural = "Querschnitte" }: {
  options: string[];
  noun?: string;
  nounPlural?: string;
  selected: Set<string> | null;
  onChange: (next: Set<string> | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? options.filter((o) => o.toLowerCase().includes(t)) : options;
  }, [options, q]);

  const has = (o: string) => selected === null || selected.has(o);
  const commit = (set: Set<string>) => onChange(options.every((o) => set.has(o)) ? null : set);
  const toggle = (o: string) => {
    const set = new Set(selected ?? options);
    if (set.has(o)) set.delete(o); else set.add(o);
    commit(set);
  };
  const selectShown = () => commit(new Set([...(selected ?? options), ...shown]));
  const clearShown = () => commit(new Set([...(selected ?? options)].filter((o) => !shown.includes(o))));

  const count = selected === null ? options.length : options.filter((o) => selected.has(o)).length;
  const label = selected === null ? `Alle ${nounPlural}`
    : count === 0 ? `Kein ${noun}`
    : count === 1 ? options.find((o) => selected.has(o))! : `${count} ${nounPlural}`;

  return (
    <div className="multi" ref={box}>
      <button type="button" className={selected === null ? "" : "active"} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {label} ▾
      </button>
      {open && (
        <div className="multi-pop">
          <input type="search" placeholder={`${noun} suchen …`} value={q} autoFocus onChange={(e) => setQ(e.target.value)} />
          <div className="multi-actions">
            <button type="button" onClick={selectShown}>Alle auswählen</button>
            <button type="button" onClick={clearShown}>Keine auswählen</button>
          </div>
          <div className="multi-list">
            {shown.map((o) => (
              <label key={o} className="check">
                <input type="checkbox" checked={has(o)} onChange={() => toggle(o)} /> {o}
              </label>
            ))}
            {!shown.length && <span className="muted">Nichts gefunden.</span>}
          </div>
        </div>
      )}
    </div>
  );
}
