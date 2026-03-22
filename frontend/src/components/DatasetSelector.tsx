import { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Database, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import { fetchDatasets } from '../lib/api';
import type { DatasetInfo } from '../types/api';

// New API call for preloading
export async function preloadDatasetIndex(datasetId: string): Promise<void> {
  const params = new URLSearchParams({ dataset_id: datasetId });
  const response = await fetch(`/api/datasets/load?${params.toString()}`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error(`Failed to load index: ${response.statusText}`);
  }
}

interface Props {
  selected: DatasetInfo | null;
  onSelect: (ds: DatasetInfo) => void;
  language: 'en' | 'zh';
}

export function DatasetSelector({ selected, onSelect, language }: Props) {
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDatasets = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchDatasets()
      .then(setDatasets)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadDatasets();
  }, [loadDatasets]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-4 text-slate-500 dark:text-slate-400">
        <Loader2 className="w-4 h-4 animate-spin" />
        {language === 'zh' ? '正在加载数据集...' : 'Loading datasets...'}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 space-y-2">
        <div className="text-red-400 text-sm">
          <AlertCircle className="w-4 h-4 inline mr-1" />
          {language === 'zh' ? '加载数据集失败' : 'Failed to load datasets'}
        </div>
        <button
          onClick={loadDatasets}
          className="w-full text-xs font-medium py-1.5 rounded-md bg-indigo-500/20 text-indigo-400 hover:bg-indigo-500/30 border border-indigo-500/30 transition-colors"
        >
          {language === 'zh' ? '🔄 点击重试' : '🔄 Retry'}
        </button>
      </div>
    );
  }

  const t = {
    en: {
      datasets: 'Datasets',
      loading: 'Loading datasets...',
      none: 'No datasets found.',
      vertices: '|V| = ',
      edges: '|E| = ',
      index: 'Index: ',
      ready: 'ready',
      missing: 'missing'
    },
    zh: {
      datasets: '数据集列表',
      loading: '正在加载数据集...',
      none: '未找到数据集',
      vertices: '点数 = ',
      edges: '边数 = ',
      index: '索引: ',
      ready: '就绪',
      missing: '缺失'
    }
  };

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 px-1">
        {t[language].datasets}
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
              onClick={() => {
                onSelect(ds);
                // Background preload
                if (ds.index_status === 'ready') {
                  preloadDatasetIndex(ds.id).catch(err => console.error("Preload error:", err));
                }
              }}
              className={`w-full text-left p-3 rounded-lg border transition-all duration-200 ${isSelected
                  ? 'bg-indigo-100/50 border-indigo-400/50 dark:bg-indigo-500/20 dark:border-indigo-500/50 shadow-lg shadow-indigo-500/10'
                  : 'bg-white/50 border-slate-300 hover:bg-slate-50/50 hover:border-slate-400 dark:bg-slate-800/50 dark:border-slate-700/50 dark:hover:bg-slate-700/50 dark:hover:border-slate-600'
                }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <Database className="w-4 h-4 text-indigo-500 dark:text-indigo-400" />
                <span className="font-medium text-sm text-slate-800 dark:text-slate-200">{ds.name}</span>
                {isReady ? (
                  <CheckCircle className="w-3.5 h-3.5 text-emerald-400 ml-auto" />
                ) : (
                  <AlertCircle className="w-3.5 h-3.5 text-amber-400 ml-auto" />
                )}
              </div>
              <div className="flex gap-4 text-xs text-slate-600 dark:text-slate-400 pl-6">
                <span>{t[language].vertices}{ds.num_vertices.toLocaleString()}</span>
                <span>{t[language].edges}{ds.num_edges.toLocaleString()}</span>
              </div>
              {!isReady && (
                <div className="text-xs text-amber-600/80 dark:text-amber-400/80 pl-6 mt-1">
                  {t[language].index}{t[language].missing}
                </div>
              )}
            </motion.button>
          );
        })}
      </AnimatePresence>
      {datasets.length === 0 && (
        <p className="text-sm text-slate-500 px-1">{t[language].none}</p>
      )}
    </div>
  );
}
