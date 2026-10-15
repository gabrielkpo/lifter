import { num } from "@/lib/format";

/** A small figure tile: value, unit, name; "–" when the value is missing. */
export default function Stat({
  value,
  unit,
  name,
  signed,
}: {
  value: number | null;
  unit?: string;
  name: string;
  /** Show a "+" on positive values (deltas). */
  signed?: boolean;
}) {
  const text = value === null ? "–" : `${signed && value > 0 ? "+" : ""}${num(value)}`;
  return (
    <div className="stat">
      <div className="value">
        {text}
        {value !== null && unit && <span className="small muted"> {unit}</span>}
      </div>
      <div className="name">{name}</div>
    </div>
  );
}
