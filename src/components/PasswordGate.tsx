import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { Lock } from "lucide-react";

// Zmień to hasło na własne. Po zmianie wszyscy zalogowani będą musieli wpisać je ponownie.
const SITE_PASSWORD = "carbuddy2026";
const STORAGE_KEY = "site_access_v1";

async function sha256(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function PasswordGate({ children }: { children: React.ReactNode }) {
  const [unlocked, setUnlocked] = useState<boolean | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [expectedHash, setExpectedHash] = useState<string>("");

  useEffect(() => {
    let mounted = true;
    sha256(SITE_PASSWORD).then((hash) => {
      if (!mounted) return;
      setExpectedHash(hash);
      const stored = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
      setUnlocked(stored === hash);
    });
    return () => {
      mounted = false;
    };
  }, []);

  if (unlocked === null) return null;
  if (unlocked) return <>{children}</>;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const hash = await sha256(value);
    if (hash === expectedHash) {
      localStorage.setItem(STORAGE_KEY, hash);
      setUnlocked(true);
    } else {
      setError("Nieprawidłowe hasło");
      setValue("");
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <Card className="w-full max-w-sm p-6">
        <div className="flex flex-col items-center text-center mb-4">
          <div className="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center mb-3">
            <Lock className="h-5 w-5 text-primary" />
          </div>
          <h1 className="text-lg font-semibold">Strona chroniona hasłem</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Podaj hasło dostępu, aby kontynuować.
          </p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="site-password">Hasło</Label>
            <Input
              id="site-password"
              type="password"
              autoFocus
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                setError("");
              }}
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
          <Button type="submit" className="w-full" disabled={!value}>
            Wejdź
          </Button>
        </form>
      </Card>
    </div>
  );
}
