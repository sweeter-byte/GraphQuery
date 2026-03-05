import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Database, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import { fetchDatasets } from '../lib/api';
import type { DatasetInfo } from '../types/api';

interface Props {
  selected: DatasetInfo | null;
  onSelect: (ds: DatasetInfo) => void;
}

export function DatasetSelector({ selected, onSelect }: Props) {
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDatasets()
      .then(setDatasets)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-4 text-slate-400">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading datasets...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-red-400 text-sm">
        <AlertCircle className="w-4 h-4 inline mr-1" />
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 px-1">
        Datasets
      </h3>
      <AnimatePresence>
        {datasets.map(ds => {
          const isSelected = selected?.id === ds.id;
          const isReady = ds.index_status === 'ready';

          return (
            <motion.button
              key={ds.id}
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              onClick={() => onSelect(ds)}
              className={`w-full text-left p-3 rounded-lg border transition-all duration-200 ${
                isSelected
                  ? 'bg-indigo-500/20 border-indigo-500/50 shadow-lg shadow-indigo-500/10'
                  : 'bg-slate-800/50 border-slate-700/50 hover:bg-slate-700/50 hover:border-slate-600'
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <Database className="w-4 h-4 text-indigo-400" />
                <span className="font-medium text-sm">{ds.name}</span>
                {isReady ? (
                  <CheckCircle className="w-3.5 h-3.5 text-emerald-400 ml-auto" />
                ) : (
                  <AlertCircle className="w-3.5 h-3.5 text-amber-400 ml-auto" />
                )}
              </div>
              <div className="flex gap-4 text-xs text-slate-400 pl-6">
                <span>|V| = {ds.num_vertices.toLocaleString()}</span>
                <span>|E| = {ds.num_edges.toLocaleString()}</span>
              </div>
              {!isReady && (
                <div className="text-xs text-amber-400/80 pl-6 mt-1">
                  Index: {ds.index_status}
                </div>
              )}
            </motion.button>
          );
        })}
      </AnimatePresence>
      {datasets.length === 0 && (
        <p className="text-sm text-slate-500 px-1">No datasets found.</p>
      )}
    </div>
  );
}
