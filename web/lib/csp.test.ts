import assert from "node:assert/strict";
import { test } from "node:test";
import { contentSecurityPolicy, newNonce, PERMISSIONS_POLICY } from "./csp.ts";

const directives = (policy: string) =>
  new Map(policy.split("; ").map((d) => [d.split(" ")[0], d.split(" ").slice(1)]));

test("each request gets its own nonce", () => {
  const a = newNonce();
  assert.match(a, /^[A-Za-z0-9+/]{22}==$/);
  assert.notEqual(a, newNonce());
});

test("in production only this app's marked scripts run and nothing loads from elsewhere", () => {
  const policy = directives(contentSecurityPolicy("abc"));
  assert.deepEqual(policy.get("script-src"), ["'self'", "'nonce-abc'", "'strict-dynamic'"]);
  assert.deepEqual(policy.get("default-src"), ["'self'"]);
  assert.deepEqual(policy.get("connect-src"), ["'self'"]);
  assert.deepEqual(policy.get("object-src"), ["'none'"]);
  assert.deepEqual(policy.get("base-uri"), ["'none'"]);
  assert.deepEqual(policy.get("frame-ancestors"), ["'none'"]);
  assert.deepEqual(policy.get("form-action"), ["'self'"]);
  for (const [name, sources] of policy) {
    assert.ok(!sources.includes("'unsafe-eval'"), name);
    assert.ok(!sources.some((s) => s.startsWith("http") || s === "*"), name);
  }
});

test("the dev server gets eval and its websocket, nothing more", () => {
  const policy = directives(contentSecurityPolicy("abc", true));
  assert.ok(policy.get("script-src")?.includes("'unsafe-eval'"));
  assert.deepEqual(policy.get("connect-src"), ["'self'", "ws:"]);
});

test("camera, microphone, location and payment are off", () => {
  for (const feature of ["camera=()", "microphone=()", "geolocation=()", "payment=()"]) {
    assert.ok(PERMISSIONS_POLICY.includes(feature), feature);
  }
});
