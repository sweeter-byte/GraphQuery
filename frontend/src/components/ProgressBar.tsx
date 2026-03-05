import { motion } from 'framer-motion';

interface Props {
  completed: number;
  total: number;
}

export function ProgressBar({ completed, total }: Props) {
  const pct = total > 0 ? Math.min((completed / total) * 100, 100) : 0;

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-slate-400">
        <span>Prefix Evaluation</span>
        <span>{completed} / {total > 0 ? total : '?'}</span>
      </div>
      <div className="h-2 bg-slate-700/50 rounded-full overflow-hidden">
        <motion.div
          className="h-full rounded-full bg-gradient-to-r from-indigo-600 to-indigo-400"
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
        />
      </div>
    </div>
  );
}
