import { useCallback, useState, useEffect } from 'react';
import { ReactFlowProvider } from '@xyflow/react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, GitBranch, Sun, Moon, Languages, AlertTriangle, X } from 'lucide-react';

import { DatasetSelector } from './components/DatasetSelector';
import { QueryGraphEditor } from './components/QueryGraphEditor';
import { EvaluationDashboard } from './components/EvaluationDashboard';
import { useSessionStream } from './hooks/useSessionStream';
import { createSession } from './lib/api';
import type { DatasetInfo, QueryGraph, ScheduleConfig } from './types/api';

interface ErrorInfo {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

function parseApiError(e: unknown, language: 'en' | 'zh'): ErrorInfo {
  const raw = String(e);

  // Network-level error (backend unreachable)
  if (raw.includes('Failed to fetch') || raw.includes('NetworkError')) {
    return {
      code: 'NETWORK_ERROR',
      message: language === 'zh'
        ? '无法连接到后端服务器，请检查服务器是否正在运行。'
        : 'Cannot connect to backend server. Please check if the server is running.',
    };
  }

  // Try to parse structured error from backend
  const jsonMatch = raw.match(/\{[\s\S]*\}/);
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[0]);
      const err = parsed.error || parsed;
      const code = err.code || 'UNKNOWN';
      const details = err.details || {};

      const messages: Record<string, { en: string; zh: string }> = {
        DISCONNECTED_GRAPH: {
          en: `Query graph is not connected. Unreachable vertices: [${(details.unreachable_vertices || []).join(', ')}]. Please add edges or remove isolated vertices.`,
          zh: `查询图不连通，以下顶点无法到达: [${(details.unreachable_vertices || []).join(', ')}]。请添加边或删除孤立顶点。`,
        },
        SELF_LOOP: {
          en: `Self-loop detected at vertex ${details.vertex ?? '?'}. Please remove it.`,
          zh: `顶点 ${details.vertex ?? '?'} 存在自环，请删除。`,
        },
        INVALID_EDGE_ENDPOINT: {
          en: 'An edge references a non-existent vertex.',
          zh: '存在引用了不存在顶点的边。',
        },
        DUPLICATE_VERTEX_ID: {
          en: 'Duplicate vertex IDs found.',
          zh: '存在重复的顶点 ID。',
        },
      };

      const msg = messages[code];
      return {
        code,
        message: msg ? msg[language] : (err.message || raw),
        details,
      };
    } catch { /* fall through */ }
  }

  return { code: 'UNKNOWN', message: raw };
}

function App() {
  const [selectedDataset, setSelectedDataset] = useState<DatasetInfo | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [language, setLanguage] = useState<'en' | 'zh'>('en');
  const [errorInfo, setErrorInfo] = useState<ErrorInfo | null>(null);
  const [datasetKey, setDatasetKey] = useState(0);
  const [editorKey, setEditorKey] = useState(0);
  const [sourceGraph, setSourceGraph] = useState<QueryGraph | null>(null);

  // Apply dark mode class to html root
  useEffect(() => {
    if (theme === 'dark') document.documentElement.classList.add('dark');
    else document.documentElement.classList.remove('dark');
  }, [theme]);

  // Dictionary
  const t = {
    en: {
      title: 'GraphQuery',
      subtitle: 'Query Plan Optimizer',
      newSession: 'New Session',
      active: 'Active',
      idle: 'Idle',
      dataset: 'Selected Dataset',
      vertices: 'Vertices',
      edges: 'Edges',
      labels: 'Labels',
      index: 'Index',
    },
    zh: {
      title: 'GraphQuery',
      subtitle: '查询计划优化器',
      newSession: '新建会话',
      active: '执行中',
      idle: '空闲',
      dataset: '已选数据集',
      vertices: '顶点数',
      edges: '边数',
      labels: '标签种类',
      index: '索引状态',
    }
  };

  const stream = useSessionStream(sessionId);

  const handleSubmitQuery = useCallback(async (graph: QueryGraph, scheduleConfig?: ScheduleConfig) => {
    if (!selectedDataset) return;
    setSubmitting(true);
    setErrorInfo(null);
    try {
      const res = await createSession({
        dataset_id: selectedDataset.id,
        query_graph: graph,
        schedule_config: scheduleConfig,
      });
      setSessionId(res.session_id);
      setSourceGraph(graph);
    } catch (e) {
      setErrorInfo(parseApiError(e, language));
    } finally {
      setSubmitting(false);
    }
  }, [selectedDataset, language]);

  const handleNewSession = useCallback(() => {
    stream.close();
    setSessionId(null);
    setSourceGraph(null);
    setErrorInfo(null);
    setDatasetKey(k => k + 1); // force DatasetSelector to re-fetch
    setEditorKey(k => k + 1); // force QueryGraphEditor to clear
  }, [stream]);

  return (
    <div className={`h-screen flex flex-col ${theme}`}>
      {/* Top Bar */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-slate-300 dark:border-slate-700/50 bg-slate-100/80 dark:bg-slate-900/80 backdrop-blur-sm transition-colors">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
            <GitBranch className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-slate-800 dark:text-white tracking-tight">{t[language].title}</h1>
            <p className="text-[10px] text-slate-500 dark:text-slate-400">{t[language].subtitle}</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {/* Theme & Lang Toggles */}
          <div className="flex items-center gap-2 mr-2 border-r border-slate-300 dark:border-slate-700 pr-4">
            <button
              onClick={() => setLanguage(l => l === 'en' ? 'zh' : 'en')}
              className="p-1.5 text-slate-500 hover:text-indigo-600 dark:text-slate-400 dark:hover:text-indigo-400 hover:bg-slate-200 dark:hover:bg-slate-800 rounded-md transition-colors flex items-center gap-1"
              title="Toggle Language"
            >
              <Languages className="w-4 h-4" />
              <span className="text-xs font-bold">{language.toUpperCase()}</span>
            </button>
            <button
              onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
              className="p-1.5 text-slate-500 hover:text-amber-500 dark:text-slate-400 dark:hover:text-amber-400 hover:bg-slate-200 dark:hover:bg-slate-800 rounded-md transition-colors"
              title="Toggle Theme"
            >
              {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          </div>

          {sessionId && (
            <button
              onClick={handleNewSession}
              className="px-3 py-1.5 text-xs font-medium rounded-md bg-slate-200 hover:bg-slate-300 text-slate-700 dark:bg-slate-700 dark:hover:bg-slate-600 dark:text-slate-300 transition-colors"
            >
              {t[language].newSession}
            </button>
          )}
          <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
            <Activity className="w-3.5 h-3.5" />
            <span>{sessionId ? t[language].active : t[language].idle}</span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden bg-slate-50 dark:bg-[#0f172a]">
        {/* Sidebar */}
        <aside className="w-64 border-r border-slate-300 dark:border-slate-700/50 bg-slate-100/50 dark:bg-slate-900/50 p-4 overflow-y-auto flex-shrink-0">
          <DatasetSelector
            key={datasetKey}
            selected={selectedDataset}
            onSelect={setSelectedDataset}
            language={language}
          />

          {selectedDataset && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="mt-6 p-3 rounded-lg bg-white/50 dark:bg-slate-800/50 border border-slate-300 dark:border-slate-700/50 shadow-sm"
            >
              <h4 className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                {t[language].dataset}
              </h4>
              <p className="text-sm font-medium text-slate-800 dark:text-white">{selectedDataset.name}</p>
              <div className="mt-2 space-y-1 text-xs text-slate-500 dark:text-slate-400">
                <div className="flex justify-between">
                  <span>{t[language].vertices}</span>
                  <span className="text-slate-700 dark:text-slate-300">{selectedDataset.num_vertices.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span>{t[language].edges}</span>
                  <span className="text-slate-700 dark:text-slate-300">{selectedDataset.num_edges.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span>{t[language].labels}</span>
                  <span className="text-slate-700 dark:text-slate-300">{selectedDataset.labels.length}</span>
                </div>
                <div className="flex justify-between">
                  <span>{t[language].index}</span>
                  <span className={
                    selectedDataset.index_status === 'ready'
                      ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'
                  }>
                    {selectedDataset.index_status === 'ready' && language === 'zh' ? '就绪' :
                      selectedDataset.index_status === 'missing' && language === 'zh' ? '缺失' :
                        selectedDataset.index_status}
                  </span>
                </div>
              </div>
            </motion.div>
          )}
        </aside>

        {/* Graph Editor */}
        <main className="flex-1 flex flex-col relative min-w-0">
          {/* Error Banner */}
          <AnimatePresence>
            {errorInfo && (
              <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className={`mx-4 mt-3 flex items-start gap-3 p-3 rounded-lg border shadow-lg ${
                  errorInfo.code === 'NETWORK_ERROR'
                    ? 'bg-amber-50 dark:bg-amber-900/30 border-amber-300 dark:border-amber-600/50'
                    : 'bg-red-50 dark:bg-red-900/30 border-red-300 dark:border-red-600/50'
                }`}
              >
                <AlertTriangle className={`w-5 h-5 flex-shrink-0 mt-0.5 ${
                  errorInfo.code === 'NETWORK_ERROR'
                    ? 'text-amber-500'
                    : 'text-red-500'
                }`} />
                <div className="flex-1 min-w-0">
                  <p className={`text-sm font-medium ${
                    errorInfo.code === 'NETWORK_ERROR'
                      ? 'text-amber-800 dark:text-amber-200'
                      : 'text-red-800 dark:text-red-200'
                  }`}>
                    {errorInfo.message}
                  </p>
                  {errorInfo.code !== 'UNKNOWN' && errorInfo.code !== 'NETWORK_ERROR' && (
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 font-mono">
                      Code: {errorInfo.code}
                    </p>
                  )}
                </div>
                <button
                  onClick={() => setErrorInfo(null)}
                  className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </motion.div>
            )}
          </AnimatePresence>

          <ReactFlowProvider key={editorKey}>
            <QueryGraphEditor
              dataset={selectedDataset}
              onSubmit={handleSubmitQuery}
              disabled={submitting}
              language={language}
              theme={theme}
              bestOrder={stream.status === 'completed' ? stream.bestOrder?.order : null}
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
              className="border-l border-slate-300 dark:border-slate-700/50 bg-slate-100/50 dark:bg-slate-900/50 overflow-hidden flex-shrink-0"
            >
              <div className="w-[420px] h-full flex flex-col">
                <EvaluationDashboard
                  sessionId={sessionId}
                  sourceGraph={sourceGraph}
                  stream={stream}
                  language={language}
                  theme={theme}
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
