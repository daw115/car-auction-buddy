
CREATE TABLE public.watchlist (
  id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  client_id UUID REFERENCES public.clients(id) ON DELETE SET NULL,
  source TEXT,
  lot_id TEXT,
  url TEXT,
  title TEXT,
  make TEXT,
  model TEXT,
  year INT,
  vin TEXT,
  current_bid_usd NUMERIC,
  buy_now_usd NUMERIC,
  score NUMERIC,
  category TEXT,
  notes TEXT,
  snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX watchlist_active_idx ON public.watchlist(active);
CREATE INDEX watchlist_client_id_idx ON public.watchlist(client_id);

CREATE TABLE public.watchlist_history (
  id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  watchlist_id UUID NOT NULL REFERENCES public.watchlist(id) ON DELETE CASCADE,
  current_bid_usd NUMERIC,
  score NUMERIC,
  status TEXT,
  payload JSONB,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX watchlist_history_wid_idx ON public.watchlist_history(watchlist_id, recorded_at DESC);

ALTER TABLE public.watchlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.watchlist_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public read watchlist" ON public.watchlist FOR SELECT USING (true);
CREATE POLICY "public insert watchlist" ON public.watchlist FOR INSERT WITH CHECK (true);
CREATE POLICY "public update watchlist" ON public.watchlist FOR UPDATE USING (true);
CREATE POLICY "public delete watchlist" ON public.watchlist FOR DELETE USING (true);

CREATE POLICY "public read watchlist_history" ON public.watchlist_history FOR SELECT USING (true);
CREATE POLICY "public insert watchlist_history" ON public.watchlist_history FOR INSERT WITH CHECK (true);
CREATE POLICY "public delete watchlist_history" ON public.watchlist_history FOR DELETE USING (true);

CREATE OR REPLACE FUNCTION public.touch_watchlist_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER watchlist_touch BEFORE UPDATE ON public.watchlist
FOR EACH ROW EXECUTE FUNCTION public.touch_watchlist_updated_at();
