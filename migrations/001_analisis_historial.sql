-- Historial de análisis SOLUM
-- Ejecutar en Supabase SQL Editor

CREATE TABLE IF NOT EXISTS public.analisis_historial (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    usuario     TEXT,
    modulo      TEXT,
    distrito    TEXT,
    tipo        TEXT,
    kpis        JSONB,
    inputs_resumen JSONB
);

-- Índice para consultas por usuario y fecha
CREATE INDEX IF NOT EXISTS idx_historial_usuario_fecha
    ON public.analisis_historial (usuario, created_at DESC);

-- RLS básico (ajustar según auth setup de SOLUM)
ALTER TABLE public.analisis_historial ENABLE ROW LEVEL SECURITY;

-- Policy permisiva para service_role (el cliente Supabase de SOLUM usa service_role)
CREATE POLICY "service_role_all" ON public.analisis_historial
    FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMENT ON TABLE public.analisis_historial IS
    'Historial de análisis de pre-factibilidad ejecutados en SOLUM';
