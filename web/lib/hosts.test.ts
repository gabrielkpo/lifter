import assert from "node:assert/strict";
import { test } from "node:test";
import { isAllowedHost } from "./hosts.ts";

test("the app answers its own host names, with or without a port", () => {
  assert.equal(isAllowedHost("localhost:3000"), true);
  assert.equal(isAllowedHost("127.0.0.1:3000"), true);
  assert.equal(isAllowedHost("LOCALHOST"), true);
});

test("a rebound or foreign host name is refused", () => {
  assert.equal(isAllowedHost("evil.example:3000"), false);
  assert.equal(isAllowedHost("localhost.evil.example"), false);
  assert.equal(isAllowedHost("[::1]:3000"), false);
  assert.equal(isAllowedHost(null), false);
  assert.equal(isAllowedHost(""), false);
});
