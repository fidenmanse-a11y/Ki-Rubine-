"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { RubineGem } from "@/components/icons";
import { Button, inputCls, Notice } from "@/components/ui";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api("/api/auth/login", { method: "POST", json: { password: pw } });
      router.replace("/");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-6 pt-safe pb-safe">
      <form onSubmit={submit} className="w-full max-w-sm animate-rise">
        <div className="mb-10 text-center">
          <RubineGem size={72} className="mx-auto drop-shadow-[0_10px_40px_rgba(139,92,246,0.55)]" />
          <h1 className="mt-6 text-[34px] font-bold tracking-tight">Rubine</h1>
          <p className="mt-1 text-[15px] text-fg-2">Deine eigene KI. Privat auf deinem PC.</p>
        </div>
        <div className="glass rounded-[24px] p-5">
          <label className="mb-2 block text-[13px] font-medium text-fg-2" htmlFor="pw">Passwort</label>
          <input
            id="pw"
            type="password"
            autoComplete="current-password"
            className={inputCls}
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            placeholder="Rubine-Passwort"
            autoFocus
          />
          {err && <div className="mt-3"><Notice tone="bad">{err}</Notice></div>}
          <Button type="submit" variant="primary" className="mt-4 w-full" loading={busy} disabled={!pw}>
            Anmelden
          </Button>
        </div>
        <p className="mt-6 text-center text-[12px] text-fg-3">
          Das Passwort steht in der Datei <span className="font-mono">.env</span> auf deinem PC (RUBINE_ADMIN_PASSWORD).
        </p>
      </form>
    </main>
  );
}
