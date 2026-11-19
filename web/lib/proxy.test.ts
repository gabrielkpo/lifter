import assert from "node:assert/strict";
import { test } from "node:test";
import { fromThisApp } from "./origin.ts";
import { messagePath, readPath, replacement } from "./proxy.ts";

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
