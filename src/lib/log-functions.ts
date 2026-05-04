// Re-export server functions for use in components (outside src/server/ to avoid import-protection)
export { listLogs, clearLogs, getLogRetention, cleanupLogs } from "@/server/api.functions";
