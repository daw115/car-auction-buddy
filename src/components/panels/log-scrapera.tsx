/** Surowe linie logu serwera — to, co scraper wypisuje w trakcie pracy.
 *
 *  Same fazy nie wystarczają: zmieniają się co kilkadziesiąt sekund, a między
 *  nimi ekran milczy i nie da się odróżnić pracy od zawieszenia. W logu widać,
 *  że scraper otwiera kolejne loty, nawet gdy faza stoi w miejscu.
 *
 *  Jeden komponent w dwóch miejscach (karta wyszukiwania i ekran aktywnych
 *  jobów), bo log jest wspólny dla całego serwera, a nie przypisany do joba —
 *  dwie kopie tego samego widoku rozjechałyby się przy pierwszej poprawce.
 */

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";

import { backendLogTail } from "@/functions/backend.functions";

const BLAD = /error|exception|traceback|failed|timeout|błąd/i;

export function LogScrapera({
  aktywny,
  domyslnieOtwarty = true,
}: {
  /** Czy coś się teraz dzieje. Bez tego odpytywalibyśmy log bez końca. */
  aktywny: boolean;
  domyslnieOtwarty?: boolean;
}) {
  const fnLog = useServerFn(backendLogTail);
  const [otwarty, setOtwarty] = useState(domyslnieOtwarty);
  const koniec = useRef<HTMLDivElement | null>(null);

  const { data } = useQuery({
    queryKey: ["log-scrapera"],
    queryFn: () => fnLog({ data: { lines: 500 } }),
    // Trzy sekundy: log przyrasta ciągle, ale częściej nie ma po co — każde
    // zapytanie dokłada własną linię do dziennika dostępu serwera.
    enabled: aktywny && otwarty,
    refetchInterval: 3000,
  });

  const linie = data?.lines ?? [];

  // Do dołu po każdej nowej porcji: bez tego broker ogląda początek listy,
  // a najświeższa linia — ta, o którą mu chodzi — jest poza ekranem.
  useEffect(() => {
    koniec.current?.scrollIntoView({ block: "nearest" });
  }, [linie.length]);

  return (
    <div className="mt-2 border-t pt-2">
      <button
        type="button"
        onClick={() => setOtwarty((o) => !o)}
        className="text-xs text-muted-foreground hover:text-foreground"
      >
        {otwarty ? "▾" : "▸"} Log scrapera{linie.length > 0 ? ` (${linie.length})` : ""}
      </button>

      {otwarty && (
        <div className="mt-1 max-h-52 overflow-y-auto rounded bg-background/60 p-1.5">
          {linie.length === 0 ? (
            <div className="font-mono text-[11px] text-muted-foreground">
              {aktywny
                ? "Cisza w logu. Scraper potrafi milczeć przez minutę, otwierając kolejny lot."
                : "Nic się teraz nie dzieje."}
            </div>
          ) : (
            <>
              {linie.map((linia, i) => (
                <div
                  key={i}
                  className={`whitespace-pre-wrap break-all font-mono text-[11px] leading-snug ${
                    BLAD.test(linia) ? "text-destructive" : "text-muted-foreground"
                  }`}
                >
                  {linia}
                </div>
              ))}
              <div ref={koniec} />
            </>
          )}
        </div>
      )}
    </div>
  );
}
