ALTER TABLE public.records
  ADD COLUMN IF NOT EXISTS analysis_error text DEFAULT NULL;