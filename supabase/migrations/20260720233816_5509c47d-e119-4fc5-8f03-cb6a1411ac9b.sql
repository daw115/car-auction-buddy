-- 1) clients_v2
CREATE TABLE public.clients_v2 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  email TEXT,
  phone TEXT,
  notes TEXT,
  created_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT ALL ON public.clients_v2 TO service_role;
ALTER TABLE public.clients_v2 ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role full access" ON public.clients_v2 FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE INDEX clients_v2_name_idx ON public.clients_v2 (lower(name));

-- 2) client_cases
CREATE TABLE public.client_cases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID NOT NULL REFERENCES public.clients_v2(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  default_criteria JSONB,
  status TEXT NOT NULL DEFAULT 'open',
  auto_refresh_enabled BOOLEAN NOT NULL DEFAULT false,
  auto_refresh_interval_hours INT NOT NULL DEFAULT 24,
  last_auto_run_at TIMESTAMPTZ,
  next_auto_run_at TIMESTAMPTZ,
  created_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT client_cases_status_check CHECK (status IN ('open','paused','closed')),
  CONSTRAINT client_cases_interval_check CHECK (auto_refresh_interval_hours BETWEEN 1 AND 168)
);
GRANT ALL ON public.client_cases TO service_role;
ALTER TABLE public.client_cases ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role full access" ON public.client_cases FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE INDEX client_cases_client_id_idx ON public.client_cases (client_id);
CREATE INDEX client_cases_auto_refresh_idx ON public.client_cases (auto_refresh_enabled, next_auto_run_at) WHERE auto_refresh_enabled = true;

-- 3) case_searches
CREATE TABLE public.case_searches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID NOT NULL REFERENCES public.client_cases(id) ON DELETE CASCADE,
  record_id TEXT NOT NULL,
  searched_by TEXT,
  new_lot_ids TEXT[] NOT NULL DEFAULT '{}',
  triggered_by TEXT NOT NULL DEFAULT 'manual',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT case_searches_unique UNIQUE (case_id, record_id)
);
GRANT ALL ON public.case_searches TO service_role;
ALTER TABLE public.case_searches ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role full access" ON public.case_searches FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE INDEX case_searches_case_id_idx ON public.case_searches (case_id, created_at DESC);
CREATE INDEX case_searches_record_id_idx ON public.case_searches (record_id);

-- 4) shared updated_at trigger
CREATE OR REPLACE FUNCTION public.touch_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$;

CREATE TRIGGER clients_v2_touch BEFORE UPDATE ON public.clients_v2
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
CREATE TRIGGER client_cases_touch BEFORE UPDATE ON public.client_cases
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();