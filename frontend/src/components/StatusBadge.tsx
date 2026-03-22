import { motion } from 'framer-motion';
import type { SessionStatus } from '../types/api';

const config: Record<SessionStatus, { bg: string; text: string; dot: string; label: string }> = {
  queued: { bg: 'bg-slate-700/50', text: 'text-slate-300', dot: 'bg-slate-400', label: 'Queued' },
  running: { bg: 'bg-blue-500/20', text: 'text-blue-300', dot: 'bg-blue-400', label: 'Running' },
  completed: { bg: 'bg-emerald-500/20', text: 'text-emerald-300', dot: 'bg-emerald-400', label: 'Completed' },
  failed: { bg: 'bg-red-500/20', text: 'text-red-300', dot: 'bg-red-400', label: 'Failed' },
};

export function StatusBadge({ status }: { status: SessionStatus }) {
  const c = config[status];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${c.bg} ${c.text}`}>
      {status === 'running' ? (
        <motion.span
          className={`w-2 h-2 rounded-full ${c.dot}`}
          animate={{ scale: [1, 1.3, 1], opacity: [1, 0.6, 1] }}
          transition={{ duration: 1.5, repeat: Infinity }}
        />
      ) : (
        <span className={`w-2 h-2 rounded-full ${c.dot}`} />
      )}
      {c.label}
    </span>
  );
}
