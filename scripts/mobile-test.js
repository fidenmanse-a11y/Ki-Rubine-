// Rubine World 3.0 – mobile web-app test (Playwright, Chromium with iPhone emulation).
// Usage: node scripts/mobile-test.js <base-url> <password> [screenshot-dir]
// Note: this runs Chromium's mobile emulation (viewport, touch, DPR, user agent). It is NOT Safari/WebKit on a real iPhone.
const { chromium, devices } = require("playwright");

const BASE = process.argv[2] || "http://localhost:8000";
const PW = process.argv[3] || "";
const OUT = process.argv[4] || null;
const results = [];
const ok = (name, pass, detail = "") => { results.push({ name, pass: !!pass, detail }); console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? "  – " + detail : ""}`); };

(async () => {
  const browser = await chromium.launch();
  // ---------------------------------------------------------------- auth: no access without login
  {
    const ctx = await browser.newContext({ ...devices["iPhone 14"] });
    const p = await ctx.newPage();
    const r = await p.request.get(`${BASE}/api/world2/state`);
    ok("Auth: API ohne Login gesperrt", r.status() === 401, `HTTP ${r.status()}`);
    const r2 = await p.request.post(`${BASE}/api/lab/jobs/train`, { data: {} });
    ok("Auth: Trainings-Endpunkt ohne Login gesperrt", r2.status() === 401, `HTTP ${r2.status()}`);
    await p.goto(`${BASE}/world/`);
    await p.waitForURL(/\/login\//, { timeout: 8000 }).catch(() => undefined);
    ok("Auth: Weiterleitung zur Anmeldung", p.url().includes("/login/"), p.url());
    await ctx.close();
  }

  const ctx = await browser.newContext({ ...devices["iPhone 14"] });
  const p = await ctx.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(String(e)));
  p.on("console", (m) => { if (m.type() === "error" && !/EventSource|net::ERR_ABORTED/.test(m.text())) errors.push(m.text()); });

  await p.goto(`${BASE}/login/`);
  await p.fill("#pw", "falsch-falsch");
  await p.click("button[type=submit]");
  await p.waitForTimeout(800);
  ok("Auth: falsches Passwort abgelehnt", p.url().includes("/login/"));
  await p.fill("#pw", PW);
  await p.click("button[type=submit]");
  await p.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 10000 }).catch(() => undefined);
  ok("Auth: Anmeldung", !p.url().includes("/login/"), p.url());
  errors.length = 0; // the deliberate wrong-password attempt logs a 401 – only errors after login count

  // ---------------------------------------------------------------- PWA basics
  const man = await (await p.request.get(`${BASE}/manifest.webmanifest`)).json().catch(() => null);
  ok("PWA: Manifest (standalone, Icons)", man && man.display === "standalone" && man.icons?.length >= 2, man ? `${man.display}, ${man.icons?.length} Icons` : "fehlt");
  const touch = await p.request.get(`${BASE}/icons/apple-touch-icon.png`);
  ok("PWA: apple-touch-icon", touch.status() === 200);
  const sw = await p.request.get(`${BASE}/sw.js`);
  ok("PWA: Service-Worker-Datei", sw.status() === 200 && (await sw.text()).includes("fetch"));
  await p.goto(`${BASE}/world/`);
  await p.waitForSelector("nav[aria-label=Hauptnavigation]");
  const meta = await p.evaluate(() => ({
    capable: document.querySelector('meta[name="apple-mobile-web-app-capable"]')?.getAttribute("content"),
    status: document.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]')?.getAttribute("content"),
    viewport: document.querySelector('meta[name="viewport"]')?.getAttribute("content"),
  }));
  ok("PWA: iOS-Meta-Tags & viewport-fit=cover", meta.capable === "yes" && /viewport-fit=cover/.test(meta.viewport || ""), JSON.stringify(meta));

  // ---------------------------------------------------------------- navigation (5 tabs, touch)
  const tabs = [["Welt", "/world/"], ["Menschen", "/people/"], ["Gesellschaft", "/society/"], ["AI Lab", "/lab/"], ["Chat", "/"]];
  await p.goto(`${BASE}/world/`);
  for (const [label, path] of tabs) {
    await p.locator(`nav[aria-label=Hauptnavigation] a:has-text("${label}")`).tap();
    await p.waitForTimeout(900);
    ok(`Navigation: Tab ${label}`, new URL(p.url()).pathname === path, new URL(p.url()).pathname);
  }
  const navBox = await p.locator("nav[aria-label=Hauptnavigation] a").first().boundingBox();
  ok("Touch: Tab-Ziele ≥ 44 pt hoch", navBox && navBox.height >= 44, navBox ? `${Math.round(navBox.height)} px` : "");

  // ---------------------------------------------------------------- world map: render, FPS, live updates, touch
  await p.goto(`${BASE}/world/`);
  await p.waitForSelector("canvas[aria-label]", { timeout: 15000 });
  await p.waitForTimeout(2500);
  if (OUT) await p.screenshot({ path: `${OUT}/m-world.png` });
  const fps = [];
  for (let i = 0; i < 5; i++) { await p.waitForTimeout(1000); fps.push(await p.evaluate(() => window.__rubineFps || 0)); }
  const fpsAvg = Math.round(fps.reduce((a, b) => a + b, 0) / fps.length);
  ok("Karte: Bildrate (Chromium-Emulation, headless)", fpsAvg >= 30, `${fps.join("/")} fps, Ziel 60`);
  const t0 = await p.evaluate(async () => (await (await fetch("/api/world2/state")).json()).tick);
  await p.locator('button[aria-pressed]:has-text("100×")').tap();
  await p.waitForTimeout(4000);
  const label1 = await p.locator(".glass-strong .text-\\[15px\\]").first().innerText();
  const t1 = await p.evaluate(async () => (await (await fetch("/api/world2/state")).json()).tick);
  ok("Live: Simulation läuft nach Tippen auf 100×", t1 > t0, `Tick ${t0} → ${t1}; Anzeige ${label1}`);
  await p.locator('button[aria-pressed]:has-text("⏸")').tap();
  await p.waitForTimeout(1500);
  const st = await p.evaluate(async () => (await (await fetch("/api/world2/state")).json()));
  ok("Steuerung: Pause per Touch", st.running === false);
  // pinch zoom via synthetic touch pointers + pan
  const box = await p.locator("canvas[aria-label]").boundingBox();
  const cdp = await ctx.newCDPSession(p);
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: cx - 30, y: cy, id: 1 }, { x: cx + 30, y: cy, id: 2 }] });
  for (let k = 1; k <= 8; k++) await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: cx - 30 - k * 12, y: cy, id: 1 }, { x: cx + 30 + k * 12, y: cy, id: 2 }] });
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await p.waitForTimeout(500);
  if (OUT) await p.screenshot({ path: `${OUT}/m-world-zoom.png` });
  ok("Touch: Pinch-Zoom ohne Fehler", errors.length === 0, errors.slice(0, 2).join(" | "));
  // tap a resident on the map: follow mode centres the camera on them, then tap the centre of the map
  {
    const st2 = await p.evaluate(async () => (await (await fetch("/api/world2/state")).json()));
    const counts = {};
    st2.agents.forEach((a) => { counts[`${a.x},${a.y}`] = (counts[`${a.x},${a.y}`] || 0) + 1; });
    const lone = st2.agents.find((a) => counts[`${a.x},${a.y}`] === 1) || st2.agents[0];
    await p.goto(`${BASE}/world/?track=${lone.id}`);
    await p.waitForSelector("canvas[aria-label]");
    await p.waitForTimeout(4000);
    const b2 = await p.locator("canvas[aria-label]").boundingBox();
    await p.touchscreen.tap(b2.x + b2.width / 2, b2.y + b2.height / 2);
    const opened = await p.waitForSelector("[role=dialog]", { timeout: 5000 }).then(() => true).catch(() => false);
    const title = opened ? await p.locator("[role=dialog] h2").innerText() : "";
    ok("Karte: Bewohner antippen öffnet Profil", opened && title.startsWith(lone.name), `${lone.name} → ${title}`);
    if (OUT && opened) await p.screenshot({ path: `${OUT}/m-map-tap.png` });
    if (opened) await p.locator('[role=dialog] button[aria-label="Schließen"]').tap();
  }
  // ---------------------------------------------------------------- people, follow, inspector
  await p.goto(`${BASE}/people/`);
  await p.waitForSelector("li.card", { timeout: 10000 });
  const nPeople = await p.locator("li.card").count();
  ok("Menschen: Liste geladen", nPeople >= 10, `${nPeople} Einträge`);
  await p.locator('li.card button[aria-label="Verfolgen"]').first().tap();
  await p.waitForTimeout(900);
  await p.locator('button:has-text("Verfolgt")').first().tap();
  await p.waitForTimeout(1200);
  const nFollowed = await p.locator("li.card").count();
  ok("Menschen: Verfolgen + Filter", nFollowed === 1, `${nFollowed} verfolgt`);
  await p.locator("li.card button").first().tap();
  await p.waitForSelector("[role=dialog]", { timeout: 8000 });
  await p.waitForTimeout(1200);
  for (const t of ["Ziele & Pläne", "Innenleben", "Wissen & Urteile", "Entwicklung"]) {
    await p.locator(`[role=dialog] button:has-text("${t}")`).first().tap();
    await p.waitForTimeout(500);
  }
  const dlg = await p.locator("[role=dialog]").innerText();
  ok("Inspector: Planungs-/Innenleben-Tabs", /Was gespeichert wird/i.test(dlg), "");
  await p.locator('[role=dialog] button:has-text("Ziele & Pläne")').first().tap();
  await p.waitForTimeout(400);
  if (OUT) await p.screenshot({ path: `${OUT}/m-inspector-goals.png` });
  await p.locator('[role=dialog] button:has-text("Innenleben")').first().tap();
  await p.waitForTimeout(400);
  if (OUT) await p.screenshot({ path: `${OUT}/m-inspector-inner.png` });
  // persistence of follow state across reload
  await p.reload();
  await p.waitForSelector("li.card", { timeout: 10000 });
  await p.locator('button:has-text("Verfolgt")').first().tap();
  await p.waitForTimeout(1200);
  ok("Persistenz: Verfolgen übersteht Neuladen", (await p.locator("li.card").count()) === 1);
  await p.locator('li.card button[aria-label="Nicht mehr verfolgen"]').first().tap();
  await p.waitForTimeout(600);

  // ---------------------------------------------------------------- society views
  await p.goto(`${BASE}/society/`);
  for (const t of ["Politik", "Justiz", "Soziales", "Wirtschaft", "Bevölkerung", "Städte", "Chronik"]) {
    await p.locator(`main button:has-text("${t}")`).first().tap();
    await p.waitForTimeout(1100);
    if (OUT && ["Justiz", "Soziales", "Bevölkerung"].includes(t)) await p.screenshot({ path: `${OUT}/m-society-${t}.png`, fullPage: false });
  }
  ok("Gesellschaft: alle Bereiche ohne Fehler", errors.length === 0, errors.slice(0, 2).join(" | "));

  // ---------------------------------------------------------------- lab + chat pages
  await p.goto(`${BASE}/lab/`);
  await p.waitForTimeout(2500);
  const labText = await p.locator("main").innerText();
  ok("AI Lab: Bewohner-Test sichtbar", /Bewohner-Test/i.test(labText));
  if (OUT) await p.screenshot({ path: `${OUT}/m-lab.png` });
  await p.goto(`${BASE}/talk/`);
  await p.waitForTimeout(1500);
  ok("Bewohner-Chat: Auswahl geladen", (await p.locator("main li").count()) >= 5);

  // ---------------------------------------------------------------- responsive: no horizontal overflow
  for (const dev of ["iPhone SE", "iPhone 14", "iPhone 14 Pro Max"]) {
    const c2 = await browser.newContext({ ...devices[dev], storageState: await ctx.storageState() });
    const p2 = await c2.newPage();
    let worst = 0;
    for (const path of ["/world/", "/people/", "/society/", "/lab/", "/"]) {
      await p2.goto(`${BASE}${path}`);
      await p2.waitForTimeout(1200);
      worst = Math.max(worst, await p2.evaluate(() => document.documentElement.scrollWidth - window.innerWidth));
    }
    ok(`Responsive: kein horizontales Scrollen (${dev})`, worst <= 1, `Überstand ${worst}px`);
    await c2.close();
  }

  // ---------------------------------------------------------------- offline view + error handling
  await p.goto(`${BASE}/world/`);
  await p.waitForTimeout(1500);
  await ctx.setOffline(true);
  await p.reload().catch(() => undefined);
  await p.waitForTimeout(2500);
  const offlineText = await p.locator("body").innerText().catch(() => "");
  ok("Offline: verständliche Ansicht statt leerer Seite", /nicht erreichbar|offline|Offline/i.test(offlineText), offlineText.slice(0, 80).replace(/\n/g, " "));
  await ctx.setOffline(false);

  console.log(`\n${results.filter((r) => r.pass).length}/${results.length} bestanden`);
  if (OUT) require("fs").writeFileSync(`${OUT}/mobile-results.json`, JSON.stringify(results, null, 1));
  await browser.close();
  process.exit(results.every((r) => r.pass) ? 0 : 1);
})();
