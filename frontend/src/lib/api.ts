import type { DatasetInfo, SessionCreateRequest, SessionCreateResponse } from '../types/api';
import { frontendLogger as log } from './logger';

const BASE = '/api';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const method = init?.method || 'GET';
  log.debug('API', `${method} ${BASE}${url}`, init?.body ? JSON.parse(init.body as string) : undefined);
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    log.error('API', `${method} ${BASE}${url} → ${res.status}`, body);
    throw new Error(`API error ${res.status}: ${body}`);
  }
  const data = await res.json();
  log.info('API', `${method} ${BASE}${url} → ${res.status}`, data);
  return data;
}

export async function fetchDatasets(): Promise<DatasetInfo[]> {
  return fetchJSON<DatasetInfo[]>('/datasets');
}

export async function fetchDataset(id: string): Promise<DatasetInfo> {
  return fetchJSON<DatasetInfo>(`/datasets/${id}`);
}

export async function createSession(req: SessionCreateRequest): Promise<SessionCreateResponse> {
  return fetchJSON<SessionCreateResponse>('/sessions', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export async function fetchSessionResult(sessionId: string) {
  return fetchJSON<Record<string, unknown>>(`/sessions/${sessionId}/result`);
}

export async function executeSession(sessionId: string) {
  return fetchJSON<Record<string, unknown>>(`/sessions/${sessionId}/execute`, {
    method: 'POST',
  });
}

export function getStreamUrl(sessionId: string): string {
  return `${BASE}/sessions/${sessionId}/stream`;
}
