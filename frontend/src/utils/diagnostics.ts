export type DiagnosticsLevel = 'debug' | 'info' | 'warn' | 'error';

export type DiagnosticsEntry = {
  ts: number;
  level: DiagnosticsLevel;
  message: string;
  data?: unknown;
};

export type DiagnosticsState = {
  v: 1;
  entries: DiagnosticsEntry[];
};

export type DiagnosticErrorPayload = {
  title: string;
  message: string;
  kind?: 'network' | 'http' | 'app' | 'unknown';
  details?: unknown;
};

const STORAGE_KEY = 'podly.diagnostics.v1';
const MAX_ENTRIES = 200;
const MAX_ENTRY_MESSAGE_CHARS = 500;
const MAX_JSON_CHARS = 120_000;

const SENSITIVE_KEY_RE = /(authorization|cookie|set-cookie|token|access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|secret|password|session)/i;
const SENSITIVE_VALUE_REPLACEMENT = '[REDACTED]';

const redactString = (value: string): string => {
  let v = value;
  // Authorization headers / bearer tokens
  v = v.replace(/\bBearer\s+([A-Za-z0-9\-._~+/]+=*)/gi, 'Bearer [REDACTED]');
  v = v.replace(/\bBasic\s+([A-Za-z0-9+/=]+)\b/gi, 'Basic [REDACTED]');

  // Common query params
  v = v.replace(/([?&](?:token|access_token|refresh_token|id_token|api_key|key|password)=)([^&#]+)/gi, '$1[REDACTED]');

  // JSON-ish fields in strings
  v = v.replace(/("(?:access_token|refresh_token|id_token|token|api_key|password)"\s*:\s*")([^"]+)(")/gi, '$1[REDACTED]$3');

  return v;
};

const sanitize = (input: unknown, depth = 0): unknown => {
  if (depth > 6) return '[Truncated]';
  if (input == null) return input;

  if (typeof input === 'string') return redactString(input);
  if (typeof input === 'number' || typeof input === 'boolean') return input;

  if (Array.isArray(input)) {
    return input.slice(0, 50).map((v) => sanitize(v, depth + 1));
  }

  if (typeof input === 'object') {
    const obj = input as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    const keys = Object.keys(obj).slice(0, 50);
    for (const key of keys) {
      const value = obj[key];
      if (SENSITIVE_KEY_RE.test(key)) {
        out[key] = SENSITIVE_VALUE_REPLACEMENT;
      } else {
        out[key] = sanitize(value, depth + 1);
      }
    }
    return out;
  }

  return String(input);
};

const safeJsonStringify = (value: unknown): string => {
  try {
    const json = JSON.stringify(value);
    if (json.length <= MAX_JSON_CHARS) return json;
    return json.slice(0, MAX_JSON_CHARS) + '\n...[truncated]';
  } catch {
    return '[Unserializable]';
  }
};

const loadState = (): DiagnosticsState => {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return { v: 1, entries: [] };
    const parsed = JSON.parse(raw) as DiagnosticsState;
    if (parsed?.v !== 1 || !Array.isArray(parsed.entries)) {
      return { v: 1, entries: [] };
    }
    return parsed;
  } catch {
    return { v: 1, entries: [] };
  }
};

const saveState = (state: DiagnosticsState) => {
  try {
    const raw = safeJsonStringify(state);
    // Prevent sessionStorage bloat
    if (raw.length > MAX_JSON_CHARS) {
      const trimmed = { v: 1 as const, entries: state.entries.slice(-Math.floor(MAX_ENTRIES / 2)) };
      sessionStorage.setItem(STORAGE_KEY, safeJsonStringify(trimmed));
      return;
    }
    sessionStorage.setItem(STORAGE_KEY, raw);
  } catch {
    // ignore
  }
};

export const DIAGNOSTIC_UPDATED_EVENT = 'podly:diagnostic-updated';

export const diagnostics = {
  add: (level: DiagnosticsLevel, message: string, data?: unknown) => {
    const sanitizedMessage = redactString(message).slice(0, MAX_ENTRY_MESSAGE_CHARS);
    const entry: DiagnosticsEntry = {
      ts: Date.now(),
      level,
      message: sanitizedMessage,
      data: data === undefined ? undefined : sanitize(data),
    };

    const state = loadState();
    const next = [...state.entries, entry].slice(-MAX_ENTRIES);
    saveState({ v: 1, entries: next });

    try {
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new Event(DIAGNOSTIC_UPDATED_EVENT));
      }
    } catch {
      // ignore
    }
  },

  getEntries: (): DiagnosticsEntry[] => {
    return loadState().entries;
  },

  clear: () => {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  },

  sanitize,
};

export const DIAGNOSTIC_ERROR_EVENT = 'podly:diagnostic-error';

export const emitDiagnosticError = (payload: DiagnosticErrorPayload) => {
  const safePayload = diagnostics.sanitize(payload) as DiagnosticErrorPayload;
  diagnostics.add('error', safePayload.title + ': ' + safePayload.message, safePayload);
  try {
    window.dispatchEvent(new CustomEvent(DIAGNOSTIC_ERROR_EVENT, { detail: safePayload }));
  } catch {
    // ignore
  }
};

let consoleWrapped = false;

export const initFrontendDiagnostics = () => {
  if (typeof window === 'undefined') return;

  if (!consoleWrapped) {
    consoleWrapped = true;
    const wrap = (level: DiagnosticsLevel, original: (...args: unknown[]) => void) =>
      (...args: unknown[]) => {
        try {
          const msg = args
            .map((a) => (typeof a === 'string' ? a : safeJsonStringify(diagnostics.sanitize(a))))
            .join(' ');
          diagnostics.add(level, msg);
        } catch {
          // ignore
        }
        original(...args);
      };

    console.log = wrap('info', console.log.bind(console));
    console.info = wrap('info', console.info.bind(console));
    console.warn = wrap('warn', console.warn.bind(console));
    console.error = wrap('error', console.error.bind(console));
  }

  window.addEventListener('error', (event) => {
    // Cross-origin scripts (iOS content blockers, browser extensions, injected
    // third-party code) are reported by the browser as "Script error." with an
    // empty filename and zero line/column numbers — the browser intentionally
    // hides all details for security.  These are never actionable, so we log
    // them quietly and skip the modal.
    if (event.message === 'Script error.' && !event.filename && event.lineno === 0) {
      diagnostics.add('warn', 'Cross-origin script error suppressed (likely iOS extension/content-blocker)');
      return;
    }

    emitDiagnosticError({
      title: 'Unhandled error',
      message: event.message || 'Unknown error',
      kind: 'app',
      details: {
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
      },
    });
  });

  window.addEventListener('unhandledrejection', (event) => {
    // Wrap the entire handler in try/catch — if anything here throws (e.g.
    // extractError itself fails) we must not create a new unhandled rejection,
    // which would trigger this handler recursively.
    try {
      const reason = (event as PromiseRejectionEvent).reason;

      // Error objects have non-enumerable message/stack so plain JSON.stringify
      // loses them.  Explicitly extract safe, useful fields before passing to
      // the sanitiser.  We allow-list rather than spreading all enumerable
      // properties to avoid leaking sensitive AxiosError fields (auth headers,
      // request config, full response bodies, etc.).
      const extractError = (
        err: unknown,
        seen = new WeakSet<object>(),
        depth = 0,
      ): unknown => {
        if (depth > 5) return '[MaxDepthExceeded]';
        if (err instanceof Error) {
          if (seen.has(err)) return '[CircularError]';
          seen.add(err);

          const axiosErr = err as Error & {
            code?: string;
            response?: { status?: number; statusText?: string };
            config?: { method?: string; url?: string };
          };

          const causeVal =
            'cause' in err && err.cause !== undefined
              ? { cause: extractError((err as Error & { cause?: unknown }).cause, seen, depth + 1) }
              : {};

          return {
            // Allow-listed safe fields — put explicit keys last so they
            // always take precedence over anything in enumerable properties.
            ...(axiosErr.code !== undefined ? { code: axiosErr.code } : {}),
            ...(axiosErr.response?.status !== undefined ? { httpStatus: axiosErr.response.status } : {}),
            ...(axiosErr.response?.statusText !== undefined ? { httpStatusText: axiosErr.response.statusText } : {}),
            ...(axiosErr.config?.method !== undefined ? { requestMethod: axiosErr.config.method } : {}),
            ...(axiosErr.config?.url !== undefined ? { requestUrl: axiosErr.config.url } : {}),
            ...causeVal,
            // Explicit fields last so they are never overwritten.
            errorType: err.constructor?.name ?? 'Error',
            message: err.message,
            stack: err.stack,
          };
        }
        return err;
      };

      const details = extractError(reason);
      const message =
        reason instanceof Error
          ? reason.message || reason.constructor?.name || 'Promise rejected'
          : typeof reason === 'string'
            ? reason
            : 'Promise rejected';

      emitDiagnosticError({
        title: 'Unhandled promise rejection',
        message,
        kind: 'app',
        details,
      });
    } catch {
      // ignore — do not create a new unhandled rejection
    }
  });
};
