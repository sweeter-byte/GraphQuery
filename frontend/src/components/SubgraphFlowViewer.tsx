import { useMemo, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ReactFlow } from '@xyflow/react';
import { X, ArrowRight, Activity } from 'lucide-react';
import type { OrderRanking, QueryGraph } from '../types/api';
import type { PrefixPoint } from '../hooks/useSessionStream';
import { CustomGraphNode } from './CustomGraphNode';

const nodeTypes = {
  custom: CustomGraphNode,
};

interface Props {
  ranking: OrderRanking | null;
  baseGraph: QueryGraph | null;
  prefixPoints: PrefixPoint[];
  onClose: () => void;
  language: 'en' | 'zh';
  theme: 'dark' | 'light';
}

export function SubgraphFlowViewer({ ranking, baseGraph, prefixPoints, onClose, language, theme }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // We need to generate a series of mini-graphs based on the order
  const flowSteps = useMemo(() => {
    if (!ranking || !baseGraph) return [];
    
    const steps = [];
    const currentOrder: number[] = [];

    // Map vertex id to base layout properties
    // We try to reuse the positions if available, or just lay them out simply
    // Wait, the baseGraph doesn't have positions directly in this interface format,
    // so we will just arrange them in a small circle or grid for the mini view.
    const radius = 60;
    const center = { x: 90, y: 90 };

    for (let i = 0; i < ranking.order.length; i++) {
      const vid = ranking.order[i];
      currentOrder.push(vid);

      // Create nodes for this step
      const stepNodes = currentOrder.map((id, idx) => {
        const vData = baseGraph.vertices.find(v => v.id === id);
        const angle = (idx / currentOrder.length) * 2 * Math.PI;
        
        return {
          id: String(id),
          type: 'custom',
          position: {
            x: center.x + radius * Math.cos(angle) - 20, // offset half width
            y: center.y + radius * Math.sin(angle) - 20,
          },
          data: { 
             label: `v${id} (${vData?.label ?? 0})`,
             vertexLabel: vData?.label ?? 0
          },
          style: { width: 40, height: 40, fontSize: '10px' },
        };
      });

      // Create edges for this step
      const stepEdges = baseGraph.edges
        .filter(e => currentOrder.includes(e.source) && currentOrder.includes(e.target))
        .map(e => ({
          id: `e-${e.source}-${e.target}`,
          source: String(e.source),
          target: String(e.target),
          label: String(e.label),
          animated: true,
          style: { stroke: theme === 'dark' ? '#fbbf24' : '#f59e0b', strokeWidth: 2 },
        }));

      // In a real scenario with intermediate cardinality scores back from backend, we could attach them here.
      let currentCost: number | undefined = undefined;
      
      // The last step always matches the final score exactly.
      if (i === ranking.order.length - 1) {
        currentCost = ranking.score;
      } else {
        // Try to find the intermediate cost. Wait, backend prefix_index might be 0, 1, 2. 
        // We find the latest point for this prefix.
        // The backend prefix_index is generally the number of vertices - 2, or index in the loop. 
        // Best effort: just find the prefix point whose prefix_index matches `i` or `i+1`.
        // Let's search backward: find the exact prefix point matching this order_id and index `i`.
        // Actually, some backends use prefix_index = current depth. Let's try matching prefix_index === i + 1.
        const point = prefixPoints.find(p => p.order_id === ranking.order_id && p.prefix_index === i + 1)
                   || prefixPoints.find(p => p.order_id === ranking.order_id && p.prefix_index === i);
        if (point) {
          currentCost = point.accumulated_score;
        }
      }

      steps.push({
        step: i + 1,
        addedNode: vid,
        nodes: stepNodes,
        edges: stepEdges,
        // Show N/A if cost is not yet available, else show the cost.
        cost: currentCost
      });
    }
    return steps;
  }, [ranking, baseGraph, prefixPoints, theme]);

  if (!ranking || !baseGraph) return null;

  const handleWheel = (e: React.WheelEvent) => {
    // If scrolling vertically on a mouse, translate it to horizontal scrolling
    if (scrollRef.current && e.deltaY !== 0) {
      scrollRef.current.scrollLeft += e.deltaY;
    }
  };

  const t = {
    en: {
      title: 'Prefix Subgraph Evolution',
      close: 'Close',
      step: 'Step',
      cost: 'Cost:',
      finalCost: 'Final Cost:'
    },
    zh: {
      title: '前缀子图生长序列',
      close: '关闭',
      step: '第',
      stepSuffix: ' 步',
      cost: '当前代价:',
      finalCost: '总代价:'
    }
  };

  return (
    <AnimatePresence>
      {ranking && (
        <motion.div
           initial={{ opacity: 0, y: 50, scale: 0.95 }}
           animate={{ opacity: 1, y: 0, scale: 1 }}
           exit={{ opacity: 0, y: 50, scale: 0.95 }}
           transition={{ type: 'spring', damping: 25, stiffness: 200 }}
           className="absolute bottom-6 left-6 right-6 lg:left-1/2 lg:-translate-x-1/2 lg:w-max max-w-[95vw] bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl border border-white/40 dark:border-white/10 shadow-2xl z-50 p-5 rounded-2xl overflow-hidden"
        >
          <div className="flex items-center justify-between mb-5">
             <div className="flex items-center gap-3">
                <div className="p-2 bg-indigo-500/10 rounded-lg">
                  <Activity className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                </div>
                <h3 className="font-bold text-slate-800 dark:text-slate-100 text-lg">
                  {t[language].title}
                  <span className="ml-3 font-mono text-sm text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-500/10 border border-indigo-200 dark:border-indigo-500/20 px-2.5 py-1 rounded-md">
                    [{ranking.order.join(', ')}]
                  </span>
                </h3>
             </div>
             <button
               onClick={onClose}
               className="p-1.5 rounded-md hover:bg-slate-200 dark:hover:bg-slate-800 text-slate-500 transition-colors"
               title={t[language].close}
             >
               <X className="w-5 h-5" />
             </button>
          </div>

          <div 
            ref={scrollRef}
            onWheel={handleWheel}
            className="flex gap-4 overflow-x-auto pb-4 pt-2 px-2"
            style={{ scrollbarWidth: 'thin' }}
          >
             {flowSteps.map((stepData, idx) => (
                <div key={idx} className="flex items-center shrink-0">
                  <motion.div 
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.1 }}
                    className="flex flex-col gap-3 relative"
                  >
                    {/* Header stat */}
                    <div className="text-xs font-semibold text-slate-600 dark:text-slate-400 text-center flex items-center justify-center gap-1">
                       <span className="px-2 py-0.5 rounded-full bg-slate-200/50 dark:bg-slate-800/50">
                         {language === 'zh' ? `${t.zh.step} ${stepData.step} ${t.zh.stepSuffix}` : `${t.en.step} ${stepData.step}`}
                       </span>
                       {stepData.addedNode !== undefined && (
                          <span className="px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-500/20">+v{stepData.addedNode}</span>
                       )}
                    </div>
                    
                    {/* Mini Flow Canvas */}
                    <div className="w-[180px] h-[180px] rounded-2xl bg-gradient-to-b from-white/60 to-white/20 dark:from-slate-800/60 dark:to-slate-900/40 border border-white/50 dark:border-slate-700/50 shadow-[0_8px_30px_rgb(0,0,0,0.04)] dark:shadow-[0_8px_30px_rgba(0,0,0,0.12)] overflow-hidden relative group hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-colors">
                       <ReactFlow
                         nodes={stepData.nodes}
                         edges={stepData.edges}
                         nodeTypes={nodeTypes}
                         panOnDrag={false}
                         zoomOnScroll={false}
                         zoomOnDoubleClick={false}
                         proOptions={{ hideAttribution: true }}
                         style={{ background: 'transparent' }}
                       >
                       </ReactFlow>
                    </div>

                    {/* Footer Cost stat */}
                    <div className="text-[11px] text-center font-mono py-1.5 px-3 rounded-xl bg-slate-100/80 dark:bg-slate-800/80 border border-white/50 dark:border-slate-700/50 text-slate-600 dark:text-slate-300 shadow-sm backdrop-blur-sm">
                       {stepData.cost !== undefined 
                         ? <span className="text-amber-600 dark:text-amber-400 font-bold">{t[language].finalCost} {stepData.cost.toExponential(2)}</span>
                         : <span className="text-slate-400/80 italic">Intermediate</span>
                       }
                    </div>
                  </motion.div>

                  {idx < flowSteps.length - 1 && (
                     <div className="mx-5 text-slate-300 dark:text-slate-700">
                        <ArrowRight className="w-5 h-5" />
                     </div>
                  )}
                </div>
             ))}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
