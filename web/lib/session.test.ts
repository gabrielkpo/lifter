import assert from "node:assert/strict";
import { test } from "node:test";
import {
  isPublicPath,
  issueSession,
  passphraseMatches,
  SESSION_SECONDS,
  safeNext,
  sessionSecrets,
  verifySession,
} from "./session.ts";

const ENV = {
  LIFTER_APP_PASSPHRASE: "a long test passphrase",
  LIFTER_SESSION_KEY: "k".repeat(32),
};
const NOW = Date.UTC(2026, 10, 12, 9, 0);

test("without both secrets, or with short ones, the app stays closed", async () => {
  assert.equal(await sessionSecrets({}), null);
  assert.equal(await sessionSecrets({ LIFTER_SESSION_KEY: ENV.LIFTER_SESSION_KEY }), null);
  assert.equal(await sessionSecrets({ LIFTER_APP_PASSPHRASE: ENV.LIFTER_APP_PASSPHRASE }), null);
  assert.equal(await sessionSecrets({ ...ENV, LIFTER_APP_PASSPHRASE: "short" }), null);
  assert.equal(await sessionSecrets({ ...ENV, LIFTER_SESSION_KEY: "k".repeat(31) }), null);
  assert.equal(await verifySession(null, "v1.1.x", NOW), false);
});

test("a session this server signed is accepted until it expires", async () => {
  const secrets = await sessionSecrets(ENV);
  const token = await issueSession(secrets!, NOW);
  assert.equal(await verifySession(secrets, token, NOW), true);
  assert.equal(await verifySession(secrets, token, NOW + (SESSION_SECONDS - 60) * 1000), true);
  assert.equal(await verifySession(secrets, token, NOW + SESSION_SECONDS * 1000), false);
});

test("a forged, altered or foreign session is refused", async () => {
  const secrets = await sessionSecrets(ENV);
  const token = await issueSession(secrets!, NOW);
  const [version, expiry, signature] = token.split(".");
  const later = `${version}.${Number(expiry) + 3600}.${signature}`;
  const flipped = `${version}.${expiry}.${signature[0] === "A" ? "B" : "A"}${signature.slice(1)}`;
  for (const bad of [undefined, "", "v1", later, flipped, `v2.${expiry}.${signature}`, `${token}.x`]) {
    assert.equal(await verifySession(secrets, bad, NOW), false, String(bad));
  }
  // An expiry further than a session lasts was not issued here.
  const far = await issueSession(secrets!, NOW + 10 * SESSION_SECONDS * 1000);
  assert.equal(await verifySession(secrets, far, NOW), false);
});

test("changing the key or the passphrase signs every device out", async () => {
  const token = await issueSession((await sessionSecrets(ENV))!, NOW);
  const newKey = await sessionSecrets({ ...ENV, LIFTER_SESSION_KEY: "j".repeat(32) });
  const newPassphrase = await sessionSecrets({ ...ENV, LIFTER_APP_PASSPHRASE: "another passphrase" });
  assert.equal(await verifySession(newKey, token, NOW), false);
  assert.equal(await verifySession(newPassphrase, token, NOW), false);
});

test("only the exact passphrase signs in", async () => {
  const secrets = (await sessionSecrets(ENV))!;
  assert.equal(await passphraseMatches(secrets, ENV.LIFTER_APP_PASSPHRASE), true);
  for (const wrong of ["", "a long test passphras", `${ENV.LIFTER_APP_PASSPHRASE} `, "A LONG TEST PASSPHRASE"]) {
    assert.equal(await passphraseMatches(secrets, wrong), false, wrong);
  }
});

test("after signing in, the app goes to one of its own pages only", () => {
  assert.equal(safeNext("/coach?c=abc"), "/coach?c=abc");
  assert.equal(safeNext("/sessions/12"), "/sessions/12");
  for (const elsewhere of [null, undefined, "", "https://evil.example", "//evil.example", "/\\evil.example", "/\t/evil.example", "/\n/evil.example", "coach", "/login", "/login?next=/wod", "/auth/logout", "/auth/login", "/api/profile", "/api"]) {
    assert.equal(safeNext(elsewhere), "/", String(elsewhere));
  }
});

test("only the sign-in page and the install files are public", () => {
  for (const open of ["/login", "/auth/login", "/_next/static/chunks/app.js", "/manifest.webmanifest", "/sw.js", "/icon.svg", "/apple-icon", "/icons/192"]) {
    assert.equal(isPublicPath(open), true, open);
  }
  for (const closed of ["/", "/wod", "/coach", "/api/profile", "/api/conversations", "/auth/logout", "/login/x", "/_next/data/x.json", "/icons"]) {
    assert.equal(isPublicPath(closed), false, closed);
  }
});
