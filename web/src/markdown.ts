/** Kleiner, sicherer Markdown-Renderer für Notizen. Der Text wird zuerst HTML-escaped; es entsteht nur Markup,
 * das hier erzeugt wird (kein Roh-HTML aus der Notiz, Links nur http/https/mailto). */

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function inline(text: string): string {
  const codes: string[] = [];
  let t = esc(text).replace(/`([^`]+)`/g, (_, c: string) => {
    codes.push(c);
    return `\u0000${codes.length - 1}\u0000`;
  });
  t = t
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/~~([^~]+)~~/g, "<del>$1</del>")
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+|mailto:[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
    );
  return t.replace(/\u0000(\d+)\u0000/g, (_, i: string) => `<code>${codes[Number(i)]}</code>`);
}

const isTableRule = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
const cells = (line: string) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

export function renderMarkdown(source: string, lineOffset = 0): string {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (/^```/.test(line)) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i++;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      out.push("<hr>");
      i++;
      continue;
    }
    if (/^>\s?/.test(line)) {
      const quote: string[] = [];
      const start = i;
      while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote>${renderMarkdown(quote.join("\n"), lineOffset + start)}</blockquote>`);
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && isTableRule(lines[i + 1]) && lines[i + 1].includes("-")) {
      const head = cells(line);
      i += 2;
      const body: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) body.push(cells(lines[i++]));
      out.push(
        "<table><thead><tr>" + head.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>" +
          body.map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") +
          "</tbody></table>",
      );
      continue;
    }
    const list = /^(\s*)([-*+]|\d+\.)\s+/.exec(line);
    if (list) {
      const ordered = /\d/.test(list[2]);
      const items: string[] = [];
      while (i < lines.length) {
        const m = /^(\s*)([-*+]|\d+\.)\s+(.*)$/.exec(lines[i]);
        if (!m) break;
        const task = /^\[([ xX])\]\s+(.*)$/.exec(m[3]);
        items.push(
          task
            ? `<li class="task" data-line="${lineOffset + i}">${task[1] === " " ? "☐" : "☑"} ${inline(task[2])}</li>`
            : `<li>${inline(m[3])}</li>`,
        );
        i++;
      }
      out.push(`<${ordered ? "ol" : "ul"}>${items.join("")}</${ordered ? "ol" : "ul"}>`);
      continue;
    }
    const paragraph: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|>|\s*([-*+]|\d+\.)\s)/.test(lines[i])) {
      paragraph.push(lines[i++]);
    }
    if (!paragraph.length) paragraph.push(lines[i++]);
    out.push(`<p>${paragraph.map(inline).join("<br>")}</p>`);
  }
  return out.join("\n");
}

/** Schaltet das Häkchen einer Aufgabe (`- [ ]` / `- [x]`) in der angegebenen Zeile um. */
export function toggleTask(source: string, line: number): string {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  if (line < 0 || line >= lines.length) return source;
  lines[line] = lines[line].replace(/\[( |x|X)\]/, (_, mark: string) => (mark === " " ? "[x]" : "[ ]"));
  return lines.join("\n");
}
