# Rubine auf dem iPhone

Rubine läuft auf deinem PC. Das iPhone zeigt die Oberfläche als installierbare Web-App (PWA) – **keine native App, kein App Store**.
Unten: fünf Bereiche **Welt · Menschen · Gesellschaft · AI Lab · Chat**. Einstellungen erreichst du im AI Lab oben rechts.

## Was wie getestet wurde – und was nicht

| Geprüft | Wie |
|---|---|
| Layout iPhone SE, 14, 14 Pro Max (kein horizontales Scrollen), Safe Areas | Playwright/Chromium mit Geräte-Emulation (`scripts/mobile-test.js`, 31/31 bestanden) |
| Touch: Tabs, Pinch-Zoom, Bewohner auf der Karte antippen, Bottom-Sheets, Tippziele ≥ 44 pt | dito, echte Touch-Ereignisse über das DevTools-Protokoll |
| Kartenleistung | 44–60 fps in der Emulation (headless, 4 CPU-Kerne, Server lief parallel) |
| Live-Updates, Pause/Geschwindigkeit, Verfolgen übersteht Neuladen, Offline-Seite, Login/Sperre ohne Login | dito |
| Manifest, Icons, apple-touch-icon, Startbildschirme, `viewport-fit=cover`, Service Worker | dito + Dateiprüfung |

**Nicht getestet: echtes Safari/WebKit auf einem echten iPhone.** In dieser Entwicklungsumgebung gibt es weder ein iPhone noch
WebKit. Chromium-Emulation bildet Bildschirmgröße, Pixeldichte, Touch und User-Agent nach, aber nicht Safaris Eigenheiten
(z. B. Verhalten der Adressleiste, PWA-Startbildschirme, Speicherlimits, tatsächliche Bildrate auf dem A-Chip).
Bitte melde Auffälligkeiten auf dem echten Gerät. Den Test kannst du selbst laufen lassen:
`node scripts/mobile-test.js http://localhost:8000 <dein-passwort> [ordner-für-screenshots]`.

Ein beim Test gefundener echter Fehler wurde behoben: Nach einem Tippen öffnete sich ein Profil und schloss sich sofort wieder,
weil der Browser nach dem Touch ein künstliches „click“ auf den Hintergrund des gerade geöffneten Blatts sendet („Ghost Click“).

## Im Heim-WLAN (HTTP)

1. **Rubine-Start.bat** starten. Im Fenster steht z. B. `iPhone/WLAN: http://192.168.178.23:8000`.
   Die Adresse findest du sonst mit `ipconfig` (IPv4-Adresse des WLAN-Adapters).
2. **Firewall** (einmalig, als Administrator): `powershell -ExecutionPolicy Bypass -File scripts\allow-firewall.ps1`
   Die Regel gilt nur für das Profil **Privat**. Stelle dein Heim-WLAN unter *Einstellungen → Netzwerk und Internet → WLAN →
   (dein Netz) → Netzwerkprofiltyp* auf **Privat**.
3. iPhone im selben WLAN, **Safari** öffnen, Adresse eingeben, anmelden.
4. **Teilen** (Quadrat mit Pfeil) → **Zum Home-Bildschirm** → Hinzufügen. Rubine startet ab jetzt im Vollbild mit eigenem Icon.

### Fehlersuche

| Problem | Lösung |
|---|---|
| Seite lädt nicht | Läuft das Startfenster? Gleiches WLAN (kein Gäste-WLAN mit Client-Isolation)? Firewall-Regel angelegt? VPN auf dem iPhone aus? |
| „Rubine ist nicht erreichbar“ | Server läuft nicht oder IP hat sich geändert (Router vergibt neue IP → im Router eine feste IP für den PC reservieren). |
| Login klappt, dann wieder Login-Seite | Cookies in Safari blockiert? *Einstellungen → Safari → Alle Cookies blockieren* aus. |
| „Modell wird geladen“ | Nach dem Start dauert das Laden 5–30 s. |
| Kopieren-Knopf | Funktioniert auch über HTTP (Fallback), ohne HTTPS fragt iOS ggf. nach. |

### Was über HTTP nicht geht

Service Worker (und damit die **Offline-Ansicht**) erfordern HTTPS. Über `http://192.168…` funktioniert die App vollständig,
nur zeigt Safari bei ausgeschaltetem PC eine Standard-Fehlerseite statt der Rubine-Offline-Seite.

## Von unterwegs und mit HTTPS (empfohlen: Tailscale)

[Tailscale](https://tailscale.com) baut ein privates, verschlüsseltes Netz zwischen deinen Geräten auf – ohne Portfreigabe
im Router und ohne Rubine öffentlich ins Internet zu stellen.

1. Tailscale auf PC und iPhone installieren, mit demselben Konto anmelden.
2. In der Tailscale-Admin-Konsole **MagicDNS** und **HTTPS Certificates** aktivieren.
3. Auf dem PC (Rubine läuft auf Port 8000):
   ```
   tailscale serve --bg 8000
   ```
   Tailscale zeigt eine Adresse wie `https://mein-pc.tailXXXX.ts.net` mit gültigem Zertifikat.
4. Falls Tailscale den Host-Header umschreibt und Aktionen mit „Ungültige Herkunft“ scheitern, in `.env` ergänzen:
   `RUBINE_ALLOWED_ORIGINS=["https://mein-pc.tailXXXX.ts.net"]` und Rubine neu starten.
5. Auf dem iPhone diese HTTPS-Adresse in Safari öffnen und zum Home-Bildschirm hinzufügen. Jetzt funktionieren auch Offline-Ansicht
   und das Secure-Flag des Session-Cookies.

Alternative: eigenes Zertifikat (z. B. mit `mkcert`, dessen Root-Zertifikat auf dem iPhone installiert und unter
*Einstellungen → Allgemein → Info → Zertifikatsvertrauenseinstellungen* aktiviert werden muss) und in `.env`
`RUBINE_SSL_CERTFILE` / `RUBINE_SSL_KEYFILE` setzen.

**Nicht empfohlen:** Port 8000 im Router freigeben. Rubine hat zwar Login und Rate-Limit, ist aber als privates Werkzeug
gedacht. Für einen öffentlichen Server siehe [DEPLOYMENT.md](DEPLOYMENT.md).
