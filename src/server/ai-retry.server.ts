// Retry with exponential backoff for AI provider calls.
// Retries on rate-limit (429), overloaded (529/503), and timeout errors.

export type RetryOpts = {
  /** Max retry attempts (default 3) */
  maxRetries?: number;
  /** Initial delay in ms (default 2000) */
  initialDelayMs?: number;
  /** Max delay cap in ms (default 30000) */
  maxDelayMs?: number;
  /** Provider name for log messages */
  provider: string;
};

const RETRYABLE_STATUS_CODES = new Set([429, 503, 529]);

export class AIRetryableError extends Error {
  constructor(
    message: string,
    public readonly statusCode: number,
    public readonly retryAfterMs: number | null,
    public readonly provider: string,
  ) {
    super(message);
    this.name = "AIRetryableError";
  }
}

export class AITimeoutError extends Error {
  constructor(message: string, public readonly provider: string) {
    super(message);
    this.name = "AITimeoutError";
  }
}

/**
 * Classify an error thrown by a provider fetch call.
 * Returns a user-friendly message and whether it's retryable.
 */
export function classifyProviderError(
  err: unknown,
  provider: string,
): { message: string; retryable: boolean } {
  if (err instanceof AIRetryableError) {
    return { message: err.message, retryable: true };
  }
  if (err instanceof AITimeoutError) {
    return { message: err.message, retryable: true };
  }
  const msg = err instanceof Error ? err.message : String(err);

  // Rate limit
  if (msg.includes("429") || msg.toLowerCase().includes("rate limit")) {
    return {
      message: `${provider}: Przekroczono limit zapytań (rate limit). Spróbuj ponownie za chwilę.`,
      retryable: true,
    };
  }
  // Overloaded
  if (msg.includes("529") || msg.includes("503") || msg.toLowerCase().includes("overloaded")) {
    return {
      message: `${provider}: Serwer przeciążony. Spróbuj ponownie za chwilę.`,
      retryable: true,
    };
  }
  // Timeout
  if (msg.toLowerCase().includes("timeout") || msg.includes("AbortError")) {
    return {
      message: `${provider}: Przekroczono czas oczekiwania (timeout). Spróbuj zmniejszyć prompt lub spróbuj ponownie.`,
      retryable: true,
    };
  }
  // Auth
  if (msg.includes("401") || msg.includes("403")) {
    return {
      message: `${provider}: Błąd autoryzacji — sprawdź klucz API.`,
      retryable: false,
    };
  }
  // Generic
  return { message: `${provider}: ${msg}`, retryable: false };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Parse Retry-After header value to milliseconds.
 */
function parseRetryAfter(headerValue: string | null): number | null {
  if (!headerValue) return null;
  const seconds = Number(headerValue);
  if (!Number.isNaN(seconds) && seconds > 0) return seconds * 1000;
  // Could be a date, but we'll skip that for simplicity
  return null;
}

/**
 * Execute a fetch-based AI call with retry + exponential backoff.
 * The `fn` should throw AIRetryableError or AITimeoutError for retryable cases.
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  opts: RetryOpts,
): Promise<T> {
  const maxRetries = opts.maxRetries ?? 3;
  const initialDelay = opts.initialDelayMs ?? 2_000;
  const maxDelay = opts.maxDelayMs ?? 30_000;

  let lastError: unknown;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      const classified = classifyProviderError(err, opts.provider);

      if (!classified.retryable || attempt >= maxRetries) {
        // No more retries — throw with user-friendly message
        throw new Error(
          attempt > 0
            ? `${classified.message} (po ${attempt} ponowieniach)`
            : classified.message,
        );
      }

      // Calculate delay: use Retry-After if available, otherwise exponential backoff with jitter
      let delay: number;
      if (err instanceof AIRetryableError && err.retryAfterMs) {
        delay = Math.min(err.retryAfterMs, maxDelay);
      } else {
        const base = initialDelay * Math.pow(2, attempt);
        const jitter = Math.random() * 0.3 * base; // up to 30% jitter
        delay = Math.min(base + jitter, maxDelay);
      }

      console.warn(
        `[ai-retry] ${opts.provider} attempt ${attempt + 1}/${maxRetries} failed: ${classified.message}. Retrying in ${Math.round(delay)}ms...`,
      );

      await sleep(delay);
    }
  }

  // Should not reach here, but just in case
  throw lastError;
}

/**
 * Check a fetch Response for retryable status and throw appropriate error.
 * Call this right after fetch() before parsing the body.
 */
export function checkRetryableResponse(res: Response, provider: string): void {
  if (res.ok) return;

  if (RETRYABLE_STATUS_CODES.has(res.status)) {
    const retryAfter = parseRetryAfter(res.headers.get("retry-after"));
    const statusLabels: Record<number, string> = {
      429: "Przekroczono limit zapytań (rate limit)",
      503: "Serwer tymczasowo niedostępny",
      529: "Serwer przeciążony",
    };
    throw new AIRetryableError(
      `${provider}: ${statusLabels[res.status] ?? `HTTP ${res.status}`}`,
      res.status,
      retryAfter,
      provider,
    );
  }
}
