ALTER TABLE public.records
  ADD COLUMN IF NOT EXISTS retry_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS max_retries integer NOT NULL DEFAULT 3,
  ADD COLUMN IF NOT EXISTS next_retry_at timestamptz DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS last_error_at timestamptz DEFAULT NULL;