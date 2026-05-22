import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";

type ClientRow = {
  id: string;
  name: string;
  contact: string | null;
  notes: string | null;
  created_at: string;
};

export function ClientsAside({
  clients,
  activeClientId,
  newName,
  newContact,
  newNotes,
  busy,
  setNewName,
  setNewContact,
  setNewNotes,
  addClient,
  refreshClients,
  setActiveClientId,
  removeClient,
}: {
  clients: ClientRow[];
  activeClientId: string | null;
  newName: string;
  newContact: string;
  newNotes: string;
  busy: string | null;
  setNewName: (v: string) => void;
  setNewContact: (v: string) => void;
  setNewNotes: (v: string) => void;
  addClient: () => void | Promise<void>;
  refreshClients: () => void | Promise<void>;
  setActiveClientId: (id: string) => void;
  removeClient: (id: string) => void | Promise<void>;
}) {
  return (
    <aside className="space-y-3">
      <Card className="p-3">
        <h2 className="mb-2 text-sm font-semibold">Nowy klient</h2>
        <div className="space-y-2">
          <Input
            placeholder="Imię i nazwisko / firma"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <Input
            placeholder="Kontakt (e-mail / telefon)"
            value={newContact}
            onChange={(e) => setNewContact(e.target.value)}
          />
          <Textarea
            placeholder="Notatki (opcjonalnie)"
            value={newNotes}
            onChange={(e) => setNewNotes(e.target.value)}
            rows={2}
          />
          <Button onClick={addClient} disabled={busy === "client"} className="w-full" size="sm">
            {busy === "client" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Dodaj
          </Button>
        </div>
      </Card>

      <Card className="p-3">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Klienci ({clients.length})</h2>
          <Button variant="ghost" size="sm" onClick={() => void refreshClients()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
        <div className="max-h-[60vh] space-y-1 overflow-y-auto">
          {clients.length === 0 && (
            <p className="px-1 py-2 text-xs text-muted-foreground">
              Brak klientów. Dodaj pierwszego powyżej.
            </p>
          )}
          {clients.map((c) => (
            <div
              key={c.id}
              className={`group flex items-start justify-between rounded-md border px-2 py-1.5 text-sm cursor-pointer ${
                activeClientId === c.id
                  ? "border-primary bg-accent"
                  : "border-transparent hover:bg-muted"
              }`}
              onClick={() => setActiveClientId(c.id)}
            >
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{c.name}</div>
                {c.contact && (
                  <div className="truncate text-xs text-muted-foreground">{c.contact}</div>
                )}
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  void removeClient(c.id);
                }}
                className="ml-2 opacity-0 group-hover:opacity-100"
                title="Usuń"
              >
                <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
              </button>
            </div>
          ))}
        </div>
      </Card>
    </aside>
  );
}
