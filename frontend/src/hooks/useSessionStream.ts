import { useCallback, useEffect, useRef, useState } from 'react';
import { getStreamUrl } from '../lib/api';
import { frontendLogger as log } from '../lib/logger';
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
  /** True when slow motion playback is still draining its buffer */
  isReplaying: boolean;
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
  isReplaying: false,
};

/** Buffered snapshot for slow motion playback */
interface BufferedSnapshot {
  ranking: OrderRanking[];
  totalOrders: number;
  bestOrder: BestOrderData | null;
}

const SLOW_MOTION_DELAY_MS = 350;

export function useSessionStream(sessionId: string | null) {
  const [state, setState] = useState<StreamState>(initialState);
  const esRef = useRef<EventSource | null>(null);
  const slowMotionRef = useRef(false);

  // Buffer for slow motion playback — stores ranking snapshots
  const snapshotBufferRef = useRef<BufferedSnapshot[]>([]);
  const replayTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Drain one snapshot from the buffer at a time
  const drainNextSnapshot = useCallback(() => {
    const buffer = snapshotBufferRef.current;
    if (buffer.length === 0) {
      setState(prev => ({ ...prev, isReplaying: false }));
      return;
    }

    const snap = buffer.shift()!;
    setState(prev => ({
      ...prev,
      ranking: snap.ranking,
      totalOrders: snap.totalOrders,
      bestOrder: snap.bestOrder ?? prev.bestOrder,
      isReplaying: buffer.length > 0,
    }));

    if (buffer.length > 0) {
      replayTimerRef.current = setTimeout(drainNextSnapshot, SLOW_MOTION_DELAY_MS);
    }
  }, []);

  const processEvent = useCallback((eventType: string, data: Record<string, unknown>) => {
    switch (eventType) {
      case 'session_started':
        log.info('SSE', 'Session started');
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
        if (slowMotionRef.current) {
          // Buffer the snapshot for slow playback
          snapshotBufferRef.current.push({
            ranking: d.top_k,
            totalOrders: d.total_orders,
            bestOrder: null,
          });
          // Start draining if not already running
          if (!replayTimerRef.current || snapshotBufferRef.current.length === 1) {
            setState(prev => ({ ...prev, isReplaying: true }));
            replayTimerRef.current = setTimeout(drainNextSnapshot, SLOW_MOTION_DELAY_MS);
          }
        } else {
          setState(prev => ({
            ...prev,
            ranking: d.top_k,
            totalOrders: d.total_orders,
          }));
        }
        break;
      }

      case 'best_order_selected': {
        const d = data as unknown as BestOrderData;
        if (slowMotionRef.current) {
          // Attach to the last buffered snapshot, or buffer a standalone one
          const buffer = snapshotBufferRef.current;
          if (buffer.length > 0) {
            buffer[buffer.length - 1].bestOrder = d;
          } else {
            setState(prev => ({ ...prev, bestOrder: d }));
          }
        } else {
          setState(prev => ({ ...prev, bestOrder: d }));
        }
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
        log.info('SSE', `Session completed — best_order=${JSON.stringify(d.best_order)}, score=${d.best_score}, total_orders=${d.total_orders}`, d);
        const completedBestOrder = {
          order_id: d.best_order_id,
          order: d.best_order,
          score: d.best_score,
        };
        if (slowMotionRef.current && snapshotBufferRef.current.length > 0) {
          // Mark the last snapshot with the final best order
          const buffer = snapshotBufferRef.current;
          buffer[buffer.length - 1].bestOrder = completedBestOrder;
          // Append a "completed" sentinel — we'll handle status change after drain
          // For now, just defer the status change
          const waitForDrain = () => {
            if (snapshotBufferRef.current.length > 0) {
              setTimeout(waitForDrain, 200);
            } else {
              setState(prev => ({
                ...prev,
                status: 'completed',
                completedData: d,
                bestOrder: completedBestOrder,
              }));
            }
          };
          waitForDrain();
        } else {
          setState(prev => ({
            ...prev,
            status: 'completed',
            completedData: d,
            bestOrder: completedBestOrder,
          }));
        }
        break;
      }

      case 'session_failed': {
        const msg = (data as { message?: string }).message || 'Session failed';
        log.error('SSE', `Session failed: ${msg}`, data);
        setState(prev => ({
          ...prev,
          status: 'failed',
          error: msg,
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
                if (slowMotionRef.current) {
                  snapshotBufferRef.current.push({
                    ranking: d.top_k,
                    totalOrders: d.total_orders,
                    bestOrder: null,
                  });
                  if (!replayTimerRef.current || snapshotBufferRef.current.length === 1) {
                    next.isReplaying = true;
                    // Schedule drain outside setState
                    setTimeout(() => drainNextSnapshot(), SLOW_MOTION_DELAY_MS);
                  }
                } else {
                  next.ranking = d.top_k;
                  next.totalOrders = d.total_orders;
                }
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
  }, [drainNextSnapshot]);

  useEffect(() => {
    if (!sessionId) {
      setState(initialState);
      return;
    }

    setState(initialState);
    snapshotBufferRef.current = [];
    if (replayTimerRef.current) {
      clearTimeout(replayTimerRef.current);
      replayTimerRef.current = null;
    }

    const t0 = performance.now();
    const es = new EventSource(getStreamUrl(sessionId));
    esRef.current = es;
    log.info('SSE', `EventSource connecting for session ${sessionId}`);

    const handleEvent = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (e.type === 'session_started') {
            const delay = performance.now() - t0;
            log.info('SSE', `Session started. Stream API latency delay: ${delay.toFixed(2)}ms`);
        }
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
      log.warn('SSE', 'EventSource error / reconnect attempt');
      // EventSource will auto-reconnect; if state is terminal, close
      setState(prev => {
        if (prev.status === 'completed' || prev.status === 'failed') {
          es.close();
        }
        return prev;
      });
    };

    return () => {
      log.info('SSE', `EventSource closed for session ${sessionId}`);
      es.close();
      esRef.current = null;
      if (replayTimerRef.current) {
        clearTimeout(replayTimerRef.current);
        replayTimerRef.current = null;
      }
    };
  }, [sessionId, processEvent]);

  const close = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
  }, []);

  const setSlowMotion = useCallback((enabled: boolean) => {
    slowMotionRef.current = enabled;
    if (!enabled) {
      // Flush all buffered snapshots immediately
      const buffer = snapshotBufferRef.current;
      if (buffer.length > 0) {
        const last = buffer[buffer.length - 1];
        snapshotBufferRef.current = [];
        if (replayTimerRef.current) {
          clearTimeout(replayTimerRef.current);
          replayTimerRef.current = null;
        }
        setState(prev => ({
          ...prev,
          ranking: last.ranking,
          totalOrders: last.totalOrders,
          bestOrder: last.bestOrder ?? prev.bestOrder,
          isReplaying: false,
        }));
      }
    }
  }, []);

  return { ...state, close, setSlowMotion };
}
