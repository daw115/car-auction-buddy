import { useQuery } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { Link } from "@tanstack/react-router";
import { Activity, CheckCircle2 } from "lucide-react";
import { listActiveScraperJobs } from "@/functions/api.functions";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function ActiveJobPill() {
  const fnList = useServerFn(listActiveScraperJobs);
  const { data } = useQuery({
    queryKey: ["active-scraper-jobs-pill"],
    queryFn: () => fnList({}),
    refetchInterval: 5000,
    staleTime: 2000,
  });

  const activeCount = (data?.jobs ?? []).filter(
    (j) => j.status === "running" || j.status === "queued",
  ).length;

  if (activeCount === 0) {
    return (
      <Badge variant="outline" className="hidden sm:inline-flex items-center gap-1.5">
        <CheckCircle2 className="h-3.5 w-3.5 text-[var(--success)]" />
        <span className="text-xs">Brak aktywnych zadań</span>
      </Badge>
    );
  }

  const firstRunning = data?.jobs.find((j) => j.status === "running" || j.status === "queued");
  const label = firstRunning?.label ?? "Job w toku";

  return (
    <Link
      to="/"
      className={cn(
        "inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-medium text-primary",
        "hover:bg-primary/15 transition-colors",
      )}
      title={label}
    >
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
      </span>
      <Activity className="h-3.5 w-3.5" />
      <span className="hidden md:inline max-w-[180px] truncate">{label}</span>
      <span className="md:hidden">{activeCount}</span>
    </Link>
  );
}
