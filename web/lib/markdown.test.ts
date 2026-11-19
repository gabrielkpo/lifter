import assert from "node:assert/strict";
import { test } from "node:test";
import { blocks, spans } from "./markdown.ts";

const text = (t: string) => ({ kind: "text", text: t });

test("bold, italic and code are found inside a line, the rest stays text", () => {
  assert.deepEqual(spans("RIR **2** on *every* set of `back squat`"), [
    text("RIR "),
    { kind: "strong", text: "2" },
    text(" on "),
    { kind: "em", text: "every" },
    text(" set of "),
    { kind: "code", text: "back squat" },
  ]);
});

test("markup is never HTML and stars that open nothing stay as written", () => {
  assert.deepEqual(spans("<b>no</b> 3 * 5 kg"), [text("<b>no</b> 3 * 5 kg")]);
  assert.deepEqual(spans("**"), [text("**")]);
  assert.deepEqual(spans(""), []);
});

test("paragraphs are split by a blank line and keep their line breaks", () => {
  assert.deepEqual(blocks("Good session.\nRest well.\n\nTomorrow: legs."), [
    { kind: "paragraph", spans: [text("Good session.\nRest well.")] },
    { kind: "paragraph", spans: [text("Tomorrow: legs.")] },
  ]);
});

test("a title stands alone, whatever its level", () => {
  assert.deepEqual(blocks("## Week 4\nDeload."), [
    { kind: "heading", spans: [text("Week 4")] },
    { kind: "paragraph", spans: [text("Deload.")] },
  ]);
});

test("a list collects its items and the indented ones under the item above", () => {
  assert.deepEqual(blocks("Plan:\n- Squat\n  - 5x5\n  - RIR 2\n- Row"), [
    { kind: "paragraph", spans: [text("Plan:")] },
    {
      kind: "list",
      ordered: false,
      items: [
        { spans: [text("Squat")], children: [[text("5x5")], [text("RIR 2")]] },
        { spans: [text("Row")], children: [] },
      ],
    },
  ]);
});

test("a numbered list is its own list, and a change of kind starts a new one", () => {
  const out = blocks("1. Warm-up\n2) Strength\n- note");
  assert.equal(out.length, 2);
  assert.deepEqual(out[0], {
    kind: "list",
    ordered: true,
    items: [
      { spans: [text("Warm-up")], children: [] },
      { spans: [text("Strength")], children: [] },
    ],
  });
  assert.equal(out[1].kind === "list" && out[1].ordered, false);
});

test("a line after a list ends it, and an indented item with no list above is an item", () => {
  assert.deepEqual(blocks("- a\nthen this").map((b) => b.kind), ["list", "paragraph"]);
  assert.deepEqual(blocks("  - lonely"), [
    { kind: "list", ordered: false, items: [{ spans: [text("lonely")], children: [] }] },
  ]);
});
