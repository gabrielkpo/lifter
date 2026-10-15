import { num, shortDate } from "@/lib/format";

export type TimePoint = { day: string; value: number; note?: string };

/** One value over time, as a thin white line with a dot per day; dates spaced by time. */
export default function TimeChart({ points, unit }: { points: TimePoint[]; unit: string }) {
  if (points.length === 0) return null;
  const W = 320;
  const H = 120;
  const pad = { top: 14, right: 14, bottom: 22, left: 34 };
  const time = (day: string) => new Date(`${day}T00:00:00`).getTime();
  const t0 = time(points[0].day);
  const t1 = time(points[points.length - 1].day);
  const values = points.map((p) => p.value);
  const max = Math.max(...values);
  const low = Math.min(...values);
  const min = low - (max - low) * 0.25 - 1;
  const x = (day: string) =>
    pad.left + (t1 === t0 ? 0.5 : (time(day) - t0) / (t1 - t0)) * (W - pad.left - pad.right);
  const y = (v: number) => pad.top + (1 - (v - min) / (max - min || 1)) * (H - pad.top - pad.bottom);

  return (
    <svg className="timechart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Progression over time">
      <line x1={pad.left} x2={W - pad.right} y1={H - pad.bottom} y2={H - pad.bottom} stroke="var(--border)" />
      <text x={pad.left - 6} y={y(max) + 4} textAnchor="end" className="axis">
        {num(max)}
      </text>
      {low !== max && (
        <text x={pad.left - 6} y={y(low) + 4} textAnchor="end" className="axis">
          {num(low)}
        </text>
      )}
      <path
        d={`M${points.map((p) => `${x(p.day)},${y(p.value)}`).join("L")}`}
        fill="none"
        stroke="var(--text)"
        strokeWidth="2"
      />
      {points.map((p) => (
        <circle key={p.day} cx={x(p.day)} cy={y(p.value)} r="4" fill="var(--text)" stroke="var(--bg)" strokeWidth="2">
          <title>{`${shortDate(p.day)}: ${num(p.value)} ${unit}${p.note ? ` · ${p.note}` : ""}`}</title>
        </circle>
      ))}
      <text x={pad.left} y={H - 6} className="axis">
        {shortDate(points[0].day)}
      </text>
      {points.length > 1 && (
        <text x={W - pad.right} y={H - 6} textAnchor="end" className="axis">
          {shortDate(points[points.length - 1].day)}
        </text>
      )}
    </svg>
  );
}
