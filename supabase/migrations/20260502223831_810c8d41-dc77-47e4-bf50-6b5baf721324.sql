ALTER TABLE public.app_config
ADD COLUMN ai_fallback_mode text NOT NULL DEFAULT 'error_only';

COMMENT ON COLUMN public.app_config.ai_fallback_mode IS 'Strategia fallbacku AI: error_only = fallback tylko przy błędach, race_both = zawsze próbuj obu dostawców równolegle';