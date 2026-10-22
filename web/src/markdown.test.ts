import { describe, expect, it } from "vitest";
import { renderMarkdown } from "./markdown";

describe("markdown", () => {
  it("renders headings, emphasis, code and lists", () => {
    const html = renderMarkdown("# Titel\n\nText mit **fett**, *kursiv* und `code`.\n\n- eins\n- [x] zwei\n\n1. a\n2. b");
    expect(html).toContain("<h1>Titel</h1>");
    expect(html).toContain("<strong>fett</strong>");
    expect(html).toContain("<em>kursiv</em>");
    expect(html).toContain("<code>code</code>");
    expect(html).toContain("<ul><li>eins</li><li class=\"task\">☑ zwei</li></ul>");
    expect(html).toContain("<ol><li>a</li><li>b</li></ol>");
  });

  it("escapes raw html and blocks unsafe links", () => {
    const html = renderMarkdown('<script>alert(1)</script> [x](javascript:alert(1)) [ok](https://example.org/a?b=1&c="2")');
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain('href="javascript');
    expect(html).toContain('<a href="https://example.org/a?b=1&amp;c=&quot;2&quot;"');
  });

  it("renders fenced code literally and tables", () => {
    const html = renderMarkdown("```\n**kein fett** <b>\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |");
    expect(html).toContain("<pre><code>**kein fett** &lt;b&gt;</code></pre>");
    expect(html).toContain("<th>A</th>");
    expect(html).toContain("<td>2</td>");
  });
});
