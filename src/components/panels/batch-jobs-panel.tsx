import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BatchJobCard, type BatchJobEntry } from "@/components/panels/batch-job-card";

type Props = {
  batchJobs: BatchJobEntry[];
  onClear: () => void;
  onPollUpdate: (jobId: string, update: Partial<BatchJobEntry>) => void;
};

export function BatchJobsPanel({ batchJobs, onClear, onPollUpdate }: Props) {
  if (batchJobs.length === 0) return null;
  const allDone = batchJobs.every(
    (j) => j.status === "done" || j.status === "error" || j.status === "cancelled",
  );
  return (
    <Card className="p-4 mb-4 border-primary/30">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">📦</span>
          <h3 className="font-semibold">Batch wyszukiwanie</h3>
          <Badge variant="outline" className="text-[10px]">
            {batchJobs.filter((j) => j.status === "done").length}/{batchJobs.length} gotowe
          </Badge>
        </div>
        {allDone && (
          <Button size="sm" variant="ghost" onClick={onClear}>
            <X className="h-3.5 w-3.5 mr-1" /> Zamknij
          </Button>
        )}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {batchJobs.map((job) => (
          <BatchJobCard key={job.jobId} job={job} onPollUpdate={onPollUpdate} />
        ))}
      </div>
    </Card>
  );
}
