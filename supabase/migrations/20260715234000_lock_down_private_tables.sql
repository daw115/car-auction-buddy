-- The application accesses these tables exclusively through authenticated server
-- functions using the service role. Browser roles must not access them directly.

DROP POLICY IF EXISTS "public read clients" ON public.clients;
DROP POLICY IF EXISTS "public write clients" ON public.clients;
DROP POLICY IF EXISTS "public update clients" ON public.clients;
DROP POLICY IF EXISTS "public delete clients" ON public.clients;

DROP POLICY IF EXISTS "public read records" ON public.records;
DROP POLICY IF EXISTS "public write records" ON public.records;
DROP POLICY IF EXISTS "public update records" ON public.records;
DROP POLICY IF EXISTS "public delete records" ON public.records;

DROP POLICY IF EXISTS "public read app_config" ON public.app_config;
DROP POLICY IF EXISTS "public update app_config" ON public.app_config;

DROP POLICY IF EXISTS "public read operation_logs" ON public.operation_logs;
DROP POLICY IF EXISTS "public write operation_logs" ON public.operation_logs;
DROP POLICY IF EXISTS "public delete operation_logs" ON public.operation_logs;

DROP POLICY IF EXISTS "public read watchlist" ON public.watchlist;
DROP POLICY IF EXISTS "public insert watchlist" ON public.watchlist;
DROP POLICY IF EXISTS "public update watchlist" ON public.watchlist;
DROP POLICY IF EXISTS "public delete watchlist" ON public.watchlist;

DROP POLICY IF EXISTS "public read watchlist_history" ON public.watchlist_history;
DROP POLICY IF EXISTS "public insert watchlist_history" ON public.watchlist_history;
DROP POLICY IF EXISTS "public delete watchlist_history" ON public.watchlist_history;

DROP POLICY IF EXISTS "public read scrape_cache" ON public.scrape_cache;
DROP POLICY IF EXISTS "public insert scrape_cache" ON public.scrape_cache;
DROP POLICY IF EXISTS "public update scrape_cache" ON public.scrape_cache;
DROP POLICY IF EXISTS "public delete scrape_cache" ON public.scrape_cache;

DROP POLICY IF EXISTS "public read site_user_passwords" ON public.site_user_passwords;
DROP POLICY IF EXISTS "public insert site_user_passwords" ON public.site_user_passwords;
DROP POLICY IF EXISTS "public update site_user_passwords" ON public.site_user_passwords;

ALTER TABLE public.clients FORCE ROW LEVEL SECURITY;
ALTER TABLE public.records FORCE ROW LEVEL SECURITY;
ALTER TABLE public.app_config FORCE ROW LEVEL SECURITY;
ALTER TABLE public.operation_logs FORCE ROW LEVEL SECURITY;
ALTER TABLE public.watchlist FORCE ROW LEVEL SECURITY;
ALTER TABLE public.watchlist_history FORCE ROW LEVEL SECURITY;
ALTER TABLE public.scrape_cache FORCE ROW LEVEL SECURITY;
ALTER TABLE public.site_user_passwords FORCE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON TABLE
  public.clients,
  public.records,
  public.app_config,
  public.operation_logs,
  public.watchlist,
  public.watchlist_history,
  public.scrape_cache,
  public.site_user_passwords
FROM anon, authenticated;


-- A dedicated row per hashed IP/user key makes login attempt consumption atomic
-- across all application instances. Only the service role can invoke these RPCs.
CREATE TABLE IF NOT EXISTS public.site_auth_rate_limits (
  rate_key text PRIMARY KEY,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  window_started_at timestamptz NOT NULL DEFAULT now(),
  locked_until timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT site_auth_rate_limits_key_format CHECK (rate_key ~ '^[0-9a-f]{64}$')
);

ALTER TABLE public.site_auth_rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.site_auth_rate_limits FORCE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public.site_auth_rate_limits FROM anon, authenticated;

CREATE OR REPLACE FUNCTION public.consume_site_auth_attempt(p_rate_key text)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_now timestamptz := clock_timestamp();
  v_attempts integer;
  v_window_started_at timestamptz;
  v_locked_until timestamptz;
BEGIN
  IF p_rate_key IS NULL OR p_rate_key !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'Invalid site authentication rate key' USING ERRCODE = '22023';
  END IF;

  INSERT INTO public.site_auth_rate_limits (rate_key, attempts, window_started_at, updated_at)
  VALUES (p_rate_key, 0, v_now, v_now)
  ON CONFLICT (rate_key) DO NOTHING;

  SELECT attempts, window_started_at, locked_until
  INTO v_attempts, v_window_started_at, v_locked_until
  FROM public.site_auth_rate_limits
  WHERE rate_key = p_rate_key
  FOR UPDATE;

  IF v_locked_until IS NOT NULL AND v_locked_until > v_now THEN
    RETURN GREATEST(1, CEIL(EXTRACT(EPOCH FROM (v_locked_until - v_now)))::integer);
  END IF;

  IF v_window_started_at <= v_now - interval '15 minutes' THEN
    v_attempts := 0;
    v_window_started_at := v_now;
    v_locked_until := NULL;
  END IF;

  IF v_attempts >= 5 THEN
    v_locked_until := v_now + interval '15 minutes';
    UPDATE public.site_auth_rate_limits
    SET locked_until = v_locked_until, updated_at = v_now
    WHERE rate_key = p_rate_key;
    RETURN 15 * 60;
  END IF;

  v_attempts := v_attempts + 1;
  UPDATE public.site_auth_rate_limits
  SET attempts = v_attempts,
      window_started_at = v_window_started_at,
      locked_until = CASE
        WHEN v_attempts >= 5 THEN v_now + interval '15 minutes'
        ELSE NULL
      END,
      updated_at = v_now
  WHERE rate_key = p_rate_key;

  RETURN 0;
END;
$$;

CREATE OR REPLACE FUNCTION public.reset_site_auth_attempts(p_rate_key text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_rate_key IS NULL OR p_rate_key !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'Invalid site authentication rate key' USING ERRCODE = '22023';
  END IF;
  DELETE FROM public.site_auth_rate_limits WHERE rate_key = p_rate_key;
END;
$$;

REVOKE ALL ON FUNCTION public.consume_site_auth_attempt(text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.reset_site_auth_attempts(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.consume_site_auth_attempt(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.reset_site_auth_attempts(text) TO service_role;