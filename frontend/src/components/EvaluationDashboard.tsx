import { motion } from 'framer-motion';
import { Zap } from 'lucide-react';
import { StatusBadge } from './StatusBadge';
import { ProgressBar } from './ProgressBar';
import { RankingLeaderboard } from './RankingLeaderboard';
import { LiveCharts } from './LiveCharts';
import { executeSession } from '../lib/api';
import type { StreamState } from '../hooks/useSessionStream';

interface Props {
  sessionId: string;
  stream: StreamState;
}

export function EvaluationDashboard({ sessionId, stream }: Props) {
  const handleExecute = async () => {
    try {
      await executeSession(sessionId);
      alert('Execution triggered on downstream engine.');
    } catch (e) {
      alert(`Execution failed: ${e}`);
    }
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-700/50">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-slate-200">Session</h3>
          <code className="text-xs text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded">
            {sessionId}
          </code>
        </div>
        <StatusBadge status={stream.status} />
      </div>

      <div className="flex-1 p-4 space-y-5 overflow-y-auto">
        {/* Progress */}
        <ProgressBar
          completed={stream.completedPrefixes}
          total={stream.totalPrefixes * (stream.totalOrders || 1)}
        />

        {/* Best Order Banner */}
        {stream.bestOrder && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-gradient-to-r from-indigo-900/40 to-purple-900/40 border border-indigo-500/30 rounded-lg p-3"
          >
            <div className="text-xs text-indigo-300 font-medium mb-1">Best Order</div>
            <div className="font-mono text-sm text-white">
              [{stream.bestOrder.order.join(', ')}]
            </div>
            <div className="text-xs text-indigo-400 mt-1">
              Score: {stream.bestOrder.score < 1000
                ? stream.bestOrder.score.toFixed(2)
                : stream.bestOrder.score.toExponential(3)}
            </div>
          </motion.div>
        )}

        {/* Error */}
        {stream.error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm text-red-300">
            {stream.error}
          </div>
        )}

        {/* Ranking */}
        <RankingLeaderboard
          ranking={stream.ranking}
          bestOrderId={stream.bestOrder?.order_id ?? null}
        />

        {/* Charts */}
        <LiveCharts points={stream.prefixPoints} />

        {/* Execute Button */}
        {stream.status === 'completed' && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="pt-2"
          >
            <button
              onClick={handleExecute}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-semibold text-sm shadow-lg shadow-emerald-600/20 transition-all"
            >
              <Zap className="w-4 h-4" />
              Execute on Downstream Engine
            </button>
          </motion.div>
        )}
      </div>
    </div>
  );
}
