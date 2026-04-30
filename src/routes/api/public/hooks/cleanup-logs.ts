import { createFileRoute } from '@tanstack/react-router'
import { supabaseAdmin } from '@/integrations/supabase/client.server'

const DEFAULT_RETENTION_DAYS = 30

function getRetentionDays(): number {
  const raw = process.env.LOG_RETENTION_DAYS
  const parsed = raw ? parseInt(raw, 10) : NaN
  if (!Number.isFinite(parsed) || parsed <= 0) return DEFAULT_RETENTION_DAYS
  return Math.min(parsed, 3650)
}

async function runCleanup() {
  const days = getRetentionDays()
  const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString()
  const { error, count } = await supabaseAdmin
    .from('operation_logs')
    .delete({ count: 'exact' })
    .lt('created_at', cutoff)
  if (error) throw error
  return { retention_days: days, cutoff, deleted: count ?? 0 }
}

export const Route = createFileRoute('/api/public/hooks/cleanup-logs')({
  server: {
    handlers: {
      POST: async () => {
        try {
          const result = await runCleanup()
          return new Response(JSON.stringify({ success: true, ...result }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        } catch (e: any) {
          return new Response(
            JSON.stringify({ success: false, error: e?.message ?? 'cleanup failed' }),
            { status: 500, headers: { 'Content-Type': 'application/json' } },
          )
        }
      },
      GET: async () => {
        try {
          const result = await runCleanup()
          return new Response(JSON.stringify({ success: true, ...result }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        } catch (e: any) {
          return new Response(
            JSON.stringify({ success: false, error: e?.message ?? 'cleanup failed' }),
            { status: 500, headers: { 'Content-Type': 'application/json' } },
          )
        }
      },
    },
  },
})
