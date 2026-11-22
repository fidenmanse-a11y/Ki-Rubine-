# Rubine World 3.0 – autonome Gesellschaft

World 3.0 erweitert World 2.0 ([WORLD2.md](WORLD2.md)), ersetzt aber nichts: World Engine, Stoffbilanz, Ereignisprotokoll,
Persistenz, Geschwindigkeiten, Steuerung und Modellrichtlinie gelten unverändert. Alte Spielstände werden beim Laden
automatisch auf das neue Schema (3) gehoben (`world2/upgrade.py`, getestet).

> **Wichtig:** Die Bewohner sind simulierte Agenten. „Emotionen“, „Überzeugungen“ und „Pläne“ sind Zahlen und Datenstrukturen
> im Simulationszustand bzw. Ausgaben eines Sprachmodells. Es wird kein Bewusstsein und kein menschliches Erleben behauptet.
> Betrug, Lügen und Diebstahl sind abstrakte Spielzüge in der virtuellen Welt – es gibt keine realen Anleitungen.

## 1. Was ein Bewohner jetzt hat (`world2/cognition.py`)

| Baustein | Umsetzung |
|---|---|
| **Eigene Ziele** | Kandidaten entstehen aus der Lage (kein Zuhause, Hunger, Krankheit, Ehrgeiz, Familie, Wissen, Amt, Unrecht, Fehde, Ruf …). Jeder Bewohner hat eine **Agenda** mit Prioritäten und begrenzter Kapazität (2–4, je nach Denkvermögen). Ziele werden **angenommen, zurückgestellt, erreicht, aufgegeben** (bei Stillstand) oder **hinfällig** (Anlass weg). Das Sprachmodell kann (falls aktiv) das wichtigste Ziel wählen und begründen – protokolliert als Entscheidung „ziel“. |
| **Mehrschrittige Pläne** | Jedes Ziel hat einen Plan aus Schritten mit Bedingung, passenden Handlungen und **erwarteter Folge** („Dann habe ich genug Holz für den Bau“). Der **Planungshorizont** hängt vom Denkvermögen ab: kurzsichtige Bewohner sehen nur die nächsten Schritte und erweitern den Plan später. |
| **Neuplanung** | Unerwartete Ereignisse (Haus eingestürzt, Hochwasser, bestohlen, krank, verurteilt, Versprechen gebrochen …) lösen über `notify()` eine Neubewertung aus. Beispiel (Test): Haus stürzt ein → Ziel „Zuhause“ wird aktiv, Planänderung „Zuhause verloren“, nach ≤ 1 Tag neue Hütte. Läuft bereits eine andere eigene Baustelle, wird sie fertiggestellt (wenig fehlt) oder **zurückgestellt** und später wieder aufgenommen. |
| **Bedürfnisse vs. Regeln** | Handlungsnutzen = Bedürfnisse + Ziele + Emotionen + Lektionen – Moral, Angst vor Strafe (nur bei bekanntem Gesetz), Zeugen, Schuldgefühl. Niemand wird zu einer Tat gezwungen; Entscheidungen sind per Softmax unvollkommen. |
| **Simulierte Emotionen** | Freude, Ärger, Angst, Trauer, Stolz, Scham, Dankbarkeit – auch **auf Personen bezogen** (Ärger auf X, Dankbarkeit gegenüber Y). Entstehen durch Ereignisse, klingen stündlich ab. |
| **Überzeugungen & Ursachen** | Bewohner bilden kausale Überzeugungen mit Sicherheit (z. B. „Hunger macht krank“). Je höher das Denkvermögen, desto öfter wird die echte Hauptursache erkannt; sonst entstehen **Irrtümer** („Fremde bringen Krankheiten“). Der Inspektor zeigt die Entwickler-Wahrheit daneben. |
| **Wissen über andere** | Ehrlichkeitseinschätzung als Beta-Verteilung (Schätzwert **und Unsicherheit**), Verdacht, Notizen. |
| **Lernen aus Fehlern** | Lektionen verschieben den Nutzen von Handlungsarten (z. B. nach einer Verurteilung „Stehlen −0,5“, nach aufgegebenem Ziel „Ziel wissen −0,1“), vergessen langsam. |
| **Moral** | Fürsorge, Fairness, Loyalität, Autorität, Freiheit, Ehrlichkeit – unterschiedlich pro Person, beeinflussen Abstimmungen, Zeugenaussagen, Taten; Freundschaften gleichen sie langsam an. |
| **Geheimnisse** | z. B. eigene Taten oder Lügen vor Gericht; nur in der Entwickleransicht sichtbar. |

**Trennung im Inspektor („Entwicklung“):** Erinnerungen (gespeicherte Ereignisse), Lektionen/Fähigkeiten (Zahlen im Zustand)
und **echtes Modell-Feintuning** (nur über das AI Lab, betrifft alle Bewohner mit dieser Modellversion) sind getrennt ausgewiesen.

## 2. Soziale Mechanik (`world2/social3.py`)

- **Freundschaften** entstehen bei gegenseitiger Zuneigung + Vertrauen + Vertrautheit und zerbrechen wieder.
- **Versprechen** (Bauhilfe, Stimme) werden gehalten oder gebrochen; gebrochene kosten Vertrauen.
- **Überzeugen:** Erfolg hängt von Vertrauen, Führungsstärke, Offenheit und der eingeschätzten Ehrlichkeit ab; verschiebt Abstimmungsneigungen.
- **Gerüchte/Lügen:** nur bei starkem persönlichem Ärger und geringer Ehrlichkeit. Zuhörer, die die betroffene Person gut kennen,
  **widersprechen**; erreicht das Gerücht die betroffene Person, wird es **entlarvt** und die Kette fällt auf die Urheber zurück.
- **Bündnisse** mit Zweck, Abstimmungsbonus, Auflösung bei geringem Zusammenhalt; **Fehden** und **Versöhnung/Entschuldigung**.

## 3. Justiz (`world2/justice.py`)

Vorwurf → **Ermittlung** (Wache, Gründlichkeit nach Denkvermögen) → **Anklage nur bei ausreichender Beweislage**
(Unschuldsvermutung; sonst nach 3 Tagen eingestellt) → Verhandlung → Urteil → Berufung.

- **Beweise:** echte Zeugen (beobachtet), entlastende Zeugen, loyal Schweigende, **Falschaussagen** (selten: Ärger + Unehrlichkeit),
  Aussage der beschuldigten Person (Geständnis / wahrheitsgemäßes Bestreiten / Lüge). Glaubwürdigkeit nach Einschätzung des Richters.
  Beweisschwelle per Gesetz „Beweisregel“ änderbar.
- **Strafen** aus dem jeweiligen Gesetz: Rückgabe, doppelte Rückgabe, Geldstrafe, Bewährung, Arrest, Verbannung, **Haft** (nur wenn
  die Bewohner ein Gefängnis gebaut haben). Häftlinge bleiben eigenständige Agenten, werden aus der Gemeinschaftskasse versorgt
  (sonst Ereignis „Haftbedingungen“), werden entlassen; ein Gesetz „Wiedereingliederung“ verringert das Stigma.
- **Fehlurteile** werden gezählt (Entwickler-Wahrheit). **Berufung** bei Berufungsgericht oder ≥ 2 Richtern: ein anderer Richter prüft,
  deckt Falschaussagen auf (→ eigenes Meineid-Verfahren), hebt Urteile auf, Entschädigung aus der Gemeinschaftskasse.
- Alle Institutionen (Gericht, Wache, Gefängnis, Berufungsgericht) entstehen nur durch Vorschläge und Abstimmungen der Bewohner.

## 4. Welt

Neue Gebäude: **Laden, Wachhaus, Gefängnis**. Rollen: Unterrichten (Schule zählt nur an Tagen mit echtem Unterricht),
Streife, Wachdienst, Ladenbetrieb und Einkauf. **Trampelpfade:** jeder Schritt zählt in einer Verkehrskarte; viel genutzte Wege
pflastern die Bewohner selbst. **Umzug/Auswanderung** in andere Gegenden. Siedlungen mit Einwohnerzahl.
**Innenansicht** eines Gebäudes zeigt Räume und die Personen, die sich gerade wirklich dort aufhalten.

## 5. Sprachmodell der Bewohner und „Bewohner-Test“

Das Sprachmodell wählt nur zwischen gültigen Optionen („Wahl: n“); die World Engine prüft und führt aus (unverändert).
Neu ist ein **Bewohner-Test** (`world2/benchmark.py`, AI Lab): 70 klare Entscheidungssituationen aus einer eigenen Prüfwelt
(Seed 737373) in genau diesem Format, 7 Kategorien. „Anpassung“ und „Normen“ kommen in keinem Trainingsdatensatz vor
(Transfer-Test). Ergebnisse: [EXPERIMENTS.md](EXPERIMENTS.md).

Optional kann ein **größeres Open-Weight-Modell** (Qwen2.5-1.5B-Instruct, Apache-2.0, feste Revision) für die Bewohner verwendet
werden: Modellrichtlinie `default_model = "hf:Qwen/Qwen2.5-1.5B-Instruct"`. Das ist **nur erlaubt, wenn ein gespeichertes
Bewohner-Test-Ergebnis mindestens 15 Prozentpunkte über Zufall liegt** – gleiches Prinzip wie „nur geprüfte Versionen“.
Das Modell wird separat geladen (≈ 6 GB RAM in float32 auf der CPU, ≈ 3 s pro Entscheidung auf 4 Kernen).

## 6. Mobile Web-App

Fünf Bereiche: **Welt** (Vollbild-Karte, Pinch/Pan, Tag/Nacht, Wetter, Geschwindigkeit, Live-Ticker, Wege-Ebene, Verfolgen-Modus,
Gebäude-Innenansicht), **Menschen** (Suche, Filter, Verfolgen), **Gesellschaft** (Politik, Justiz, Soziales, Wirtschaft,
Bevölkerung & Bildung, Städte, Chronik), **AI Lab** (inkl. Bewohner-Test, Einstellungen), **Chat** (Rubine-Chat und
**Gespräch mit Bewohnern**). Gespräche ändern die Welt nicht – außer man speichert sie ausdrücklich als Erinnerung; das wird als
Entwickler-Eingriff im Ereignisprotokoll vermerkt.

## 7. API (alle Endpunkte nur nach Anmeldung)

| Endpunkt | Inhalt |
|---|---|
| `GET /api/world2/agents/{id}` | wie bisher + `mind` (Agenda mit Planschritten, Emotionen, Überzeugungen mit Entwickler-Wahrheit, Einschätzungen, Lektionen, Entwicklung, Versprechen, Bündnisse, Fehden, Haft, Herkunft der Entscheidungen) |
| `GET /api/world2/agents/{id}/mind` | nur der Innenzustand |
| `GET /api/world2/people?q=&filter=&sort=` | Liste mit Filtern (verfolgt, Ämter, Haft, krank, ohne Zuhause, Kinder, verstorben) |
| `GET/POST /api/world2/follow` | Verfolgen-Liste (UI-Einstellung, beeinflusst die Simulation nicht) |
| `GET /api/world2/society3` | Justiz (Fälle mit Phasen, Berufungen, Fehlurteile, Gefängnisse), Bündnisse, Fehden, Versprechen, Gerüchte, Bildung, Siedlungen |
| `GET /api/world2/buildings/{id}/interior` | Räume und anwesende Personen |
| `POST /api/world2/agents/{id}/chat` | Gespräch (SSE-Streaming), `remember: true` = Entwickler-Eingriff |
| `POST/GET /api/lab/agent-bench` | Bewohner-Test starten / Ergebnisse |
| `POST /api/lab/data/simulation` mit `resident_decisions: true` | Entscheidungsbeispiele aus separaten Trainingswelten |
