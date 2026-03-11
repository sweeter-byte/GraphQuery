import { useState } from 'react';
import { motion } from 'framer-motion';
import { Zap, Turtle, Download } from 'lucide-react';
import { StatusBadge } from './StatusBadge';
import { ProgressBar } from './ProgressBar';
import { RankingLeaderboard } from './RankingLeaderboard';
import { LiveCharts } from './LiveCharts';
import { SubgraphFlowViewer } from './SubgraphFlowViewer';
import { executeSession } from '../lib/api';
import { frontendLogger as log } from '../lib/logger';
import type { StreamState } from '../hooks/useSessionStream';
import type { OrderRanking, QueryGraph } from '../types/api';

interface Props {
  sessionId: string;
  sourceGraph: QueryGraph | null;
  stream: StreamState & { setSlowMotion: (v: boolean) => void };
  language: 'en' | 'zh';
  theme: 'dark' | 'light';
}

export function EvaluationDashboard({ sessionId, sourceGraph, stream, language, theme }: Props) {
  const [slowMotion, setSlowMotionLocal] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [execResult, setExecResult] = useState<any>(null);
  const [selectedFlowRanking, setSelectedFlowRanking] = useState<OrderRanking | null>(null);

  const toggleSlowMotion = () => {
    const next = !slowMotion;
    setSlowMotionLocal(next);
    stream.setSlowMotion(next);
  };

  const handleExecute = async () => {
    setExecuting(true);
    setExecResult(null);
    log.info('EXECUTION', `Triggering DAF execution for session ${sessionId}`);
    try {
      const res = await executeSession(sessionId);
      log.info('EXECUTION', `DAF execution complete`, res.results);
      setExecResult(res.results);
    } catch (e) {
      log.error('EXECUTION', `DAF execution failed: ${e}`);
      alert(`Execution failed: ${e}`);
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-slate-50/50 dark:bg-transparent">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-300 dark:border-slate-700/50">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            {language === 'zh' ? '会话' : 'Session'}
          </h3>
          <code className="text-xs text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded">
            {sessionId}
          </code>
        </div>
        <div className="flex items-center gap-2">
          {/* Slow Motion Toggle */}
          <button
            onClick={toggleSlowMotion}
            title={language === 'zh' ? '慢动作回放' : 'Slow Motion Playback'}
            className={`flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded-md transition-all ${slowMotion
              ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40 shadow-sm shadow-amber-500/10'
              : 'bg-slate-200/50 dark:bg-slate-700/50 text-slate-500 dark:text-slate-400 border border-transparent hover:border-slate-400/30'
              }`}
          >
            <Turtle className="w-3 h-3" />
            {slowMotion ? (language === 'zh' ? '慢放 ON' : 'Slow ON') : (language === 'zh' ? '慢放' : 'Slow')}
          </button>
          <button
            onClick={() => log.downloadLogs()}
            title={language === 'zh' ? '下载前端日志' : 'Download Frontend Logs'}
            className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded-md bg-slate-200/50 dark:bg-slate-700/50 text-slate-500 dark:text-slate-400 border border-transparent hover:border-slate-400/30 transition-all"
          >
            <Download className="w-3 h-3" />
            {language === 'zh' ? '日志' : 'Logs'}
          </button>
          <StatusBadge status={stream.status} />
        </div>
      </div>

      <div className="flex-1 p-4 space-y-5 overflow-y-auto">
        {/* Progress */}
        <ProgressBar
          completed={stream.completedPrefixes}
          total={stream.totalPrefixes * (stream.totalOrders || 1)}
          label={language === 'zh' ? '前缀评估' : 'Prefix Evaluation'}
        />

        {/* Replaying indicator */}
        {stream.isReplaying && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex items-center gap-2 text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-md px-3 py-1.5"
          >
            <Turtle className="w-3.5 h-3.5 animate-pulse" />
            {language === 'zh' ? '慢动作回放中...' : 'Slow motion replaying...'}
          </motion.div>
        )}

        {/* Best Order Banner */}
        {stream.bestOrder && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-gradient-to-r from-indigo-100/50 to-purple-100/50 dark:from-indigo-900/40 dark:to-purple-900/40 border border-indigo-300/30 dark:border-indigo-500/30 rounded-lg p-3"
          >
            <div className="text-xs text-indigo-600 dark:text-indigo-300 font-medium mb-1">
              {language === 'zh' ? '最优排列' : 'Best Order'}
            </div>
            <div className="font-mono text-sm text-slate-800 dark:text-white">
              [{stream.bestOrder.order.join(', ')}]
            </div>
            <div className="text-xs text-indigo-500 dark:text-indigo-400 mt-1">
              {language === 'zh' ? '分数' : 'Score'}: {stream.bestOrder.score < 1000
                ? stream.bestOrder.score.toFixed(2)
                : stream.bestOrder.score.toExponential(3)}
            </div>
          </motion.div>
        )}

        {/* Error */}
        {stream.error && (
          <div className="bg-red-100/50 dark:bg-red-500/10 border border-red-400/30 dark:border-red-500/30 rounded-lg p-3 text-sm text-red-700 dark:text-red-300">
            {stream.error}
          </div>
        )}

        <RankingLeaderboard
          ranking={stream.ranking}
          bestOrderId={stream.bestOrder?.order_id ?? null}
          isCompleted={stream.status === 'completed'}
          activeOrderId={selectedFlowRanking?.order_id}
          onRowClick={(r) => setSelectedFlowRanking(r)}
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
              disabled={executing}
              className={`w-full flex items-center justify-center gap-2 py-3 rounded-lg text-white font-semibold text-sm shadow-lg transition-all ${executing
                  ? 'bg-slate-400 cursor-not-allowed'
                  : 'bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 dark:from-emerald-600 dark:to-teal-600 dark:hover:from-emerald-500 dark:hover:to-teal-500 shadow-emerald-600/20'
                }`}
            >
              <Zap className={`w-4 h-4 ${executing ? 'animate-pulse' : ''}`} />
              {executing
                ? (language === 'zh' ? '执行中...' : 'Executing...')
                : (language === 'zh' ? '执行下游引擎' : 'Execute on Downstream Engine')}
            </button>

            {/* Execution Result */}
            {execResult && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-4 bg-emerald-50/80 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800/50 rounded-lg p-4"
              >
                <h4 className="flex items-center gap-2 text-sm font-semibold text-emerald-800 dark:text-emerald-400 mb-3">
                  <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                  {language === 'zh' ? '执行查询成功' : 'Execution Successful'}
                </h4>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div className="bg-white dark:bg-slate-800/50 rounded-md p-2 border border-slate-100 dark:border-slate-700/50 shadow-sm">
                    <div className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
                      {language === 'zh' ? '匹配数量' : 'Matches'}
                    </div>
                    <div className="text-lg font-bold text-slate-700 dark:text-slate-200">
                      {execResult.results?.num_matches?.toLocaleString() || '0'}
                    </div>
                  </div>
                  <div className="bg-white dark:bg-slate-800/50 rounded-md p-2 border border-slate-100 dark:border-slate-700/50 shadow-sm">
                    <div className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
                      {language === 'zh' ? '总耗时' : 'Time (ms)'}
                    </div>
                    <div className="text-lg font-bold text-emerald-600 dark:text-emerald-400">
                      {execResult.results?.execution_time_ms?.toFixed(2) || '0.00'}
                    </div>
                  </div>
                  <div className="bg-white dark:bg-slate-800/50 rounded-md p-2 border border-slate-100 dark:border-slate-700/50 shadow-sm">
                    <div className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
                      {language === 'zh' ? '递归调用' : 'Rec. Calls'}
                    </div>
                    <div className="text-lg font-bold text-slate-700 dark:text-slate-200">
                      {execResult.results?.recursive_calls?.toLocaleString() || '0'}
                    </div>
                  </div>
                </div>
              </motion.div>
            )}
          </motion.div>
        )}
      </div>

      {/* Pop-up flow viewer when a leaderboard row is clicked */}
      <SubgraphFlowViewer 
         ranking={selectedFlowRanking}
         baseGraph={sourceGraph}
         prefixPoints={stream.prefixPoints}
         onClose={() => setSelectedFlowRanking(null)}
         language={language}
         theme={theme}
      />
    </div>
  );
}
