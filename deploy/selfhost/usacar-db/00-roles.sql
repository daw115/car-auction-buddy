-- Role, których oczekują migracje przeniesione z Supabase.
-- Uruchomić RAZ, jako postgres, PRZED migracjami.
--
-- Wywołanie:
--   psql "postgres://postgres:<haslo>@127.0.0.1:5433/postgres" \
--        -v ON_ERROR_STOP=1 -v authenticator_password="'<haslo>'" -f 00-roles.sql
--
-- BYPASSRLS na service_role jest OBOWIĄZKOWE. Migracja lockdown nakłada
-- FORCE ROW LEVEL SECURITY na tabele prywatne bez żadnych polityk — FORCE znosi
-- wyjątek dla właściciela tabeli, więc bez BYPASSRLS supabaseAdmin nie odczytałby
-- ani nie zapisał niczego. Dokładnie tak zachowuje się service_role w Supabase.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    CREATE ROLE service_role NOLOGIN NOINHERIT BYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticator') THEN
    CREATE ROLE authenticator LOGIN NOINHERIT;
  END IF;
END
$$;

-- Hasło ustawiane osobno, żeby skrypt był idempotentny.
ALTER ROLE authenticator WITH PASSWORD :authenticator_password;

-- PostgREST loguje się jako authenticator i przełącza SET ROLE na rolę z claimu JWT.
GRANT anon, authenticated, service_role TO authenticator;

GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

-- Migracje tworzą tabele jako postgres; service_role musi mieć do nich pełny dostęp
-- także dla obiektów powstałych później.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO service_role;
