import { useCallback, useEffect, useRef, useState } from 'react';
import { getStreamUrl } from '../lib/api';
import type {
  BatchUpdateData,
  BestOrderData,
  OrderRanking,
  PrefixProgressData,
  RankingUpdatedData,
  SessionCompletedData,
  SessionStatus,
} from '../types/api';

export interface PrefixPoint {
  order_id: number;
  prefix_index: number;
  estimated_cardinality: number;
  accumulated_score: number;
}

export interface StreamState {
  status: SessionStatus;
  ranking: OrderRanking[];
  totalOrders: number;
  prefixPoints: PrefixPoint[];
  bestOrder: BestOrderData | null;
  completedData: SessionCompletedData | null;
  error: string | null;
  completedPrefixes: number;
  totalPrefixes: number;
}

const initialState: StreamState = {
  status: 'queued',
  ranking: [],
  totalOrders: 0,
  prefixPoints: [],
  bestOrder: null,
  completedData: null,
  error: null,
  completedPrefixes: 0,
  totalPrefixes: 0,
};

export function useSessionStream(sessionId: string | null) {
  const [state, setState] = useState<StreamState>(initialState);
  const esRef = useRef<EventSource | null>(null);

  const processEvent = useCallback((eventType: string, data: Record<string, unknown>) => {
    switch (eventType) {
      case 'session_started':
        setState(prev => ({ ...prev, status: 'running' }));
        break;

      case 'prefix_progress': {
        const d = data as unknown as PrefixProgressData;
        setState(prev => ({
          ...prev,
          prefixPoints: [...prev.prefixPoints, {
            order_id: d.order_id,
            prefix_index: d.prefix_index,
            estimated_cardinality: d.estimated_cardinality,
            accumulated_score: d.accumulated_score,
          }],
          completedPrefixes: prev.completedPrefixes + 1,
          totalPrefixes: Math.max(prev.totalPrefixes, d.total_prefixes),
        }));
        break;
      }

      case 'score_updated': {
        // Score updates are folded into prefix_progress already
        break;
      }

      case 'ranking_updated': {
        const d = data as unknown as RankingUpdatedData;
        setState(prev => ({
          ...prev,
          ranking: d.top_k,
          totalOrders: d.total_orders,
        }));
        break;
      }

      case 'best_order_selected': {
        const d = data as unknown as BestOrderData;
        setState(prev => ({ ...prev, bestOrder: d }));
        break;
      }

      case 'order_generated': {
        setState(prev => ({
          ...prev,
          totalOrders: prev.totalOrders + 1,
        }));
        break;
      }

      case 'session_completed': {
        const d = data as unknown as SessionCompletedData;
        setState(prev => ({
          ...prev,
          status: 'completed',
          completedData: d,
          bestOrder: {
            order_id: d.best_order_id,
            order: d.best_order,
            score: d.best_score,
          },
        }));
        break;
      }

      case 'session_failed': {
        setState(prev => ({
          ...prev,
          status: 'failed',
          error: (data as { message?: string }).message || 'Session failed',
        }));
        break;
      }

      case 'batch_update': {
        const batch = data as unknown as BatchUpdateData;
        // Process all events in a single setState to avoid multi-render stuttering
        setState(prev => {
          let next = { ...prev };
          const newPoints: PrefixPoint[] = [...prev.prefixPoints];
          let completed = prev.completedPrefixes;

          for (const evt of batch.events) {
            switch (evt.event) {
              case 'prefix_progress': {
                const d = evt.data as unknown as PrefixProgressData;
                newPoints.push({
                  order_id: d.order_id,
                  prefix_index: d.prefix_index,
                  estimated_cardinality: d.estimated_cardinality,
                  accumulated_score: d.accumulated_score,
                });
                completed++;
                next.totalPrefixes = Math.max(next.totalPrefixes, d.total_prefixes);
                break;
              }
              case 'ranking_updated': {
                const d = evt.data as unknown as RankingUpdatedData;
                next.ranking = d.top_k;
                next.totalOrders = d.total_orders;
                break;
              }
              case 'score_updated':
                break;
            }
          }

          next.prefixPoints = newPoints;
          next.completedPrefixes = completed;
          return next;
        });
        break;
      }
    }
  }, []);

  useEffect(() => {
    if (!sessionId) {
      setState(initialState);
      return;
    }

    setState(initialState);
    const es = new EventSource(getStreamUrl(sessionId));
    esRef.current = es;

    const handleEvent = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        processEvent(e.type, data);
      } catch {
        // ignore parse errors
      }
    };

    // Listen for all known event types
    const eventTypes = [
      'session_started', 'index_loading', 'index_loaded',
      'order_generated', 'prefix_progress', 'score_updated',
      'ranking_updated', 'best_order_selected',
      'session_completed', 'session_failed', 'batch_update',
    ];

    for (const type of eventTypes) {
      es.addEventListener(type, handleEvent);
    }

    // Also listen to generic messages
    es.onmessage = handleEvent;

    es.onerror = () => {
      // EventSource will auto-reconnect; if state is terminal, close
      setState(prev => {
        if (prev.status === 'completed' || prev.status === 'failed') {
          es.close();
        }
        return prev;
      });
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [sessionId, processEvent]);

  const close = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
  }, []);

  return { ...state, close };
}
