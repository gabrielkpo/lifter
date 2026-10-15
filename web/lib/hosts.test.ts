import assert from "node:assert/strict";
import { test } from "node:test";
import { allowedHosts, isAllowedHost } from "./hosts.ts";

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

test("on Vercel the deployment's own host names are allowed, nothing else", () => {
  const allowed = allowedHosts({
    VERCEL_URL: "lifter-abc123.vercel.app",
    VERCEL_BRANCH_URL: "lifter-git-main-gabriel.vercel.app",
    VERCEL_PROJECT_PRODUCTION_URL: "lifter.vercel.app",
    LIFTER_WEB_HOSTS: " Lifter.example.com ,",
  });
  assert.equal(isAllowedHost("lifter-abc123.vercel.app", allowed), true);
  assert.equal(isAllowedHost("lifter.vercel.app", allowed), true);
  assert.equal(isAllowedHost("lifter.example.com", allowed), true);
  assert.equal(isAllowedHost("localhost:3000", allowed), true);
  assert.equal(isAllowedHost("other-app.vercel.app", allowed), false);
  assert.equal(isAllowedHost("evil.example", allowed), false);
});

test("without Vercel variables only this machine is allowed", () => {
  assert.deepEqual(allowedHosts({}), ["localhost", "127.0.0.1"]);
});
