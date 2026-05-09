CREATE TABLE public.site_user_passwords (
  username text PRIMARY KEY,
  password_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.site_user_passwords ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public read site_user_passwords"
  ON public.site_user_passwords FOR SELECT
  USING (true);

CREATE POLICY "public insert site_user_passwords"
  ON public.site_user_passwords FOR INSERT
  WITH CHECK (true);

CREATE POLICY "public update site_user_passwords"
  ON public.site_user_passwords FOR UPDATE
  USING (true) WITH CHECK (true);