import { AnimatePresence, motion, LayoutGroup } from 'framer-motion';
import { Trophy, ArrowUp } from 'lucide-react';
import type { OrderRanking } from '../types/api';

interface Props {
  ranking: OrderRanking[];
  bestOrderId: number | null;
}

export function RankingLeaderboard({ ranking, bestOrderId }: Props) {
  if (ranking.length === 0) {
    return (
      <div className="text-center py-8 text-slate-500 text-sm">
        Waiting for ranking data...
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 mb-3">
        <Trophy className="w-4 h-4 text-amber-400" />
        <h4 className="text-sm font-semibold text-slate-200">Top-K Leaderboard</h4>
        <span className="text-xs text-slate-500 ml-auto">{ranking.length} orders</span>
      </div>

      <div className="grid grid-cols-[2rem_1fr_5rem_4rem] gap-x-2 text-xs text-slate-400 font-medium px-2 pb-1 border-b border-slate-700/50">
        <span>#</span>
        <span>Order</span>
        <span className="text-right">Score</span>
        <span className="text-right">Progress</span>
      </div>

      <LayoutGroup>
        <AnimatePresence mode="popLayout">
          {ranking.map((r) => {
            const isBest = r.order_id === bestOrderId;
            return (
              <motion.div
                key={r.order_id}
                layout
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 20 }}
                transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                className={`grid grid-cols-[2rem_1fr_5rem_4rem] gap-x-2 items-center px-2 py-1.5 rounded-md text-xs ${
                  isBest
                    ? 'bg-indigo-500/15 border border-indigo-500/30'
                    : r.rank <= 3
                      ? 'bg-slate-800/50'
                      : ''
                }`}
              >
                <span className={`font-bold ${
                  r.rank === 1 ? 'text-amber-400' :
                  r.rank === 2 ? 'text-slate-300' :
                  r.rank === 3 ? 'text-amber-600' :
                  'text-slate-500'
                }`}>
                  {r.rank}
                </span>
                <span className="font-mono text-slate-300 truncate" title={`[${r.order.join(', ')}]`}>
                  [{r.order.join(', ')}]
                </span>
                <span className="text-right font-mono text-slate-200">
                  {r.score < 1000 ? r.score.toFixed(1) : r.score.toExponential(2)}
                </span>
                <span className="text-right text-slate-400">
                  {r.prefix_index}/{r.total_prefixes}
                </span>
                {isBest && (
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    className="col-span-4 flex items-center gap-1 mt-1 text-indigo-400"
                  >
                    <ArrowUp className="w-3 h-3" />
                    <span className="text-[10px] font-medium">Current Best</span>
                  </motion.div>
                )}
              </motion.div>
            );
          })}
        </AnimatePresence>
      </LayoutGroup>
    </div>
  );
}
