import { num } from "@/lib/format";

export type ChartWeek = { number: number; phase: string };

/**
 * One measure of one exercise, week by week: done as a solid white line, planned as a dashed
 * grey one (two inks plus a dash, so the pair never relies on colour). Deload weeks are shaded.
 */
export default function WeekChart({
  title,
  unit,
  weeks,
  done,
  planned,
  fromZero = true,
}: {
  title: string;
  /** Start the scale at 0 (counts); false fits it to the data (loads, where 0 kg says nothing). */
  fromZero?: boolean;
  unit?: string;
  weeks: ChartWeek[];
  done: (number | null)[];
  planned: (number | null)[];
}) {
  const W = 320;
  const H = 120;
  const pad = { top: 14, right: 12, bottom: 22, left: 30 };
  const values = [...done, ...planned].filter((v): v is number => v !== null);
  if (values.length === 0) return null;
  const max = Math.max(...values);
  const low = Math.min(...values);
  const min = fromZero ? Math.min(0, low) : low - (max - low) * 0.25 - 1;
  const span = max - min || 1;
  const x = (i: number) =>
    pad.left + (weeks.length === 1 ? 0.5 : i / (weeks.length - 1)) * (W - pad.left - pad.right);
  const y = (v: number) => pad.top + (1 - (v - min) / span) * (H - pad.top - pad.bottom);
  const step = weeks.length > 1 ? (W - pad.left - pad.right) / (weeks.length - 1) : 40;

  const path = (series: (number | null)[]) =>
    series
      .map((v, i) => (v === null ? null : `${x(i)},${y(v)}`))
      .reduce<string[][]>(
        (runs, point) => {
          if (point === null) runs.push([]);
          else runs[runs.length - 1].push(point);
          return runs;
        },
        [[]],
      )
      .filter((run) => run.length > 0)
      .map((run) => `M${run.join("L")}`)
      .join(" ");

  const last = done.findLastIndex((v) => v !== null);
  return (
    <figure className="chart">
      <figcaption className="row">
        <span>{title}</span>
        {last >= 0 && (
          <strong>
            {num(done[last]!)}
            {unit && <span className="muted small"> {unit}</span>}
          </strong>
        )}
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title} by week`}>
        {weeks.map((w, i) =>
          w.phase === "deload" ? (
            <rect
              key={`deload-${w.number}`}
              x={x(i) - step / 2}
              y={pad.top - 6}
              width={step}
              height={H - pad.top - pad.bottom + 6}
              fill="var(--surface-2)"
            />
          ) : null,
        )}
        <line x1={pad.left} x2={W - pad.right} y1={y(min)} y2={y(min)} stroke="var(--border)" />
        <text x={pad.left - 6} y={y(max) + 4} textAnchor="end" className="axis">
          {num(max)}
        </text>
        {!fromZero && (
          <text x={pad.left - 6} y={y(low) + 4} textAnchor="end" className="axis">
            {num(low)}
          </text>
        )}
        <path d={path(planned)} fill="none" stroke="var(--muted)" strokeWidth="2" strokeDasharray="4 4" />
        <path d={path(done)} fill="none" stroke="var(--text)" strokeWidth="2" />
        {done.map((v, i) =>
          v === null ? null : (
            <circle key={i} cx={x(i)} cy={y(v)} r="4" fill="var(--text)" stroke="var(--surface)" strokeWidth="2">
              <title>{`Week ${weeks[i].number}: ${num(v)}${unit ? ` ${unit}` : ""} done${
                planned[i] !== null ? `, ${num(planned[i]!)} planned` : ""
              }`}</title>
            </circle>
          ),
        )}
        {weeks.map((w, i) => (
          <text key={w.number} x={x(i)} y={H - 6} textAnchor="middle" className="axis">
            W{w.number}
          </text>
        ))}
      </svg>
    </figure>
  );
}
