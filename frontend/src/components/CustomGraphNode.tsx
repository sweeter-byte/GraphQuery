import { Handle, Position } from '@xyflow/react';

// A custom node that provides a single, central handle allowing loose connections 
// from any angle, avoiding the rigid top/bottom wiring.
export function CustomGraphNode({ data, selected }: any) {
  const label = data.label || '0';
  const vertexLabel = data.vertexLabel || 0;
  
  // High-end styling based on selection state and vertex label
  const colorPalettes = [
    { base: 'from-amber-400 to-orange-500 text-white', shadow: 'shadow-orange-500/50', border: 'border-orange-200' },
    { base: 'from-emerald-400 to-teal-500 text-white', shadow: 'shadow-teal-500/50', border: 'border-teal-200' },
    { base: 'from-blue-400 to-indigo-500 text-white', shadow: 'shadow-indigo-500/50', border: 'border-indigo-200' },
    { base: 'from-rose-400 to-pink-500 text-white', shadow: 'shadow-rose-500/50', border: 'border-rose-200' },
    { base: 'from-purple-400 to-fuchsia-500 text-white', shadow: 'shadow-fuchsia-500/50', border: 'border-fuchsia-200' },
    { base: 'from-cyan-400 to-blue-500 text-white', shadow: 'shadow-cyan-500/50', border: 'border-cyan-200' },
  ];

  const palette = colorPalettes[vertexLabel % colorPalettes.length];

  const bgClass = selected
    ? `bg-gradient-to-br ${palette.base} shadow-[0_0_15px_rgba(255,255,255,0.6)] border-white ring-2 ring-white ring-offset-2 ring-offset-slate-900`
    : `bg-gradient-to-br ${palette.base} shadow-md ${palette.border} hover:shadow-lg hover:${palette.shadow}`;
    
  const textClass = 'text-white font-bold drop-shadow-md';

  const isDrawEdgeMode = data.isDrawEdgeMode || false;

  return (
    <div className="group relative flex items-center justify-center w-14 h-14">
      {/* 
        A single Universal Halo Handle.
        When isDrawEdgeMode is active, it becomes visible and connectable.
        Otherwise, it is completely disabled, allowing unimpeded node dragging.
      */}
      <Handle
        type="source"
        position={Position.Top}
        className={`!w-[84px] !h-[84px] !min-w-[84px] !min-h-[84px] !absolute !-top-[14px] !-left-[14px] !bg-transparent !border-[8px] !border-indigo-400/50 !rounded-full transition-all duration-300 ${
          isDrawEdgeMode ? 'opacity-100 cursor-crosshair hover:!border-indigo-400 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
        style={{ zIndex: isDrawEdgeMode ? 30 : 0, transform: 'none' }}
        isConnectable={isDrawEdgeMode}
      />
      
      {/* 
        A silent target handle to satisfy ReactFlow's internal edge routing without console warnings.
        It overlays the source handle but is completely invisible and sits at a lower z-index.
      */}
      <Handle
        type="target"
        position={Position.Bottom}
        className={`!w-[84px] !h-[84px] !min-w-[84px] !min-h-[84px] !absolute !-top-[14px] !-left-[14px] !bg-transparent !border-none !rounded-full opacity-0 ${isDrawEdgeMode ? 'pointer-events-auto' : 'pointer-events-none'}`}
        style={{ zIndex: isDrawEdgeMode ? 29 : -1, transform: 'none' }}
        isConnectable={isDrawEdgeMode}
      />

      {/* Main Node Visuals */}
      <div 
        className={`absolute inset-0 rounded-full border-2 transition-all duration-300 ${bgClass}`} 
        style={{ zIndex: 10 }} 
      />
      
      {/* Text Label */}
      <span className={`text-sm ${textClass} relative`} style={{ zIndex: 20 }}>
        {label}
      </span>
    </div>
  );
}
