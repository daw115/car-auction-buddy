import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { useState } from "react";
import { toast } from "sonner";
import { Users, Plus } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { listClients, createClient } from "@/functions/clients.functions";

export const Route = createFileRoute("/clients")({
  component: ClientsPage,
});

function ClientsPage() {
  const router = useRouter();
  const fnList = useServerFn(listClients);
  const fnCreate = useServerFn(createClient);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", phone: "", notes: "" });
  const [q, setQ] = useState("");

  const { data: clients = [], isLoading } = useQuery({
    queryKey: ["clients"],
    queryFn: () => fnList(),
  });

  const filtered = clients.filter((c) =>
    q ? [c.name, c.email, c.phone].some((v) => v?.toLowerCase().includes(q.toLowerCase())) : true,
  );

  const submit = async () => {
    if (!form.name.trim()) {
      toast.error("Podaj nazwę klienta");
      return;
    }
    try {
      const c = await fnCreate({
        data: {
          name: form.name.trim(),
          email: form.email.trim() || null,
          phone: form.phone.trim() || null,
          notes: form.notes.trim() || null,
        },
      });
      toast.success("Klient dodany");
      setOpen(false);
      setForm({ name: "", email: "", phone: "", notes: "" });
      router.navigate({ to: "/clients/$clientId", params: { clientId: c.id } });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Klienci"
        description="Baza klientów i ich sprawy. Każda sprawa spina wyszukiwania i może być monitorowana cyklicznie."
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4 mr-2" />
                Dodaj klienta
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Nowy klient</DialogTitle>
                <DialogDescription>Wpisz podstawowe dane. Sprawy dodasz później.</DialogDescription>
              </DialogHeader>
              <div className="space-y-3">
                <div>
                  <Label>Imię / nazwa *</Label>
                  <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                </div>
                <div>
                  <Label>Email</Label>
                  <Input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </div>
                <div>
                  <Label>Telefon</Label>
                  <Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
                </div>
                <div>
                  <Label>Notatki</Label>
                  <Textarea
                    value={form.notes}
                    onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>
                  Anuluj
                </Button>
                <Button onClick={submit}>Zapisz</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      <Input
        placeholder="Szukaj po nazwie, emailu, telefonie…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="max-w-md"
      />

      {isLoading ? (
        <div className="text-sm text-muted-foreground">Ładowanie…</div>
      ) : filtered.length === 0 ? (
        <Card className="p-8 text-center text-muted-foreground">
          <Users className="h-10 w-10 mx-auto mb-2 opacity-40" />
          Brak klientów. Dodaj pierwszego.
        </Card>
      ) : (
        <div className="grid gap-2">
          {filtered.map((c) => (
            <Link
              key={c.id}
              to="/clients/$clientId"
              params={{ clientId: c.id }}
              className="block"
            >
              <Card className="p-4 hover:shadow-md transition-shadow">
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="font-semibold truncate">{c.name}</div>
                    <div className="text-xs text-muted-foreground truncate">
                      {[c.email, c.phone].filter(Boolean).join(" • ") || "—"}
                    </div>
                  </div>
                  <Badge variant="outline" className="text-xs">
                    {c.created_by ?? "?"}
                  </Badge>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
