"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { IconChat, IconLab, IconSettings, IconWorld, RubineGem } from "./icons";

const TABS = [
  { href: "/", label: "Chat", Icon: IconChat },
  { href: "/world/", label: "World", Icon: IconWorld },
  { href: "/lab/", label: "AI Lab", Icon: IconLab },
  { href: "/settings/", label: "Mehr", Icon: IconSettings },
];

function TabBar() {
  const path = usePathname() || "/";
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 flex justify-center px-4"
      style={{ paddingBottom: "max(var(--sab), 10px)" }}
      aria-label="Hauptnavigation"
    >
      <div className="glass-strong flex w-full max-w-md items-center justify-between rounded-[26px] p-1.5">
        {TABS.map(({ href, label, Icon }) => {
          const active = href === "/" ? path === "/" : path.startsWith(href.replace(/\/$/, ""));
          return (
            <Link
              key={href}
              href={href}
              className={`tap relative flex flex-1 flex-col items-center justify-center gap-0.5 rounded-[20px] py-1.5 text-[11px] font-medium transition-colors ${
                active ? "text-white" : "text-fg-3"
              }`}
              aria-current={active ? "page" : undefined}
            >
              {active && <span className="absolute inset-0 rounded-[20px] bg-white/10 animate-fade" />}
              <Icon size={23} className="relative" />
              <span className="relative">{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname() || "/";
  const router = useRouter();
  const isLogin = path.startsWith("/login");
  const [state, setState] = useState<"checking" | "ok" | "offline">(isLogin ? "ok" : "checking");

  useEffect(() => {
    if (isLogin) return;
    let alive = true;
    api<{ authenticated: boolean }>("/api/auth/me")
      .then((r) => {
        if (!alive) return;
        if (!r.authenticated) router.replace("/login/");
        else setState("ok");
      })
      .catch(() => alive && setState("offline"));
    return () => { alive = false; };
  }, [isLogin, router, path]);

  useEffect(() => {
    // Service workers only work in a secure context (HTTPS or localhost).
    if ("serviceWorker" in navigator && window.isSecureContext && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);

  if (state === "checking") {
    return (
      <div className="grid min-h-dvh place-items-center">
        <RubineGem size={54} className="animate-pulse-soft" />
      </div>
    );
  }
  if (state === "offline") {
    return (
      <div className="grid min-h-dvh place-items-center px-8 text-center">
        <div className="animate-rise">
          <RubineGem size={56} className="mx-auto mb-5 opacity-80" />
          <h1 className="text-xl font-semibold">Rubine ist nicht erreichbar</h1>
          <p className="mt-2 text-[15px] text-fg-2">
            Der Rubine-Server auf deinem PC antwortet nicht. Prüfe, ob er läuft und ob dein iPhone im selben WLAN ist.
          </p>
          <button onClick={() => location.reload()} className="tap mt-6 rounded-2xl glass px-6 font-medium">Erneut versuchen</button>
        </div>
      </div>
    );
  }
  return (
    <>
      {children}
      {!isLogin && <TabBar />}
    </>
  );
}
