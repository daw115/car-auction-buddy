-- Add analysis tracking and artifacts metadata columns to records
ALTER TABLE public.records
  ADD COLUMN IF NOT EXISTS analysis_status text DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS analysis_started_at timestamptz DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS analysis_completed_at timestamptz DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS artifacts_meta jsonb DEFAULT NULL;