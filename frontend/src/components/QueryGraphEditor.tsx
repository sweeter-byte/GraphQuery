import { useCallback, useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge as RFEdge,
  type OnConnect,
  type NodeMouseHandler,
  BackgroundVariant,
  MarkerType,
  Panel,
} from '@xyflow/react';
import { Play, Trash2, Plus, Tag } from 'lucide-react';
import type { QueryGraph, DatasetInfo } from '../types/api';

interface Props {
  dataset: DatasetInfo | null;
  onSubmit: (graph: QueryGraph) => void;
  disabled?: boolean;
}

let nodeIdCounter = 0;

export function QueryGraphEditor({ dataset, onSubmit, disabled }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<RFEdge>([]);
  const [editingNode, setEditingNode] = useState<string | null>(null);
  const [editingEdge, setEditingEdge] = useState<string | null>(null);
  const [labelInput, setLabelInput] = useState('');

  const onConnect: OnConnect = useCallback(
    (params) => {
      const newEdge: RFEdge = {
        ...params,
        id: `e-${params.source}-${params.target}`,
        label: '0',
        type: 'default',
        markerEnd: { type: MarkerType.ArrowClosed, color: '#6366f1' },
        style: { stroke: '#6366f1', strokeWidth: 2 },
      };
      setEdges((eds) => addEdge(newEdge, eds));
    },
    [setEdges],
  );

  const addNode = useCallback(() => {
    const id = `${nodeIdCounter++}`;
    const x = 100 + (nodes.length % 4) * 150;
    const y = 100 + Math.floor(nodes.length / 4) * 120;
    const newNode: Node = {
      id,
      position: { x, y },
      data: { label: `v${id} (0)`, vertexLabel: 0 },
      style: {
        background: '#312e81',
        color: '#e0e7ff',
        border: '2px solid #6366f1',
        borderRadius: '50%',
        width: 60,
        height: 60,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: '11px',
        fontWeight: 600,
      },
    };
    setNodes((nds) => [...nds, newNode]);
  }, [nodes.length, setNodes]);

  const clearGraph = useCallback(() => {
    setNodes([]);
    setEdges([]);
    nodeIdCounter = 0;
  }, [setNodes, setEdges]);

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
      onSubmit(queryGraph);
    }
  }, [queryGraph, dataset, onSubmit]);

  const canSubmit = queryGraph !== null && dataset !== null && dataset.index_status === 'ready' && !disabled;

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 p-3 border-b border-slate-700/50">
        <button
          onClick={addNode}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-600 hover:bg-indigo-500 text-white transition-colors"
        >
          <Plus className="w-3.5 h-3.5" /> Add Vertex
        </button>
        <button
          onClick={clearGraph}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" /> Clear
        </button>
        <div className="flex-1" />
        <span className="text-xs text-slate-400">
          {nodes.length}V / {edges.length}E
        </span>
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className={`flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold rounded-md transition-all ${
            canSubmit
              ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/25'
              : 'bg-slate-700/50 text-slate-500 cursor-not-allowed'
          }`}
        >
          <Play className="w-3.5 h-3.5" /> Submit Query
        </button>
      </div>

      {/* Label Editor Popup */}
      {(editingNode || editingEdge) && (
        <div className="absolute top-16 left-1/2 -translate-x-1/2 z-50 bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl flex items-center gap-2">
          <Tag className="w-4 h-4 text-indigo-400" />
          <span className="text-xs text-slate-300">
            {editingNode ? 'Vertex' : 'Edge'} Label:
          </span>
          <input
            type="number"
            value={labelInput}
            onChange={e => setLabelInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && commitLabel()}
            className="w-16 px-2 py-1 text-xs bg-slate-900 border border-slate-600 rounded text-white focus:outline-none focus:border-indigo-500"
            autoFocus
          />
          <button
            onClick={commitLabel}
            className="px-2 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 rounded text-white"
          >
            Set
          </button>
          <button
            onClick={() => { setEditingNode(null); setEditingEdge(null); }}
            className="px-2 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded text-slate-300"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Canvas */}
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeDoubleClick={onNodeDoubleClick}
          onEdgeDoubleClick={onEdgeDoubleClick}
          fitView
          defaultEdgeOptions={{
            style: { stroke: '#6366f1', strokeWidth: 2 },
            markerEnd: { type: MarkerType.ArrowClosed, color: '#6366f1' },
          }}
          style={{ background: '#0f172a' }}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#334155" />
          <Controls
            style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
          />
          <MiniMap
            style={{ background: '#1e293b', border: '1px solid #334155' }}
            nodeColor="#6366f1"
            maskColor="rgba(15, 23, 42, 0.7)"
          />
          {nodes.length === 0 && (
            <Panel position="top-center">
              <div className="text-sm text-slate-400 bg-slate-800/80 backdrop-blur px-4 py-2 rounded-lg border border-slate-700/50 mt-8">
                Click <strong>"Add Vertex"</strong> to start building your query graph.
                <br />
                <span className="text-xs text-slate-500">
                  Drag between nodes to create edges. Double-click to edit labels.
                </span>
              </div>
            </Panel>
          )}
        </ReactFlow>
      </div>
    </div>
  );
}
