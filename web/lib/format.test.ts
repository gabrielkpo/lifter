import assert from "node:assert/strict";
import { test } from "node:test";
import {
  addDays,
  clock,
  isoDay,
  label,
  monthYear,
  num,
  parseDay,
  partFormat,
  partResult,
  partTarget,
  prescription,
  shortDate,
  weekday,
} from "./format.ts";
import type { Line, Part } from "./types.ts";

test("a day is read as a local date, never shifted by the time zone", () => {
  const day = parseDay("2026-03-02");
  assert.deepEqual([day.getFullYear(), day.getMonth(), day.getDate()], [2026, 2, 2]);
  assert.equal(isoDay(day), "2026-03-02");
});

test("adding days crosses months, years and the clock changes", () => {
  assert.equal(addDays("2026-01-31", 1), "2026-02-01");
  assert.equal(addDays("2026-12-31", 1), "2027-01-01");
  assert.equal(addDays("2026-03-28", 2), "2026-03-30"); // Europe's spring change, 29/03
  assert.equal(addDays("2026-10-24", 2), "2026-10-26"); // and autumn, 25/10
  assert.equal(addDays("2026-03-02", -7), "2026-02-23");
});

test("dates read the way the app shows them", () => {
  assert.equal(weekday("2026-11-19"), "Thu");
  assert.equal(shortDate("2026-11-19"), "Thu 19 Nov");
  assert.equal(monthYear("2026-07-16"), "Jul 2026");
});

test("numbers, times and codes", () => {
  assert.equal(num(60), "60");
  assert.equal(num(62.5), "62.5");
  assert.equal(num(1 / 3), "0.33");
  assert.equal(clock(754), "12'34");
  assert.equal(clock(60), "1'00");
  assert.equal(label("strength_peak"), "Strength peak");
});

const line = (over: Partial<Line>): Line => ({
  position: 1,
  exercise: "Back squat",
  category: "strength",
  pattern: "squat",
  sets: null,
  quantity: null,
  unit: "reps",
  load_kg: null,
  load_kg_max: null,
  rir: null,
  rest_seconds: null,
  notes: null,
  ...over,
});

test("a line's prescription: sets, amount, unit and load range", () => {
  assert.equal(prescription(line({ sets: 4, quantity: 8, load_kg: 60, load_kg_max: 62.5 })), "4×8 @ 60–62.5 kg");
  assert.equal(prescription(line({ quantity: 500, unit: "m" })), "500 m");
  assert.equal(prescription(line({ sets: 3 })), "3 sets");
  assert.equal(prescription(line({ load_kg: 20 })), "@ 20 kg");
  assert.equal(prescription(line({})), "");
});

const part = (over: Partial<Part>): Part => ({
  position: 1,
  kind: "metcon",
  title: null,
  notes: null,
  format: null,
  duration_minutes: null,
  rounds: null,
  interval_seconds: null,
  target_seconds: null,
  target_rounds: null,
  result_seconds: null,
  result_rounds: null,
  result_notes: null,
  planned: [],
  done: [],
  ...over,
});

test("a metcon's header, target and result", () => {
  assert.equal(partFormat(part({ format: "amrap", duration_minutes: 15 })), "AMRAP · 15 min");
  assert.equal(partFormat(part({ format: "for_time", rounds: 5 })), "For time · 5 rounds");
  assert.equal(partFormat(part({ format: "emom", interval_seconds: 60 })), "EMOM · every 60 s");
  assert.equal(partTarget(part({ target_seconds: 598 })), "Target 9'58");
  assert.equal(partTarget(part({ target_rounds: 5.5 })), "Target 5.5 rounds");
  assert.equal(partTarget(part({})), null);
  assert.equal(partResult(part({ result_seconds: 271 })), "Done in 4'31");
  assert.equal(partResult(part({ result_rounds: 0 })), "0 rounds");
  assert.equal(partResult(part({})), null);
});
