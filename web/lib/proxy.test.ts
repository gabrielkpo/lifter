import assert from "node:assert/strict";
import { test } from "node:test";
import { fromThisApp } from "./origin.ts";
import { bodyRefused, MAX_BODY, messagePath, readCapped, readPath, replacement } from "./proxy.ts";

test("a GET reads one of the API's endpoints, with at most one id", () => {
  assert.equal(readPath(["profile"]), "profile");
  assert.equal(readPath(["sessions", "12"]), "sessions/12");
  assert.equal(readPath(["conversations", "a1b2-c3_d4"]), "conversations/a1b2-c3_d4");
});

test("a GET elsewhere is refused: unknown endpoint, deeper path, odd segment", () => {
  for (const path of [
    ["proposals"],
    ["conversation"],
    ["admin"],
    ["sessions", "12", "lines"],
    ["sessions", "../profile"],
    ["sessions", "12.json"],
    ["sessions", ""],
    ["sessions", "x".repeat(65)],
    [],
  ]) {
    assert.equal(readPath(path), null, path.join("/"));
  }
});

test("a message goes to a new conversation, one by its id, or the undo of a change", () => {
  assert.equal(messagePath(["conversations"]), "conversations");
  assert.equal(messagePath(["conversations", "abc-123"]), "conversations/abc-123");
  assert.equal(messagePath(["conversations", "abc-123", "undo"]), "conversations/abc-123/undo");
});

test("a message anywhere else is refused", () => {
  for (const path of [
    ["conversation"],
    ["profile"],
    ["conversations", "abc", "messages"],
    ["conversations", "a/b"],
    ["conversations", "abc", "undo", "1"],
    ["proposals", "1", "approve"],
    [],
  ]) {
    assert.equal(messagePath(path), null, path.join("/"));
  }
});

test("the API's own answers pass through as they are", () => {
  for (const status of [200, 201, 204, 404, 409, 422, 429, 502, 503]) {
    assert.equal(replacement(status), null, String(status));
  }
});

test("a refusal of the app's token or bypass becomes 503, distinct from a failure", () => {
  for (const status of [401, 403, 301, 302, 307, 308]) {
    assert.deepEqual(replacement(status), { status: 503, detail: "Lifter API refused the request" });
  }
});

test("any other error becomes a plain 502, without the API's detail", () => {
  for (const status of [400, 405, 413, 500, 504]) {
    assert.deepEqual(replacement(status), { status: 502, detail: "Lifter API error" });
  }
});

test("a POST counts as the app's own only with the app's origin", () => {
  const request = (origin: string | null) =>
    ({
      headers: new Headers(origin === null ? {} : { origin }),
      nextUrl: new URL("https://lifter.example/api/conversations"),
    }) as Parameters<typeof fromThisApp>[0];
  assert.equal(fromThisApp(request("https://lifter.example")), true);
  for (const origin of [null, "null", "https://evil.example", "http://lifter.example", "https://lifter.example:8443"]) {
    assert.equal(fromThisApp(request(origin)), false, String(origin));
  }
});

test("a message is refused before it is read when its length is too long or odd", () => {
  assert.equal(bodyRefused(null), false); // no header: read up to the limit instead
  assert.equal(bodyRefused("120"), false);
  assert.equal(bodyRefused(String(MAX_BODY)), false);
  for (const length of ["", "abc", "-1", "1.5", "1e3", " 12", String(MAX_BODY + 1), "9999999999"]) {
    assert.equal(bodyRefused(length), true, length);
  }
});

const stream = (...parts: string[]) =>
  new ReadableStream<Uint8Array>({
    start(controller) {
      for (const part of parts) controller.enqueue(new TextEncoder().encode(part));
      controller.close();
    },
  });

test("a body is read up to the limit in bytes, and given up past it", async () => {
  assert.equal(await readCapped(stream('{"text":', '"é 💪"}')), '{"text":"é 💪"}');
  assert.equal(await readCapped(null), "");
  assert.equal(await readCapped(stream("abc"), 3), "abc");
  assert.equal(await readCapped(stream("ab", "cd"), 3), null);
  assert.equal(await readCapped(stream("éé"), 3), null); // 4 bytes, 2 characters
});
