import type { DatasetInfo, SessionCreateRequest, SessionCreateResponse } from '../types/api';

const BASE = '/api';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API error ${res.status}: ${body}`);
  }
  return res.json();
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
