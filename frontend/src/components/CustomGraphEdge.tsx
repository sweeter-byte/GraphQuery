import { BaseEdge, getStraightPath, useInternalNode } from '@xyflow/react';
import type { EdgeProps } from '@xyflow/react';
import { getEdgeParams } from './utils';

// A custom edge that draws a straight line between two nodes' boundaries
// instead of their centers, creating a cleaner floating look.
export function CustomGraphEdge({
  id,
  source,
  target,
  style,
  markerEnd,
}: EdgeProps) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);

  if (!sourceNode || !targetNode) {
    return null;
  }

  const { sx, sy, tx, ty } = getEdgeParams(sourceNode, targetNode);

  // We use getStraightPath to draw a direct line between the calculated boundary intersections.
  const [edgePath] = getStraightPath({
    sourceX: sx,
    sourceY: sy,
    targetX: tx,
    targetY: ty,
  });

  return (
    <>
      <BaseEdge id={id} path={edgePath} style={style} markerEnd={markerEnd} />
    </>
  );
}
