/** Co scraper właśnie robi — na ekranie, na którym broker czeka.
 *
 *  Wyszukiwanie trwa kilka, czasem kilkanaście minut. Do tej pory przez cały ten
 *  czas widać było jedno zdanie i kręcące się kółko: nie dało się odróżnić pracy
 *  od zawieszenia, więc broker albo odświeżał kartę (gubiąc żądanie), albo szedł
 *  do „Aktywnych jobów" i tracił kontekst tego, na co czeka.
 *
 *  Backend raportował fazy od dawna — po prostu nikt ich tutaj nie czytał.
 */

import { useQuery } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { backendListJobs } from "@/functions/backend.functions";

const IKONA: Record<string, string> = {
  done: "✅",
  running: "🔄",
  pending: "⏳",
  blocked: "🚫",
  error: "❌",
  skipped: "⏭",
};

/** Fazy bywają puste przez pierwsze sekundy — wtedy mówimy to wprost,
 *  zamiast pokazywać pustą ramkę, która wygląda jak awaria. */
export function PrzebiegWyszukiwania() {
  const fnJobs = useServerFn(backendListJobs);

  const { data } = useQuery({
    queryKey: ["przebieg-wyszukiwania"],
    queryFn: () => fnJobs({ data: { activeOnly: true } }),
    // Dwie sekundy: tyle, ile odświeża się ekran „Aktywne joby". Szybciej nie ma
    // sensu, bo fazy zmieniają się co kilkadziesiąt sekund.
    refetchInterval: 2000,
  });

  const job = (data?.jobs ?? []).find((j) => j.status === "running" || j.status === "queued");
  const fazy = job?.phases ?? [];

  if (!job) {
    return (
      <div className="mt-3 text-xs text-muted-foreground">
        Czekam na pierwszą odpowiedź scrapera…
      </div>
    );
  }

  return (
    <div className="mt-3 rounded border bg-muted/40 p-2">
      <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
        <span className="truncate font-mono">{job.label || `job ${job.id.slice(0, 8)}`}</span>
        <span>{job.status}</span>
      </div>
      {fazy.length === 0 ? (
        <div className="font-mono text-xs text-muted-foreground">
          Scraper wstaje — przeglądarka i logowanie do giełd.
        </div>
      ) : (
        <div className="space-y-0.5 font-mono text-xs">
          {fazy.map((faza, i) => (
            <div key={`${faza.name}-${i}`} className="flex items-start gap-2">
              <span>{IKONA[faza.status] ?? "•"}</span>
              <span className={faza.status === "error" ? "text-destructive" : ""}>
                {faza.name}
                {faza.info && Object.keys(faza.info).length > 0 ? (
                  <span className="text-muted-foreground">
                    {" · "}
                    {Object.entries(faza.info)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(" · ")}
                  </span>
                ) : null}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
