/**
 * Browser-side structured logger for the GraphQuery frontend.
 * 
 * Stores log entries in-memory (capped at MAX_ENTRIES).
 * Each entry: { timestamp, level, category, message, data? }
 * Provides downloadLogs() to export all entries as a .jsonl file.
 */

export type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';
export type LogCategory = 'SESSION' | 'SSE' | 'API' | 'EXECUTION' | 'CONFIG' | 'GENERAL';

interface LogEntry {
  timestamp: string;
  level: LogLevel;
  category: LogCategory;
  message: string;
  data?: unknown;
}

const MAX_ENTRIES = 5000;
const entries: LogEntry[] = [];

function now(): string {
  return new Date().toISOString();
}

function addEntry(level: LogLevel, category: LogCategory, message: string, data?: unknown) {
  const entry: LogEntry = { timestamp: now(), level, category, message };
  if (data !== undefined) entry.data = data;

  entries.push(entry);

  // Cap at MAX_ENTRIES (remove oldest)
  if (entries.length > MAX_ENTRIES) {
    entries.splice(0, entries.length - MAX_ENTRIES);
  }

  // Also mirror to browser console for real-time debugging
  const prefix = `[${category}]`;
  switch (level) {
    case 'DEBUG': console.debug(prefix, message, data ?? ''); break;
    case 'INFO':  console.log(prefix, message, data ?? '');   break;
    case 'WARN':  console.warn(prefix, message, data ?? '');  break;
    case 'ERROR': console.error(prefix, message, data ?? ''); break;
  }
}

export const frontendLogger = {
  debug: (category: LogCategory, message: string, data?: unknown) =>
    addEntry('DEBUG', category, message, data),

  info: (category: LogCategory, message: string, data?: unknown) =>
    addEntry('INFO', category, message, data),

  warn: (category: LogCategory, message: string, data?: unknown) =>
    addEntry('WARN', category, message, data),

  error: (category: LogCategory, message: string, data?: unknown) =>
    addEntry('ERROR', category, message, data),

  /** Get all log entries (read-only snapshot) */
  getEntries: (): readonly LogEntry[] => entries,

  /** Get entry count */
  count: (): number => entries.length,

  /** Clear all entries */
  clear: () => { entries.length = 0; },

  /** Download all logs as a .jsonl file */
  downloadLogs: () => {
    const lines = entries.map(e => JSON.stringify(e)).join('\n');
    const blob = new Blob([lines], { type: 'application/x-ndjson' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `graphquery_frontend_${new Date().toISOString().replace(/[:.]/g, '-')}.jsonl`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },
};
