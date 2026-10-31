// Dependency-free SVG sparkline. Colours come from CSS classes (no inline styles: CSP style-src 'self').
import type { MetricSeries } from '@/api/types';

const W = 220;
const H = 44;
const PAD = 3;

export function Sparkline({ series, label }: { series: MetricSeries; label?: string }) {
  const title = label ?? series.name;
  if (series.status !== 'ok' || series.points.length === 0) {
    return (
      <div className="spark spark-empty" data-status={series.status}>
        <div className="spark-title">{title}</div>
        <div className="muted">no data ({series.status}), not treated as zero</div>
      </div>
    );
  }
  const vs = series.points.map((p) => p.v);
  const min = Math.min(...vs);
  const max = Math.max(...vs);
  const span = max - min || 1;
  const n = series.points.length;
  const pts = series.points.map((p, i) => {
    const x = PAD + (n === 1 ? (W - 2 * PAD) / 2 : (i * (W - 2 * PAD)) / (n - 1));
    const y = H - PAD - ((p.v - min) / span) * (H - 2 * PAD);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = vs[n - 1] as number;
  const fmt = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(3).replace(/0+$/, '').replace(/\.$/, ''));
  return (
    <figure className="spark" data-testid={`spark-${series.name}`}>
      <figcaption className="spark-title">{title} <span className="muted">last {fmt(last)} · min {fmt(min)} · max {fmt(max)}</span></figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={`${title}: last ${fmt(last)}, min ${fmt(min)}, max ${fmt(max)}`}>
        <polyline className="spark-line" fill="none" points={pts.join(' ')} />
        <circle className="spark-dot" cx={pts[n - 1]?.split(',')[0]} cy={pts[n - 1]?.split(',')[1]} r="2.5" />
      </svg>
    </figure>
  );
}
