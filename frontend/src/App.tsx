import { useCallback, useState } from 'react';
import { ReactFlowProvider } from '@xyflow/react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, GitBranch } from 'lucide-react';

import { DatasetSelector } from './components/DatasetSelector';
import { QueryGraphEditor } from './components/QueryGraphEditor';
import { EvaluationDashboard } from './components/EvaluationDashboard';
import { useSessionStream } from './hooks/useSessionStream';
import { createSession } from './lib/api';
import type { DatasetInfo, QueryGraph } from './types/api';

function App() {
  const [selectedDataset, setSelectedDataset] = useState<DatasetInfo | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const stream = useSessionStream(sessionId);

  const handleSubmitQuery = useCallback(async (graph: QueryGraph) => {
    if (!selectedDataset) return;
    setSubmitting(true);
    try {
      const res = await createSession({
        dataset_id: selectedDataset.id,
        query_graph: graph,
      });
      setSessionId(res.session_id);
    } catch (e) {
      alert(`Failed to create session: ${e}`);
    } finally {
      setSubmitting(false);
    }
  }, [selectedDataset]);

  const handleNewSession = useCallback(() => {
    stream.close();
    setSessionId(null);
  }, [stream]);

  return (
    <div className="h-screen flex flex-col">
      {/* Top Bar */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-slate-700/50 bg-slate-900/80 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
            <GitBranch className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-white tracking-tight">GraphQuery</h1>
            <p className="text-[10px] text-slate-400">Query Plan Optimizer</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {sessionId && (
            <button
              onClick={handleNewSession}
              className="px-3 py-1.5 text-xs font-medium rounded-md bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors"
            >
              New Session
            </button>
          )}
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <Activity className="w-3.5 h-3.5" />
            <span>{sessionId ? 'Active' : 'Idle'}</span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        <aside className="w-64 border-r border-slate-700/50 bg-slate-900/50 p-4 overflow-y-auto flex-shrink-0">
          <DatasetSelector
            selected={selectedDataset}
            onSelect={setSelectedDataset}
          />

          {selectedDataset && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="mt-6 p-3 rounded-lg bg-slate-800/50 border border-slate-700/50"
            >
              <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                Selected Dataset
              </h4>
              <p className="text-sm font-medium text-white">{selectedDataset.name}</p>
              <div className="mt-2 space-y-1 text-xs text-slate-400">
                <div className="flex justify-between">
                  <span>Vertices</span>
                  <span className="text-slate-300">{selectedDataset.num_vertices.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span>Edges</span>
                  <span className="text-slate-300">{selectedDataset.num_edges.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span>Labels</span>
                  <span className="text-slate-300">{selectedDataset.labels.length}</span>
                </div>
                <div className="flex justify-between">
                  <span>Index</span>
                  <span className={
                    selectedDataset.index_status === 'ready'
                      ? 'text-emerald-400' : 'text-amber-400'
                  }>
                    {selectedDataset.index_status}
                  </span>
                </div>
              </div>
            </motion.div>
          )}
        </aside>

        {/* Graph Editor */}
        <main className="flex-1 flex flex-col relative min-w-0">
          <ReactFlowProvider>
            <QueryGraphEditor
              dataset={selectedDataset}
              onSubmit={handleSubmitQuery}
              disabled={submitting}
            />
          </ReactFlowProvider>
        </main>

        {/* Right Panel - Evaluation Dashboard */}
        <AnimatePresence>
          {sessionId && (
            <motion.aside
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 420, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 300, damping: 30 }}
              className="border-l border-slate-700/50 bg-slate-900/50 overflow-hidden flex-shrink-0"
            >
              <div className="w-[420px]">
                <EvaluationDashboard
                  sessionId={sessionId}
                  stream={stream}
                />
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

export default App;
