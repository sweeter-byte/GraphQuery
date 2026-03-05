// ── Graph Models ──
export interface Vertex {
  id: number;
  label: number;
}

export interface Edge {
  id?: number;
  source: number;
  target: number;
  label: number;
}

export interface QueryGraph {
  vertices: Vertex[];
  edges: Edge[];
}

// ── Dataset Models ──
export type IndexStatus = 'ready' | 'missing' | 'stale' | 'unknown';

export interface DatasetInfo {
  id: string;
  name: string;
  num_vertices: number;
  num_edges: number;
  labels: number[];
  index_status: IndexStatus;
  index_artifact_path: string;
  index_version: string;
  index_built_at: string;
}

// ── Session Models ──
export type SessionStatus = 'queued' | 'running' | 'completed' | 'failed';

export interface SessionCreateRequest {
  dataset_id: string;
  query_graph: QueryGraph;
  beam_width?: number | null;
}

export interface SessionCreateResponse {
  session_id: string;
  status: SessionStatus;
  stream_url: string;
}

export interface OrderRanking {
  rank: number;
  order_id: number;
  order: number[];
  score: number;
  prefix_index: number;
  total_prefixes: number;
}

// ── SSE Event Types ──
export interface SSEEventData {
  event: string;
  data: Record<string, unknown>;
}

export interface PrefixProgressData {
  order_id: number;
  order: number[];
  prefix_index: number;
  total_prefixes: number;
  estimated_cardinality: number;
  weight: number;
  accumulated_score: number;
}

export interface ScoreUpdatedData {
  order_id: number;
  score: number;
  prefix_index: number;
}

export interface RankingUpdatedData {
  top_k: OrderRanking[];
  total_orders: number;
}

export interface BatchUpdateData {
  events: SSEEventData[];
  count: number;
}

export interface BestOrderData {
  order_id: number;
  order: number[];
  score: number;
}

export interface SessionCompletedData {
  best_order_id: number;
  best_order: number[];
  best_score: number;
  total_orders: number;
}
