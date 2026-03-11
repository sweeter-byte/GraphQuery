import { useEffect, useState, useRef } from 'react';
import { AnimatePresence, motion, LayoutGroup } from 'framer-motion';
import { Trophy, ArrowUp } from 'lucide-react';
import type { OrderRanking } from '../types/api';

interface Props {
  ranking: OrderRanking[];
  bestOrderId: number | null;
  isCompleted?: boolean;
  activeOrderId?: number | null;
  onRowClick?: (ranking: OrderRanking) => void;
}

export function RankingLeaderboard({ ranking, bestOrderId, isCompleted, activeOrderId, onRowClick }: Props) {
  // Throttle updates to avoid "phantom" jitter in the UI when SSE stream pushes rapidly
  const [displayedRanking, setDisplayedRanking] = useState<OrderRanking[]>(ranking);
  const lastUpdateTime = useRef<number>(0);
  const updateTimeout = useRef<number | null>(null);

  useEffect(() => {
    // If completed, show final result immediately
    if (isCompleted || ranking.length === 0) {
      setDisplayedRanking(ranking);
      if (updateTimeout.current) clearTimeout(updateTimeout.current);
      return;
    }

    const now = Date.now();
    const timeSinceLastUpdate = now - lastUpdateTime.current;
    
    // Throttle rate: update UI at most once every 300ms
    if (timeSinceLastUpdate > 300) {
      setDisplayedRanking(ranking);
      lastUpdateTime.current = now;
      if (updateTimeout.current) clearTimeout(updateTimeout.current);
    } else {
      // Schedule an update for the end of the throttle window
      if (updateTimeout.current) clearTimeout(updateTimeout.current);
      updateTimeout.current = window.setTimeout(() => {
        setDisplayedRanking(ranking);
        lastUpdateTime.current = Date.now();
      }, 300 - timeSinceLastUpdate);
    }

    return () => {
      if (updateTimeout.current) clearTimeout(updateTimeout.current);
    };
  }, [ranking, isCompleted]);

  if (displayedRanking.length === 0) {
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
        <span className="text-xs text-slate-500 ml-auto">{displayedRanking.length} orders</span>
      </div>

      <div className="grid grid-cols-[2rem_1fr_5rem_4rem] gap-x-2 text-xs text-slate-400 font-medium px-2 pb-1 border-b border-slate-700/50">
        <span>#</span>
        <span>Order</span>
        <span className="text-right">Score</span>
        <span className="text-right">Progress</span>
      </div>

      <LayoutGroup>
        <AnimatePresence mode="popLayout">
          {displayedRanking.map((r, idx) => {
            const isBest = r.order_id === bestOrderId;
            return (
              <motion.div
                key={r.order_id}
                layoutId={`leaderboard-row-${r.order_id}`}
                layout="position"
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 20 }}
                transition={{
                  layout: {
                    type: 'spring',
                    stiffness: 200,
                    damping: 25,
                    // Stagger: rows lower in the list animate slightly later
                    delay: idx * 0.03,
                  },
                  opacity: { duration: 0.2 },
                }}
                onClick={() => onRowClick?.(r)}
                className={`grid grid-cols-[2rem_1fr_5rem_4rem] gap-x-2 items-center px-2 py-1.5 rounded-md text-xs relative cursor-pointer group transition-all duration-300 ${
                  r.order_id === activeOrderId 
                    ? 'bg-indigo-500/20 shadow-[0_0_15px_rgba(99,102,241,0.4)] border border-indigo-400/60 ring-1 ring-indigo-400 z-20 scale-[1.02]' 
                    : isCompleted && isBest
                    ? 'bg-gradient-to-r from-amber-500/20 to-yellow-500/20 border border-amber-400/80 shadow-[0_0_15px_rgba(251,191,36,0.3)] z-10'
                    : isBest
                      ? 'bg-indigo-500/15 border border-indigo-500/30'
                      : r.rank <= 3
                        ? 'bg-slate-800/50 hover:bg-slate-700/50'
                        : 'hover:bg-slate-800/30'
                  }`}
              >
                <span className={`font-bold ${(isCompleted && isBest) || r.rank === 1 ? 'text-amber-400' :
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
                    className={`col-span-4 flex items-center gap-1 mt-1 ${isCompleted ? 'text-amber-400 font-bold' : 'text-indigo-400'}`}
                  >
                    {isCompleted ? <Trophy className="w-3.5 h-3.5 animate-pulse" /> : <ArrowUp className="w-3 h-3" />}
                    <span className="text-[10px] font-medium">{isCompleted ? 'Final Winner' : 'Current Best'}</span>
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
