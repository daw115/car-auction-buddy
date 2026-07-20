import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { useState } from "react";
import { toast } from "sonner";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
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
import {
  getClient,
  updateClient,
  deleteClient,
  listCases,
  createCase,
} from "@/functions/clients.functions";

export const Route = createFileRoute("/clients/$clientId")({
  component: ClientDetailPage,
});

function ClientDetailPage() {
  const { clientId } = Route.useParams();
  const router = useRouter();
  const qc = useQueryClient();

  const fnGet = useServerFn(getClient);
  const fnUpdate = useServerFn(updateClient);
  const fnDelete = useServerFn(deleteClient);
  const fnListCases = useServerFn(listCases);
  const fnCreateCase = useServerFn(createCase);

  const { data: client, isLoading } = useQuery({
    queryKey: ["client", clientId],
    queryFn: () => fnGet({ data: { id: clientId } }),
  });

  const { data: cases = [] } = useQuery({
    queryKey: ["cases", clientId],
    queryFn: () => fnListCases({ data: { clientId } }),
  });

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", phone: "", notes: "" });
  const [caseOpen, setCaseOpen] = useState(false);
  const [caseForm, setCaseForm] = useState({ title: "", description: "" });

  const startEdit = () => {
    if (!client) return;
    setForm({
      name: client.name,
      email: client.email ?? "",
      phone: client.phone ?? "",
      notes: client.notes ?? "",
    });
    setEditing(true);
  };

  const saveEdit = async () => {
    try {
      await fnUpdate({
        data: {
          id: clientId,
          name: form.name.trim(),
          email: form.email.trim() || null,
          phone: form.phone.trim() || null,
          notes: form.notes.trim() || null,
        },
      });
      toast.success("Zapisano");
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["client", clientId] });
      qc.invalidateQueries({ queryKey: ["clients"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const doDelete = async () => {
    if (!confirm("Usunąć klienta wraz ze wszystkimi sprawami?")) return;
    try {
      await fnDelete({ data: { id: clientId } });
      toast.success("Klient usunięty");
      router.navigate({ to: "/clients" });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const submitCase = async () => {
    if (!caseForm.title.trim()) {
      toast.error("Podaj tytuł sprawy");
      return;
    }
    try {
      const c = await fnCreateCase({
        data: {
          client_id: clientId,
          title: caseForm.title.trim(),
          description: caseForm.description.trim() || null,
        },
      });
      toast.success("Sprawa dodana");
      setCaseOpen(false);
      setCaseForm({ title: "", description: "" });
      router.navigate({
        to: "/clients/$clientId/cases/$caseId",
        params: { clientId, caseId: c.id },
      });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  if (isLoading) return <div className="text-sm text-muted-foreground">Ładowanie…</div>;
  if (!client) return <div className="text-sm text-muted-foreground">Klient nie znaleziony.</div>;

  return (
    <div className="space-y-4">
      <Link to="/clients" className="text-sm text-muted-foreground hover:text-foreground inline-flex items-center gap-1">
        <ArrowLeft className="h-3 w-3" /> Wszyscy klienci
      </Link>
      <PageHeader
        title={client.name}
        description={[client.email, client.phone].filter(Boolean).join(" • ") || "Brak danych kontaktowych"}
        actions={
          <div className="flex gap-2">
            {!editing && (
              <Button variant="outline" onClick={startEdit}>
                Edytuj
              </Button>
            )}
            <Button variant="destructive" onClick={doDelete}>
              <Trash2 className="h-4 w-4 mr-2" />
              Usuń
            </Button>
          </div>
        }
      />

      {editing ? (
        <Card className="p-4 space-y-3">
          <div>
            <Label>Nazwa</Label>
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
            <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>
          <div className="flex gap-2">
            <Button onClick={saveEdit}>Zapisz</Button>
            <Button variant="outline" onClick={() => setEditing(false)}>
              Anuluj
            </Button>
          </div>
        </Card>
      ) : client.notes ? (
        <Card className="p-4 text-sm whitespace-pre-line">{client.notes}</Card>
      ) : null}

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Sprawy ({cases.length})</h2>
        <Dialog open={caseOpen} onOpenChange={setCaseOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <Plus className="h-4 w-4 mr-2" />
              Nowa sprawa
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Nowa sprawa</DialogTitle>
              <DialogDescription>Domyślne kryteria uzupełnisz w widoku sprawy.</DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              <div>
                <Label>Tytuł *</Label>
                <Input
                  value={caseForm.title}
                  onChange={(e) => setCaseForm({ ...caseForm, title: e.target.value })}
                  placeholder="np. Tesla Model 3 do 20k"
                />
              </div>
              <div>
                <Label>Opis</Label>
                <Textarea
                  value={caseForm.description}
                  onChange={(e) => setCaseForm({ ...caseForm, description: e.target.value })}
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setCaseOpen(false)}>
                Anuluj
              </Button>
              <Button onClick={submitCase}>Dodaj</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {cases.length === 0 ? (
        <Card className="p-6 text-center text-sm text-muted-foreground">
          Ten klient nie ma jeszcze spraw.
        </Card>
      ) : (
        <div className="grid gap-2">
          {cases.map((c) => (
            <Link
              key={c.id}
              to="/clients/$clientId/cases/$caseId"
              params={{ clientId, caseId: c.id }}
              className="block"
            >
              <Card className="p-4 hover:shadow-md transition-shadow">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-semibold truncate">{c.title}</div>
                    {c.description && (
                      <div className="text-xs text-muted-foreground truncate">{c.description}</div>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant={c.status === "open" ? "default" : "outline"}>{c.status}</Badge>
                    {c.auto_refresh_enabled && (
                      <Badge variant="outline" className="text-xs">
                        🔄 {c.auto_refresh_interval_hours}h
                      </Badge>
                    )}
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
