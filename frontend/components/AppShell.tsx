"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { IconChat, IconLab, IconPeople, IconSociety, IconWorld, RubineGem } from "./icons";

const TABS = [
  { href: "/world/", label: "Welt", Icon: IconWorld, match: ["/world"] },
  { href: "/people/", label: "Menschen", Icon: IconPeople, match: ["/people"] },
  { href: "/society/", label: "Gesellschaft", Icon: IconSociety, match: ["/society"] },
  { href: "/lab/", label: "AI Lab", Icon: IconLab, match: ["/lab", "/settings"] },
  { href: "/", label: "Chat", Icon: IconChat, match: ["/talk"] },
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
        {TABS.map(({ href, label, Icon, match }) => {
          const active = (href === "/" && path === "/") || match.some((m) => path.startsWith(m));
          return (
            <Link
              key={href}
              href={href}
              className={`tap relative flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-[20px] py-1.5 text-[10.5px] font-medium transition-colors ${
                active ? "text-white" : "text-fg-3"
              }`}
              aria-current={active ? "page" : undefined}
            >
              {active && <span className="absolute inset-0 rounded-[20px] bg-white/10 animate-fade" />}
              <Icon size={23} className="relative" />
              <span className="relative max-w-full truncate">{label}</span>
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
    // never spin forever: if the server does not answer within 10 s, show an explanation
    const slow = setTimeout(() => alive && setState((st) => (st === "checking" ? "offline" : st)), 10000);
    api<{ authenticated: boolean }>("/api/auth/me")
      .then((r) => {
        if (!alive) return;
        if (!r.authenticated) router.replace("/login/");
        else setState("ok");
      })
      .catch(() => alive && setState("offline"))
      .finally(() => clearTimeout(slow));
    return () => { alive = false; clearTimeout(slow); };
  }, [isLogin, router, path]);

  useEffect(() => {
    // Service workers only work in a secure context (HTTPS or localhost).
    if ("serviceWorker" in navigator && window.isSecureContext && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);

  // The login page must always render, even if the auth check started on another page and redirected here.
  if (state === "checking" && !isLogin) {
    return (
      <div className="grid min-h-dvh place-items-center">
        <RubineGem size={54} className="animate-pulse-soft" />
      </div>
    );
  }
  if (state === "offline" && !isLogin) {
    return (
      <div className="grid min-h-dvh place-items-center px-8 text-center">
        <div className="animate-rise">
          <RubineGem size={56} className="mx-auto mb-5 opacity-80" />
          <h1 className="text-xl font-semibold">Rubine ist nicht erreichbar</h1>
          <p className="mt-2 text-[15px] text-fg-2">
            Der Rubine-Server auf deinem PC antwortet nicht. Prüfe, ob das Fenster von Rubine-Start.bat noch offen ist.
            Steht in dessen Titelleiste „Auswählen“ oder „Markieren“, klicke hinein und drücke Esc – dann läuft Rubine weiter.
            Vom iPhone aus: gleiches WLAN wie der PC?
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
