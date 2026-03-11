import { motion, useSpring, useTransform } from 'framer-motion';
import { useEffect } from 'react';

interface Props {
  completed: number;
  total: number;
  label?: string;
}

export function ProgressBar({ completed, total, label }: Props) {
  const pct = total > 0 ? Math.min((completed / total) * 100, 100) : 0;

  // useSpring for smooth animated interpolation even when data arrives in bursts
  const springPct = useSpring(0, { stiffness: 80, damping: 20 });

  useEffect(() => {
    springPct.set(pct);
  }, [pct, springPct]);

  const width = useTransform(springPct, (v) => `${v}%`);

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-slate-500 dark:text-slate-400">
        <span>{label ?? 'Prefix Evaluation'}</span>
        <span>{completed} / {total > 0 ? total : '?'}</span>
      </div>
      <div className="h-2 bg-slate-300/50 dark:bg-slate-700/50 rounded-full overflow-hidden">
        <motion.div
          className="h-full rounded-full bg-gradient-to-r from-indigo-600 to-indigo-400"
          style={{ width }}
        />
      </div>
    </div>
  );
}
