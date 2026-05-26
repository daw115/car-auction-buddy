-- Remove permissive public policies on the password store
DROP POLICY IF EXISTS "public read site_user_passwords" ON public.site_user_passwords;
DROP POLICY IF EXISTS "public insert site_user_passwords" ON public.site_user_passwords;
DROP POLICY IF EXISTS "public update site_user_passwords" ON public.site_user_passwords;

-- Keep RLS enabled. No policies means anon/authenticated roles cannot access the table.
-- Service role (used by server functions via supabaseAdmin) bypasses RLS.
ALTER TABLE public.site_user_passwords FORCE ROW LEVEL SECURITY;

-- Add per-user salt for password hashing
ALTER TABLE public.site_user_passwords
  ADD COLUMN IF NOT EXISTS password_salt text;

-- Harden function search_path
CREATE OR REPLACE FUNCTION public.touch_watchlist_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;