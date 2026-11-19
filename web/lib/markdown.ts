// The coach writes Markdown; the Coach page shows a small part of it as text, never as HTML:
// paragraphs, "#" titles, "- " and "1. " lists (one level of items under an item, indented),
// **bold**, *italic* and `code`. Parsed here into plain data, drawn by app/coach (MessageText).

export type Span = { kind: "text" | "strong" | "em" | "code"; text: string };

export type ListItem = { spans: Span[]; children: Span[][] };

export type Block =
  | { kind: "paragraph"; spans: Span[] }
  | { kind: "heading"; spans: Span[] }
  | { kind: "list"; ordered: boolean; items: ListItem[] };

/** **bold**, *italic* and `code` inside a line; everything else is text, as written. */
export function spans(text: string): Span[] {
  return text
    .split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)/g)
    .filter((piece) => piece !== "")
    .map((piece): Span => {
      if (piece.length > 4 && piece.startsWith("**") && piece.endsWith("**")) {
        return { kind: "strong", text: piece.slice(2, -2) };
      }
      if (piece.length > 2 && piece.startsWith("*") && piece.endsWith("*")) {
        return { kind: "em", text: piece.slice(1, -1) };
      }
      if (piece.length > 2 && piece.startsWith("`") && piece.endsWith("`")) {
        return { kind: "code", text: piece.slice(1, -1) };
      }
      return { kind: "text", text: piece };
    });
}

/** A reply's text as blocks: a blank line ends a paragraph or a list, a title stands alone, a
 * list changes when it goes from "- " to "1. " (or back), an indented item belongs to the
 * item above it. */
export function blocks(text: string): Block[] {
  const out: Block[] = [];
  let paragraph: string[] = [];
  let items: { text: string; children: string[] }[] = [];
  let ordered = false;
  const flush = () => {
    if (paragraph.length) {
      out.push({ kind: "paragraph", spans: spans(paragraph.join("\n")) });
      paragraph = [];
    }
    if (items.length) {
      out.push({
        kind: "list",
        ordered,
        items: items.map((item) => ({
          spans: spans(item.text),
          children: item.children.map(spans),
        })),
      });
      items = [];
    }
  };
  for (const line of text.split("\n")) {
    const title = /^\s*#{1,6}\s+(.*)$/.exec(line);
    const item = /^(\s*)(?:([-*•])|(\d+)[.)])\s+(.*)$/.exec(line);
    if (title) {
      flush();
      out.push({ kind: "heading", spans: spans(title[1]) });
    } else if (item) {
      const [, indent, , number, words] = item;
      if (indent.length >= 2 && items.length) {
        items[items.length - 1].children.push(words);
        continue;
      }
      if (paragraph.length || (items.length && ordered !== (number !== undefined))) flush();
      ordered = number !== undefined;
      items.push({ text: words, children: [] });
    } else if (!line.trim()) {
      flush();
    } else {
      if (items.length) flush();
      paragraph.push(line);
    }
  }
  flush();
  return out;
}
