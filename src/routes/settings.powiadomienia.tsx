/** Powiadomienia z nasłuchów — jedyny kanał, którym backend odzywa się sam.
 *
 *  Nasłuchy aukcji chodzą w nocy i zgłaszają trafienia Telegramem. Trzy endpointy
 *  administracyjne istniały od dawna i nie były wołane przez nic, więc broker nie
 *  miał jak sprawdzić, czy bot działa, kto jest zapisany ani czy wiadomości w ogóle
 *  dochodzą — dowiadywał się o awarii przez ciszę, która wygląda jak brak trafień.
 *
 *  Powiadomienia idą DO BROKERA. Do klienta nic stąd nie wychodzi.
 */

import { createFileRoute } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Send, Trash2 } from "lucide-react";

import {
  backendTelegramRemoveSubscriber,
  backendTelegramStatus,
  backendTelegramTest,
} from "@/functions/backend.functions";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export const Route = createFileRoute("/settings/powiadomienia")({
  component: PowiadomieniaPage,
});

function PowiadomieniaPage() {
  const fnStatus = useServerFn(backendTelegramStatus);
  const fnTest = useServerFn(backendTelegramTest);
  const fnUsun = useServerFn(backendTelegramRemoveSubscriber);
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["telegram-status"],
    queryFn: () => fnStatus(),
  });

  const test = useMutation({
    mutationFn: () => fnTest(),
    onSuccess: (wynik) =>
      wynik.sent === false
        ? toast.warning(wynik.detail || "Backend nie wysłał wiadomości.")
        : toast.success(
            "Wysłane — sprawdź Telegrama. Jeśli nic nie przyszło, bot nie ma odbiorcy.",
          ),
    onError: (e: { message?: string }) => toast.error(e.message || "Nie udało się wysłać."),
  });

  const subskrybenci = data?.subscribers ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Powiadomienia"
        description="Nasłuchy aukcji zgłaszają trafienia Telegramem. Tu sprawdzisz, czy ten kanał żyje."
      />

      <Card className="p-4">
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm font-medium">Bot</span>
              {data?.configured ? (
                <Badge className="bg-success text-success-foreground">skonfigurowany</Badge>
              ) : (
                <Badge variant="destructive">brak konfiguracji</Badge>
              )}
              {data?.bot_username ? (
                <span className="text-sm text-muted-foreground">@{data.bot_username}</span>
              ) : null}
              <Button
                size="sm"
                variant="outline"
                disabled={!data?.configured || test.isPending}
                onClick={() => test.mutate()}
              >
                {test.isPending ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Send className="mr-1.5 h-3.5 w-3.5" />
                )}
                Wyślij test
              </Button>
            </div>

            {data?.error ? <p className="mt-2 text-sm text-destructive">{data.error}</p> : null}

            {!data?.configured ? (
              <p className="mt-3 text-sm text-muted-foreground">
                Bez tokena bota nasłuchy działają, ale nie mają jak Cię zawiadomić — trafienia
                zobaczysz dopiero na karcie klienta, w sekcji „Ostatnio wyłowione”. Token ustawia
                się na serwerze w <code>/etc/usacar/api.env</code>.
              </p>
            ) : (
              <div className="mt-4">
                <div className="mb-2 text-sm font-medium">
                  Kto dostaje powiadomienia ({subskrybenci.length})
                </div>
                {subskrybenci.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Nikt. Bot działa, ale nie ma komu pisać — wejdź na czat z botem i wyślij{" "}
                    <code>/start</code>, żeby się zapisać.
                  </p>
                ) : (
                  <div className="space-y-1">
                    {subskrybenci.map((s) => (
                      <div
                        key={String(s.chat_id)}
                        className="flex items-center justify-between rounded border p-2 text-sm"
                      >
                        <span>
                          {s.name || "bez nazwy"}{" "}
                          <span className="text-xs text-muted-foreground">({s.chat_id})</span>
                        </span>
                        <Button
                          size="sm"
                          variant="ghost"
                          title="Wypisz z powiadomień"
                          onClick={() =>
                            fnUsun({ data: { chatId: s.chat_id } })
                              .then(() => {
                                toast.success("Wypisany.");
                                qc.invalidateQueries({ queryKey: ["telegram-status"] });
                              })
                              .catch((e: { message?: string }) =>
                                toast.error(e.message || "Nie udało się wypisać."),
                              )
                          }
                        >
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
