import type { Line, Part } from "./types";

/** "2026-03-02" as a local date, without the UTC shift of `new Date("2026-03-02")`. */
export function parseDay(day: string): Date {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function isoDay(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function addDays(day: string, days: number): string {
  const date = parseDay(day);
  date.setDate(date.getDate() + days);
  return isoDay(date);
}

export function today(): string {
  return isoDay(new Date());
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function weekday(day: string): string {
  return WEEKDAYS[parseDay(day).getDay()];
}

export function shortDate(day: string): string {
  const date = parseDay(day);
  return `${WEEKDAYS[date.getDay()]} ${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

export function num(x: number): string {
  return Number.isInteger(x) ? String(x) : String(Math.round(x * 100) / 100);
}

/** 754 -> 12'34 */
export function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}'${String(seconds % 60).padStart(2, "0")}`;
}

export function label(code: string): string {
  const text = code.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "4×8 @ 60–62.5 kg" from a line, without its exercise name. */
export function prescription(line: Line): string {
  const parts: string[] = [];
  if (line.quantity !== null) {
    const amount = num(line.quantity) + (line.unit === "reps" ? "" : ` ${line.unit}`);
    parts.push(line.sets ? `${line.sets}×${amount}` : amount);
  } else if (line.sets) {
    parts.push(`${line.sets} sets`);
  }
  if (line.load_kg !== null) {
    const range = line.load_kg_max !== null ? `–${num(line.load_kg_max)}` : "";
    parts.push(`@ ${num(line.load_kg)}${range} kg`);
  }
  return parts.join(" ");
}

/** The metcon header: "AMRAP 15 min · target 5 rounds". */
export function partFormat(part: Part): string {
  const bits = [
    part.format && (part.format === "amrap" || part.format === "emom" ? part.format.toUpperCase() : label(part.format)),
    part.duration_minutes && `${num(part.duration_minutes)} min`,
    part.rounds && `${part.rounds} rounds`,
    part.interval_seconds && `every ${part.interval_seconds} s`,
  ].filter(Boolean);
  return bits.join(" · ");
}

export function partTarget(part: Part): string | null {
  if (part.target_seconds) return `Target ${clock(part.target_seconds)}`;
  if (part.target_rounds) return `Target ${num(part.target_rounds)} rounds`;
  return null;
}

export function partResult(part: Part): string | null {
  if (part.result_seconds) return `Done in ${clock(part.result_seconds)}`;
  if (part.result_rounds !== null) return `${num(part.result_rounds)} rounds`;
  return null;
}
