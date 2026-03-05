import { useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts';
import type { PrefixPoint } from '../hooks/useSessionStream';

interface Props {
  points: PrefixPoint[];
}

interface ChartPoint {
  prefix_index: number;
  [key: string]: number;
}

export function LiveCharts({ points }: Props) {
  // Group by order_id, aggregate per prefix_index
  const { cardinalityData, scoreData, orderIds } = useMemo(() => {
    const byOrder = new Map<number, PrefixPoint[]>();
    for (const p of points) {
      const arr = byOrder.get(p.order_id) || [];
      arr.push(p);
      byOrder.set(p.order_id, arr);
    }

    const ids = Array.from(byOrder.keys()).sort((a, b) => a - b);

    // Build cardinality chart data: x = prefix_index, lines per order_id
    const maxPrefixIdx = points.length > 0
      ? Math.max(...points.map(p => p.prefix_index))
      : 0;

    const cData: ChartPoint[] = [];
    const sData: ChartPoint[] = [];

    for (let k = 0; k <= maxPrefixIdx; k++) {
      const cPoint: ChartPoint = { prefix_index: k + 1 };
      const sPoint: ChartPoint = { prefix_index: k + 1 };
      for (const oid of ids) {
        const arr = byOrder.get(oid)!;
        const pt = arr.find(p => p.prefix_index === k);
        if (pt) {
          cPoint[`o${oid}`] = pt.estimated_cardinality;
          sPoint[`o${oid}`] = pt.accumulated_score;
        }
      }
      if (Object.keys(cPoint).length > 1) cData.push(cPoint);
      if (Object.keys(sPoint).length > 1) sData.push(sPoint);
    }

    return { cardinalityData: cData, scoreData: sData, orderIds: ids };
  }, [points]);

  const colors = [
    '#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6',
    '#06b6d4', '#f97316', '#ec4899', '#14b8a6', '#a855f7',
  ];

  // Show at most top 5 orders in charts to avoid clutter
  const visibleOrders = orderIds.slice(0, 5);

  if (points.length === 0) {
    return (
      <div className="text-center py-6 text-slate-500 text-sm">
        Charts will appear when prefix evaluation begins...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Chart A: Cardinality */}
      <div>
        <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
          Prefix Depth vs Est. Cardinality
        </h4>
        <div className="h-48 bg-slate-800/30 rounded-lg p-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={cardinalityData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis
                dataKey="prefix_index"
                stroke="#64748b"
                fontSize={10}
                label={{ value: 'k', position: 'insideBottomRight', offset: -5, style: { fill: '#64748b', fontSize: 10 } }}
              />
              <YAxis
                stroke="#64748b"
                fontSize={10}
                tickFormatter={v => v >= 1000 ? `${(v/1000).toFixed(0)}k` : String(v)}
                label={{ value: 'ĉₖ', angle: -90, position: 'insideLeft', style: { fill: '#64748b', fontSize: 10 } }}
              />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', fontSize: '11px' }}
                labelFormatter={v => `Prefix k=${v}`}
              />
              <Legend wrapperStyle={{ fontSize: '10px' }} />
              {visibleOrders.map((oid, i) => (
                <Line
                  key={oid}
                  type="monotone"
                  dataKey={`o${oid}`}
                  name={`Order ${oid}`}
                  stroke={colors[i % colors.length]}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Chart B: Score */}
      <div>
        <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
          Prefix Depth vs Accumulated Score
        </h4>
        <div className="h-48 bg-slate-800/30 rounded-lg p-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={scoreData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis
                dataKey="prefix_index"
                stroke="#64748b"
                fontSize={10}
                label={{ value: 'k', position: 'insideBottomRight', offset: -5, style: { fill: '#64748b', fontSize: 10 } }}
              />
              <YAxis
                stroke="#64748b"
                fontSize={10}
                tickFormatter={v => v >= 1000 ? `${(v/1000).toFixed(0)}k` : String(v)}
                label={{ value: 'Score', angle: -90, position: 'insideLeft', style: { fill: '#64748b', fontSize: 10 } }}
              />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', fontSize: '11px' }}
                labelFormatter={v => `Prefix k=${v}`}
              />
              <Legend wrapperStyle={{ fontSize: '10px' }} />
              {visibleOrders.map((oid, i) => (
                <Line
                  key={oid}
                  type="monotone"
                  dataKey={`o${oid}`}
                  name={`Order ${oid}`}
                  stroke={colors[i % colors.length]}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
