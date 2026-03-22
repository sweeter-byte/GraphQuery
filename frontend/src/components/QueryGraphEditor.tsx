import { useCallback, useMemo, useState, useRef, useEffect } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Node,
  type Edge as RFEdge,
  type OnConnect,
  type NodeMouseHandler,
  ConnectionMode,
  BackgroundVariant,
  Panel,
} from '@xyflow/react';
import { Play, Trash2, Plus, Tag, Settings2, Cable, MousePointer2 } from 'lucide-react';
import type { QueryGraph, DatasetInfo, ScheduleConfig } from '../types/api';
import { CustomGraphNode } from './CustomGraphNode';
import { CustomGraphEdge } from './CustomGraphEdge';

const nodeTypes = {
  custom: CustomGraphNode,
};

const edgeTypes = {
  customEdge: CustomGraphEdge,
};

interface Props {
  dataset: DatasetInfo | null;
  onSubmit: (graph: QueryGraph, scheduleConfig?: ScheduleConfig) => void;
  disabled?: boolean;
  language: 'en' | 'zh';
  theme: 'dark' | 'light';
  bestOrder?: number[] | null;
}

function QueryGraphEditorInner({ dataset, onSubmit, disabled, language, theme, bestOrder }: Props) {
  const nodeIdCounter = useRef(0);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<RFEdge>([]);
  const [editingNode, setEditingNode] = useState<string | null>(null);
  const [editingEdge, setEditingEdge] = useState<string | null>(null);
  const [labelInput, setLabelInput] = useState('');
  const [animationStep, setAnimationStep] = useState(0);
  const [isDrawEdgeMode, setIsDrawEdgeMode] = useState(false);

  const { screenToFlowPosition } = useReactFlow();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  // Thread Configuration State
  const [useCustomSchedule, setUseCustomSchedule] = useState(false);
  const [pythonThreads, setPythonThreads] = useState(4);
  const totalCores = navigator.hardwareConcurrency || 8;
  const ompThreads = Math.max(1, Math.floor(totalCores / pythonThreads));

  // Trigger sequential growth animation when bestOrder changes
  useEffect(() => {
    if (!bestOrder || bestOrder.length === 0) {
      setAnimationStep(0);
      return;
    }

    // Start: dim everything, then reveal step by step
    setAnimationStep(0);
    let intervalId: ReturnType<typeof setInterval> | null = null;

    // Small initial delay so the dim state renders first
    const startTimer = setTimeout(() => {
      setAnimationStep(1);

      intervalId = setInterval(() => {
        setAnimationStep((prev) => {
          if (prev < bestOrder.length) return prev + 1;
          if (intervalId) clearInterval(intervalId);
          return prev;
        });
      }, 1200); // Longer delay for dramatic effect
    }, 400);

    return () => {
      clearTimeout(startTimer);
      if (intervalId) clearInterval(intervalId);
    };
  }, [bestOrder]);

  const onConnect: OnConnect = useCallback(
    (params) => {
      const newEdge: RFEdge = {
        ...params,
        id: `e-${params.source}-${params.target}`,
        label: '0',
        type: 'customEdge',
        style: { stroke: theme === 'dark' ? '#818cf8' : '#6366f1', strokeWidth: 3 },
      };
      setEdges((eds) => addEdge(newEdge, eds));
    },
    [setEdges, theme],
  );

  const addNode = useCallback(() => {
    const id = `${nodeIdCounter.current++}`;
    // Place new node near the visible center of the canvas
    const center = screenToFlowPosition({
      x: (reactFlowWrapper.current?.clientWidth ?? 600) / 2 + (reactFlowWrapper.current?.getBoundingClientRect().left ?? 0),
      y: (reactFlowWrapper.current?.clientHeight ?? 400) / 2 + (reactFlowWrapper.current?.getBoundingClientRect().top ?? 0),
    });
    // Offset slightly based on count so they don't stack
    const offset = nodes.length * 20;
    const x = center.x + (nodes.length % 3 - 1) * 100 + offset % 60;
    const y = center.y + Math.floor(nodes.length % 3) * 80;
    const newNode: Node = {
      id,
      position: { x, y },
      type: 'custom',
      data: { label: `v${id} (0)`, vertexLabel: 0 },
      className: 'graph-node',
      style: {
        width: 56,
      },
    };
    setNodes((nds) => [...nds, newNode]);
  }, [nodes.length, setNodes, screenToFlowPosition, theme]);

  const clearGraph = useCallback(() => {
    setNodes([]);
    setEdges([]);
    nodeIdCounter.current = 0;
  }, [setNodes, setEdges]);

  const onPaneClick = useCallback(
    (event: React.MouseEvent) => {
      if (event.detail === 2) {
        const id = `${nodeIdCounter.current++}`;
        const position = screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });

        const newNode: Node = {
          id,
          position,
          type: 'custom',
          data: { label: `v${id} (0)`, vertexLabel: 0 },
          className: 'graph-node',
          style: {
            width: 56,
          },
        };
        setNodes((nds) => [...nds, newNode]);
      }
    },
    [screenToFlowPosition, setNodes]
  );

  const deleteSelected = useCallback(() => {
    setNodes((nds) => nds.filter((n) => !n.selected));
    setEdges((eds) => eds.filter((e) => !e.selected));
  }, [setNodes, setEdges]);
  
  // React flow supports keyboard deletion via 'Delete' or 'Backspace'
  // But we need to ensure our internal UI 'deleteSelected' also removes selected edges correctly.

  const onNodeDoubleClick: NodeMouseHandler = useCallback((_event, node) => {
    setEditingNode(node.id);
    setLabelInput(String(node.data.vertexLabel ?? 0));
    setEditingEdge(null);
  }, []);

  const onEdgeDoubleClick = useCallback((_event: React.MouseEvent, edge: RFEdge) => {
    setEditingEdge(edge.id);
    setLabelInput(String(edge.label ?? 0));
    setEditingNode(null);
  }, []);

  const commitLabel = useCallback(() => {
    const val = parseInt(labelInput) || 0;
    if (editingNode) {
      setNodes(nds => nds.map(n =>
        n.id === editingNode
          ? { ...n, data: { ...n.data, label: `v${n.id} (${val})`, vertexLabel: val } }
          : n
      ));
      setEditingNode(null);
    }
    if (editingEdge) {
      setEdges(eds => eds.map(e =>
        e.id === editingEdge ? { ...e, label: String(val) } : e
      ));
      setEditingEdge(null);
    }
  }, [editingNode, editingEdge, labelInput, setNodes, setEdges]);

  const queryGraph = useMemo((): QueryGraph | null => {
    if (nodes.length === 0 || edges.length === 0) return null;
    return {
      vertices: nodes.map(n => ({
        id: parseInt(n.id),
        label: (n.data.vertexLabel as number) ?? 0,
      })),
      edges: edges.map(e => ({
        source: parseInt(e.source),
        target: parseInt(e.target),
        label: parseInt(String(e.label)) || 0,
      })),
    };
  }, [nodes, edges]);

  const handleSubmit = useCallback(() => {
    if (queryGraph && dataset) {
      const config: ScheduleConfig | undefined = useCustomSchedule 
        ? { mode: 'custom', python_threads: pythonThreads, omp_threads: ompThreads }
        : { mode: 'auto', python_threads: 4, omp_threads: 4 }; // Mode auto overrides backend

      onSubmit(queryGraph, useCustomSchedule ? config : undefined);
    }
  }, [queryGraph, dataset, onSubmit, useCustomSchedule, pythonThreads, ompThreads]);

  const canSubmit = queryGraph !== null && dataset !== null && dataset.index_status === 'ready' && !disabled;

  const t = {
    en: {
      addVertex: 'Add Vertex',
      deleteSelected: 'Delete Selected',
      clearAll: 'Clear All',
      submitQuery: 'Submit Query',
      emptyHintTitle: 'Click "Add Vertex" or double-click on the canvas to add nodes.',
      emptyHintSub: 'Drag between nodes to create edges. Double-click to edit labels.',
      vertexLabel: 'Vertex Label:',
      edgeLabel: 'Edge Label:',
      set: 'Set',
      cancel: 'Cancel',
      customSchedule: 'Custom Scheduling',
      pythonThreads: 'Python Max Threads:',
      ompThreads: 'OpenMP Cores/Task:',
      coresTotal: 'Total System Cores:',
      drawEdgeMode: 'Drawing Edges',
      moveNodeMode: 'Moving Nodes',
    },
    zh: {
      addVertex: '添加顶点',
      deleteSelected: '删除选中',
      clearAll: '清空画布',
      submitQuery: '提交查询',
      emptyHintTitle: '点击"添加顶点"或在空白处双击即可添加节点。',
      emptyHintSub: '在节点间拖拽即可连线。双击节点或边可修改标签。',
      vertexLabel: '顶点标签:',
      edgeLabel: '边标签:',
      set: '确认',
      cancel: '取消',
      customSchedule: '自定义调度',
      pythonThreads: 'Python 并发度 (Max):',
      ompThreads: 'OpenMP 核心/任务:',
      coresTotal: '系统总核心:',
      drawEdgeMode: '连线模式 (开启)',
      moveNodeMode: '普通移动模式',
    }
  };

  // ------------------------------------------------------------------
  // Compute the DISPLAYED nodes & edges: only show revealed elements.
  // This avoids opacity / hidden hacks that break ReactFlow rendering.
  // ------------------------------------------------------------------

  const revealedSet = useMemo(
    () => new Set(bestOrder ? bestOrder.slice(0, animationStep) : []),
    [bestOrder, animationStep],
  );

  const displayNodes: Node[] = useMemo(() => {
    // If no animation, show all nodes with isDrawEdgeMode injected
    if (!bestOrder || bestOrder.length === 0) {
      return nodes.map((n) => ({
        ...n,
        data: { ...n.data, isDrawEdgeMode },
      }));
    }
    // During animation step 0 (initial blank), show nothing
    if (animationStep === 0) return [];

    return nodes
      .filter((n) => revealedSet.has(parseInt(n.id)))
      .map((n) => ({
        ...n,
        data: {
          ...n.data,
          isDrawEdgeMode,
        },
        // Keep ReactFlow's internal dimensions IDENTICAL to original (60×60)
        // so edge connection points stay aligned.
        style: {
          ...n.style,
          // When active, we inject CSS variables or class override if needed,
          // but width/height match custom node constraints
          width: 56,
          height: 56,
          boxShadow:
            '0 0 24px rgba(251, 191, 36, 0.8), 0 0 48px rgba(251, 191, 36, 0.4)',
          transition: 'all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1)',
          // CRITICAL: Must be at the end to override any poisoned state
          opacity: 1,
          pointerEvents: 'auto',
        },
      }));
  }, [nodes, bestOrder, animationStep, revealedSet, theme, isDrawEdgeMode]);

  const displayEdges: RFEdge[] = useMemo(() => {
    if (!bestOrder || bestOrder.length === 0) return edges;
    if (animationStep === 0) return [];

    const glowStroke = '#fbbf24';

    return edges
      .filter(
        (e) =>
          revealedSet.has(parseInt(e.source)) &&
          revealedSet.has(parseInt(e.target)),
      )
      .map((e) => ({
        ...e,
        animated: true,
        style: {
          ...e.style,
          stroke: glowStroke,
          strokeWidth: 4,
          filter: 'drop-shadow(0 0 10px rgba(251, 191, 36, 0.7))',
          // CRITICAL: Must be at the end
          opacity: 1,
          pointerEvents: 'auto',
        },
      }));
  }, [edges, bestOrder, animationStep, revealedSet]);

  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-transparent">
      {/* Toolbar */}
      <div className="flex items-center gap-2 p-3 border-b border-slate-300 dark:border-slate-700/50">
        <button
          onClick={addNode}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-500 hover:bg-indigo-600 dark:bg-indigo-600 dark:hover:bg-indigo-500 text-white transition-colors"
        >
          <Plus className="w-3.5 h-3.5" /> {t[language].addVertex}
        </button>
        <button
          onClick={deleteSelected}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-red-100 hover:bg-red-200 text-red-700 dark:bg-red-900/40 dark:hover:bg-red-900/60 dark:text-red-300 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" /> {t[language].deleteSelected}
        </button>
        <button
          onClick={clearGraph}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-slate-200 hover:bg-slate-300 text-slate-700 dark:bg-slate-700 dark:hover:bg-slate-600 dark:text-slate-300 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" /> {t[language].clearAll}
        </button>
        <div className="h-4 border-l border-slate-300 dark:border-slate-700 mx-1"></div>
        <button
          onClick={() => setIsDrawEdgeMode(!isDrawEdgeMode)}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
            isDrawEdgeMode 
              ? 'bg-amber-500 hover:bg-amber-600 text-white shadow-inner shadow-amber-900/20' 
              : 'bg-slate-200 hover:bg-slate-300 text-slate-700 dark:bg-slate-700 dark:hover:bg-slate-600 dark:text-slate-300'
          }`}
        >
          {isDrawEdgeMode ? <Cable className="w-3.5 h-3.5" /> : <MousePointer2 className="w-3.5 h-3.5" />} 
          {isDrawEdgeMode ? t[language].drawEdgeMode : t[language].moveNodeMode}
        </button>
        <div className="flex-1 flex items-center justify-end pr-4">
          <div className="flex items-center gap-3">
            {/* Thread Configuration Area */}
            <div className="flex items-center gap-2 bg-slate-200/50 dark:bg-slate-800/50 rounded-md px-2 py-1">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input 
                  type="checkbox" 
                  checked={useCustomSchedule}
                  onChange={(e) => setUseCustomSchedule(e.target.checked)}
                  className="w-3.5 h-3.5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                />
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300 flex items-center gap-1">
                  <Settings2 className="w-3.5 h-3.5" />
                  {t[language].customSchedule}
                </span>
              </label>

              {useCustomSchedule && (
                <div className="flex items-center gap-2 border-l border-slate-300 dark:border-slate-700 pl-2 ml-1">
                  <div className="flex items-center gap-1" title={`${t[language].coresTotal} ${totalCores}`}>
                    <span className="text-[10px] text-slate-500">{t[language].pythonThreads}</span>
                    <input 
                      type="number" 
                      min="1" 
                      max={totalCores * 2}
                      value={pythonThreads}
                      onChange={(e) => setPythonThreads(Math.max(1, parseInt(e.target.value) || 1))}
                      className="w-12 h-6 px-1 text-xs bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-600 rounded"
                    />
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="text-[10px] text-slate-500">{t[language].ompThreads}</span>
                    <span className="text-xs font-medium text-amber-600 dark:text-amber-400 w-6 text-center">
                      {ompThreads}
                    </span>
                  </div>
                </div>
              )}
            </div>

            <span className="text-xs text-slate-500 dark:text-slate-400 font-medium whitespace-nowrap">
              {nodes.length}V / {edges.length}E
            </span>
          </div>
        </div>
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className={`flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold rounded-md transition-all ${canSubmit
            ? 'bg-emerald-500 hover:bg-emerald-600 dark:bg-emerald-600 dark:hover:bg-emerald-500 text-white shadow-lg shadow-emerald-500/25'
            : 'bg-slate-200 dark:bg-slate-700/50 text-slate-400 dark:text-slate-500 cursor-not-allowed'
            }`}
        >
          <Play className="w-3.5 h-3.5" /> {t[language].submitQuery}
        </button>
      </div>

      {/* Label Editor Popup */}
      {(editingNode || editingEdge) && (
        <div className="absolute top-16 left-1/2 -translate-x-1/2 z-50 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg p-3 shadow-xl flex items-center gap-2">
          <Tag className="w-4 h-4 text-indigo-500 dark:text-indigo-400" />
          <span className="text-xs font-medium text-slate-700 dark:text-slate-300">
            {editingNode ? t[language].vertexLabel : t[language].edgeLabel}
          </span>
          <input
            type="number"
            value={labelInput}
            onChange={e => setLabelInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && commitLabel()}
            className="w-16 px-2 py-1 text-xs bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-600 rounded text-slate-800 dark:text-white focus:outline-none focus:border-indigo-500"
            autoFocus
          />
          <button
            onClick={commitLabel}
            className="px-2 py-1 text-xs bg-indigo-500 hover:bg-indigo-600 dark:bg-indigo-600 dark:hover:bg-indigo-500 rounded text-white font-medium"
          >
            {t[language].set}
          </button>
          <button
            onClick={() => { setEditingNode(null); setEditingEdge(null); }}
            className="px-2 py-1 text-xs bg-slate-200 hover:bg-slate-300 text-slate-700 dark:bg-slate-700 dark:hover:bg-slate-600 rounded dark:text-slate-300 font-medium"
          >
            {t[language].cancel}
          </button>
        </div>
      )}

      {/* Canvas */}
      <div className="flex-1 relative" ref={reactFlowWrapper}>
        <ReactFlow
          nodes={displayNodes}
          edges={displayEdges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeDoubleClick={onNodeDoubleClick}
          onEdgeDoubleClick={onEdgeDoubleClick}
          onPaneClick={onPaneClick}
          nodesDraggable={!isDrawEdgeMode}
          fitView
          snapToGrid
          snapGrid={[20, 20]}

          connectionRadius={40}
          connectionMode={ConnectionMode.Loose}
          defaultEdgeOptions={{
            type: 'customEdge',
            style: { stroke: theme === 'dark' ? '#818cf8' : '#6366f1', strokeWidth: 3 },
            interactionWidth: 20, // Increases the clickable/selectable area of edges
            focusable: true,
            selectable: true,
          }}
          proOptions={{ hideAttribution: true }}
          style={{ background: theme === 'dark' ? '#0f172a' : '#f8fafc' }}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color={theme === 'dark' ? '#334155' : '#cbd5e1'} />
          <Controls
            style={{ background: theme === 'dark' ? '#1e293b' : '#ffffff', border: theme === 'dark' ? '1px solid #334155' : '1px solid #e2e8f0', borderRadius: '8px' }}
          />
          <MiniMap
            style={{ background: theme === 'dark' ? '#1e293b' : '#ffffff', border: theme === 'dark' ? '1px solid #334155' : '1px solid #e2e8f0' }}
            nodeColor={theme === 'dark' ? '#6366f1' : '#4f46e5'}
            maskColor={theme === 'dark' ? 'rgba(15, 23, 42, 0.7)' : 'rgba(248, 250, 252, 0.7)'}
          />
          {nodes.length === 0 && (
            <Panel position="top-center">
              <div className="text-sm text-slate-600 dark:text-slate-400 bg-white/80 dark:bg-slate-800/80 backdrop-blur px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-700/50 mt-8 shadow-sm">
                {t[language].emptyHintTitle}
                <br />
                <span className="text-xs text-slate-500">
                  {t[language].emptyHintSub}
                </span>
              </div>
            </Panel>
          )}
        </ReactFlow>
      </div>
    </div >
  );
}

// Wrap the component in ReactFlowProvider to use hooks like screenToFlowPosition
import { ReactFlowProvider } from '@xyflow/react';

export function QueryGraphEditor(props: Props) {
  return (
    <ReactFlowProvider>
      <QueryGraphEditorInner {...props} />
    </ReactFlowProvider>
  );
}
