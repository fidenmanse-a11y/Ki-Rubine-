"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { RubineGem } from "@/components/icons";
import { Badge, Button, Card, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import type { EngineInfo } from "@/lib/types";

type Info = { version: string; engine: EngineInfo; base_model: string; base_model_revision: string | null; license: string; sim_enabled: boolean; agent_backend: string };

export default function SettingsPage() {
  const router = useRouter();
  const [info, setInfo] = useState<Info | null>(null);
  const [standalone, setStandalone] = useState(false);
  const [secure, setSecure] = useState(false);
  const [backup, setBackup] = useState<string | null>(null);

  useEffect(() => {
    api<Info>("/api/info").then(setInfo).catch(() => undefined);
    setStandalone(window.matchMedia("(display-mode: standalone)").matches || (navigator as unknown as { standalone?: boolean }).standalone === true);
    setSecure(window.isSecureContext);
  }, []);

  return (
    <main className="mx-auto max-w-3xl px-4 pt-safe" style={{ paddingBottom: "calc(max(var(--sab),10px) + 96px)" }}>
      <header className="pb-3 pt-2">
        <h1 className="text-[30px] font-bold tracking-tight">Mehr</h1>
      </header>

      <Card className="flex items-center gap-4">
        <RubineGem size={48} />
        <div>
          <div className="text-[18px] font-semibold">Rubine AI <span className="text-fg-3">v{info?.version}</span></div>
          <div className="text-[13px] text-fg-3">Eigenes Modell auf Basis von {info?.base_model ?? "…"} ({info?.license})</div>
        </div>
      </Card>

      <Card className="mt-4" title="Status">
        <div className="space-y-1.5 text-[14px]">
          <Row k="Sprachmodell" v={<Badge tone={info?.engine.status === "ready" ? "ok" : "warn"}>{info?.engine.status ?? "…"}</Badge>} />
          <Row k="Rechengerät" v={info?.engine.device ?? "—"} />
          <Row k="Basis-Revision" v={<span className="font-mono text-[12px]">{info?.base_model_revision?.slice(0, 12) ?? "neueste"}</span>} />
          <Row k="Agenten-Denken" v={info?.agent_backend === "rubine" ? "aktives Rubine-Modell" : "OpenAI-kompatibler Server"} />
          <Row k="Als App installiert" v={standalone ? "Ja" : "Nein"} />
          <Row k="Sichere Verbindung (HTTPS)" v={secure ? "Ja" : "Nein"} />
        </div>
      </Card>

      {!standalone && (
        <Card className="mt-4" title="Auf dem iPhone installieren">
          <ol className="list-decimal space-y-1.5 pl-5 text-[14px] text-fg-2">
            <li>Diese Seite in <b>Safari</b> öffnen.</li>
            <li>Auf das Teilen-Symbol tippen (Quadrat mit Pfeil).</li>
            <li><b>„Zum Home-Bildschirm“</b> wählen und „Hinzufügen“ tippen.</li>
          </ol>
          {!secure && (
            <div className="mt-3"><Notice tone="info">
              Über http:// im WLAN funktioniert die App, aber die Offline-Ansicht (Service Worker) benötigt HTTPS. Siehe docs/IPHONE.md für HTTPS per Tailscale.
            </Notice></div>
          )}
        </Card>
      )}

      <Card className="mt-4" title="Datenschutz & Ehrlichkeit">
        <ul className="list-disc space-y-1.5 pl-5 text-[14px] text-fg-2">
          <li>Alle Chats bleiben in der lokalen Datenbank auf deinem PC.</li>
          <li>Chats werden nie ohne ausdrückliche Zustimmung pro Unterhaltung für Training genutzt.</li>
          <li>Jede Antwort im Chat stammt vom gewählten Modell – es gibt keine simulierten Antworten.</li>
          <li>Neue Modellversionen werden erst nach bestandenen Tests vorgeschlagen und nie automatisch aktiviert.</li>
        </ul>
      </Card>

      <Card className="mt-4" title="Daten">
        <Button onClick={async () => {
          const r = await api<{ path: string | null; note: string | null }>("/api/lab/backup", { method: "POST" });
          setBackup(r.path ? `Backup gespeichert: ${r.path}` : r.note);
        }}>Datenbank-Backup erstellen</Button>
        {backup && <p className="mt-2 break-all text-[12px] text-fg-3">{backup}</p>}
      </Card>

      <Button variant="danger" className="mt-6 w-full" onClick={async () => { await api("/api/auth/logout", { method: "POST" }); router.replace("/login/"); }}>
        Abmelden
      </Button>
    </main>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex items-center justify-between gap-3"><span className="text-fg-3">{k}</span><span className="text-right">{v}</span></div>;
}
