import { Position, type Node } from '@xyflow/react';

// Returns the position (top/bottom/left/right) based on intersection angle
function getEdgePosition(node: Node, intersectionPoint: { x: number; y: number }) {
  const nx = Math.round((node as any).positionAbsolute?.x || node.position.x);
  const ny = Math.round((node as any).positionAbsolute?.y || node.position.y);
  const px = Math.round(intersectionPoint.x);
  const py = Math.round(intersectionPoint.y);

  if (px <= nx + 1) return Position.Left;
  if (px >= nx + (node.measured?.width ?? 0) - 1) return Position.Right;
  if (py <= ny + 1) return Position.Top;
  if (py >= ny + (node.measured?.height ?? 0) - 1) return Position.Bottom;

  return Position.Top;
}

// Calculates the intersection point between a line segment (from center to center)
// and the bounding box / circle of a node. We assume nodes are circular for 
// CustomNode (w=56, h=56) but fallback to rectangle.
function getNodeIntersection(intersectionNode: Node, targetNode: Node) {
  // Center of the intersection node
  const intersectionNodeWidth = intersectionNode.measured?.width || 56;
  const intersectionNodeHeight = intersectionNode.measured?.height || 56;
  const intersectionNodePosition = (intersectionNode as any).positionAbsolute || intersectionNode.position;
  const targetPosition = (targetNode as any).positionAbsolute || targetNode.position;
  const targetNodeWidth = targetNode.measured?.width || 56;
  const targetNodeHeight = targetNode.measured?.height || 56;

  const w = intersectionNodeWidth / 2;
  const h = intersectionNodeHeight / 2;

  const x2 = intersectionNodePosition.x + w;
  const y2 = intersectionNodePosition.y + h;
  const x1 = targetPosition.x + targetNodeWidth / 2;
  const y1 = targetPosition.y + targetNodeHeight / 2;

  const dx = x1 - x2;
  const dy = y1 - y2;
  const distance = Math.sqrt(dx * dx + dy * dy);

  if (distance === 0) return { x: x2, y: y2 };

  // For circular nodes, the intersection is exactly the radius away from the center
  // towards the other node.
  const radius = w; // assuming width roughly equals height
  const x = x2 + (dx / distance) * radius;
  const y = y2 + (dy / distance) * radius;

  return { x, y };
}

// Returns the point and position for the Edge starting at `node` pointing to `targetNode`
export function getEdgeParams(source: Node, target: Node) {
  const sourceIntersectionPoint = getNodeIntersection(source, target);
  const targetIntersectionPoint = getNodeIntersection(target, source);

  const sourcePos = getEdgePosition(source, sourceIntersectionPoint);
  const targetPos = getEdgePosition(target, targetIntersectionPoint);

  return {
    sx: sourceIntersectionPoint.x,
    sy: sourceIntersectionPoint.y,
    tx: targetIntersectionPoint.x,
    ty: targetIntersectionPoint.y,
    sourcePos,
    targetPos,
  };
}
