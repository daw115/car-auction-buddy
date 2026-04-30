CREATE TABLE IF NOT EXISTS public.scrape_cache (
  id uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  cache_key text NOT NULL UNIQUE,
  criteria jsonb NOT NULL,
  config_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  listings jsonb NOT NULL DEFAULT '[]'::jsonb,
  listings_count integer NOT NULL DEFAULT 0,
  source text,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL DEFAULT (now() + interval '1 hour')
);

CREATE INDEX IF NOT EXISTS scrape_cache_expires_at_idx ON public.scrape_cache (expires_at);
CREATE INDEX IF NOT EXISTS scrape_cache_created_at_idx ON public.scrape_cache (created_at DESC);

ALTER TABLE public.scrape_cache ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public read scrape_cache" ON public.scrape_cache FOR SELECT USING (true);
CREATE POLICY "public insert scrape_cache" ON public.scrape_cache FOR INSERT WITH CHECK (true);
CREATE POLICY "public delete scrape_cache" ON public.scrape_cache FOR DELETE USING (true);
CREATE POLICY "public update scrape_cache" ON public.scrape_cache FOR UPDATE USING (true) WITH CHECK (true);