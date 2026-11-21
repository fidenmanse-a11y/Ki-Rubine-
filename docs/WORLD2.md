# Rubine World 2.0 – Architektur, Regeln und Grenzen

> **Wichtig:** Die Bewohner sind simulierte Agenten. Ihre Innenzustände (Hunger, Stress, Zufriedenheit, Pläne, Begründungen)
> sind Zahlen und Texte von Regeln bzw. eines Sprachmodells – keine nachweisbaren Gedanken, Gefühle oder ein Bewusstsein.
> Die Oberfläche kennzeichnet das überall („Simulierter Agent“, „modellgeneriert“, „Regeln“).

## 1. Analyse von Rubine 0.1 (Ausgangspunkt)

| Komponente 0.1 | Weiterverwendet? | Begründung |
|---|---|---|
| ModelEngine (Basismodell + LoRA, Prioritäts-Lock) | **ja** | Bewohner denken mit demselben lokalen Modell; Chat behält Vorrang |
| Modell-Registry (bestanden/aktiv/Rollback) | **ja** | Grundlage der Modellrichtlinie für Agenten |
| Trainingspipeline (Pool, Datensätze, Trainer, Gate, Jobs) | **ja, erweitert** | neue Quelle `sim_gold`, Job `sim_export`, zweites Eval-Set |
| Sicherheitsfilter (Prompt Injection) | **ja** | jede Modellausgabe wird gefiltert |
| Klassische Smallville-Welt (`world/`) | **erhalten, optional** | feste Berufe, ein vorgegebener Bürgermeister, keine Wirtschaft – widerspricht „keine vorgegebene Hierarchie“. Läuft weiter mit `RUBINE_SIM_ENABLED=true` (Seite `/world/classic`) |
| UI-Bausteine, SSE, PWA | **ja** | neue Welt-Seite nutzt dieselben Komponenten |

## 2. Aufbau

```
backend/rubine/world2/
  rules.py         Physik der Welt: Zeit, Güter, Bedürfnisse, Gelände, Technologien, Gebäude, Gesetzeswirkungen
  mapgen.py        Seeded Kartengenerator (72×48): See, Flüsse zum See, Gebirge, Klimazonen, 7 Regionen, Ressourcen
  state.py         Weltzustand, Ledger (Erhaltungssatz), Ereignis-Log, Gedächtnis, Wissen, Beziehungen, Snapshot
  genesis.py       Neue Welt: 25 Bewohner, keine Regierung/Gesetze/Geld/Gebäude
  env.py           Wetter je Region, Temperatur, Flusspegel, Hochwasser, Nachwachsen, Verfall, Verderb, Heizen
  perception.py    Wahrnehmung (eigene Karte im Kopf), A*-Wegfindung
  life.py          Bedürfnisse, Stress, Gesundheit, Krankheit, Alter, Tod, Geburt, Kindheit/Bildung
  construction.py  Bauplätze, Material, Arbeit, Bauzeit, Siedlungserkennung
  economy.py       Bewertungen, Tausch, Preise, Steuern, Arbeit, Kredite, Währung
  society.py       Gespräche/Informationen, Vorschläge, Abstimmungen, Regierungen, Gesetze, Justiz, Familie, Erbe, Kultur
  actions.py       Optionen je Bewohner (aus eigenem Wissen), Nutzenbewertung, Ausführung durch die Engine
  mind.py          Sprachmodell-Schicht: wählt nur aus validierten Optionen; Tagesplan, Dialog, Benennung, Reflexion
  engine.py        Tick-Reihenfolge, Tagesroutinen, Statistik
  store.py         Eigene SQLite-Datei je Welt: atomare Checkpoints, Ereignisse, Archiv, Entscheidungen, Statistik
  service.py       Hintergrund-Thread, Geschwindigkeiten, Steuerung, Backups, mehrere Welten, Modellrichtlinie
  api.py           /api/world2 (alle Endpunkte mit Login)
  export.py        Verifizierte Trainingsaufgaben aus der Simulation + separate Evaluationswelt
```

### Zeit
1 Tick = 15 simulierte Minuten. Ein Tag hat 96 Ticks. **Komprimierter Kalender:** 1 Jahr = 4 Jahreszeiten × 7 Tage = 28 Tage
(sonst wären Generationen nicht beobachtbar). Geschwindigkeiten: ⏸, 1× (1 Sim-Minute/Sekunde), 5×, 20×, 100×.
Ticks werden **nie übersprungen**: Ist die Rechenzeit knapp, läuft die Welt langsamer als das Ziel (die Steuerung zeigt Ist- und Soll-Rate).

### Entscheidungsablauf eines Bewohners
1. **Wahrnehmen** – Umgebung im Sichtradius, nur selbst Gesehenes landet in der eigenen Karte.
2. **Bedürfnisse prüfen** – Hunger, Durst, Energie, Kälte, Gesundheit, Einsamkeit, Stress.
3. **Erinnern** – Langzeitgedächtnis (Stärke verblasst; Wichtiges hält länger, Abrufen stärkt), soziales Gedächtnis, Wissen mit Quelle.
4. **Optionen bewerten** – nur Handlungen, die mit eigenem Wissen möglich sind (bekannte Ressourcen, eigene Technik, Personen in der Nähe).
5. **Ziele/Persönlichkeit/Werte** gewichten den Nutzen; die Tagesabsicht verschiebt Kategorien.
6. **Wählen** – Softmax: Der beste Nutzen ist am wahrscheinlichsten, aber impulsivere/gestresste Personen weichen öfter ab
   (kein Zufallsdrama, sondern zustandsabhängige Unvollkommenheit). Bei knappen, bedeutsamen Entscheidungen
   (Bauen, Vorschlagen, Partnerschaft, Kind, Einstellen, Stehlen, Protest …) wird – im Rahmen eines Budgets – das Sprachmodell gefragt.
7. **Ausführen** – ausschließlich durch die Engine (Wege, Material, Dauer, Ledger).
8. **Ergebnis beobachten**, 9. **Erinnerung/Beziehungen aktualisieren**, 10. **Neu planen** (Tagesplan morgens, Reflexion abends).

Das Sprachmodell kann **nichts** direkt verändern. Es erhält eine nummerierte Liste gültiger Optionen und antwortet „Wahl: n“.
Ungültige oder verspätete Antworten → Regelentscheidung. Jede Entscheidung wird mit Entscheider und Modellversion protokolliert.

## 3. Regeln der Welt (Auszug)

- **Güter** (Nahrung, Holz, Stein, Kräuter, Werkzeug, Medizin, Münzen) sind ganze Zahlen. Sie entstehen nur aus Natur
  (Kachelbestand sinkt), Herstellung (Rohstoffe werden verbraucht) oder Münzprägung nach einer Institutionsregel und verschwinden
  nur durch Verbrauch (Essen, Heizen, Bauen, Verderb, Einsturz). `audit()` prüft den Erhaltungssatz.
- **Ressourcen sind begrenzt**: Abgeholzte Wälder werden zu Rodungen (Ackerfähigkeit ↑) und wachsen erst nach ~3 Jahren nach;
  Fisch, Sammelgut und Kräuter wachsen langsam nach (nicht im Winter, Sammelgut kaum bei Dürre).
- **Wetter je Region** (Markov-Prozess nach Jahreszeit); Starkregen hebt den Flusspegel; > 1,0 → **Hochwasser** beschädigt Gebäude
  am Fluss, außer ein **Damm** schützt die Umgebung.
- **Gebäude** brauchen gültigen Bauplatz, alle Materialien vor Arbeitsbeginn, Arbeitsstunden (Bauen-Fähigkeit, Werkzeug, Energie),
  und verfallen täglich (Sturm beschleunigt). Erst nach Fertigstellung existieren sie. **Siedlungen** werden erkannt, wenn ≥ 3 Wohngebäude
  innerhalb von 5 Feldern stehen.
- **Gesundheit**: Hunger/Durst/Kälte/Krankheit senken, Versorgung erhöht. Krankheiten hängen von Ernährung, Kälte, Stress, Alter,
  Wasserzugang und Ansteckung ab; Behandlung durch Heilkundige beschleunigt Genesung; schwere Verläufe können chronisch werden.
  **Sterblichkeit** steigt mit dem Alter (Gompertz) und schlechter Gesundheit. **Tod ist endgültig** (keine Wiederkehr; ID, Biografie,
  archivierte Erinnerungen und Wirkungen bleiben).
- **Familien**: Partnerschaften entstehen nur bei gegenseitiger Zuneigung/Vertrauen und Zustimmung; Kinderwunsch ist eine
  gemeinsame Entscheidung; Kinder erben Persönlichkeit als Mischung + Abweichung, lernen von Eltern, in Schulen schneller;
  mit 18 werden sie eigenständig. Haushalte versorgen Kleinkinder aus Vorräten.
- **Wirtschaft**: Preise entstehen aus den Reservationswerten zweier Parteien (Bedarf, Vorrat, Persönlichkeit) und Verhandlungsmacht;
  Märkte speichern gleitende Durchschnittspreise. Unehrliche Personen können beim Tausch betrügen (entdeckbar). Arbeitsverträge mit
  täglichem Lohn – bleibt er aus, ist das ein Vertragsbruch; Kredite mit Fälligkeit und Zahlungsausfall.
- **Politik – nur Mechanismen, keine Inhalte**: Vorschläge werden öffentlich gemacht und von denen abgestimmt, die davon wissen.
  Ohne Regierung gilt eine **Gründungsregel** der Engine (Ja > Nein und Ja ≥ max(3, 30 % der Erwachsenen der Region)).
  Bewohner können Regierungsformen gründen (Versammlung, Rat mit Wahlen, gewähltes oder erbliches Oberhaupt), Gesetze mit
  mechanischer Wirkung beschließen (Eigentumsschutz, Gewaltverbot, Abgabe, Grundversorgung, Ressourcenschutz, Erbrecht,
  Schulpflicht, Gesundheitsversorgung), Institutionen (Gericht, Wache, Schule, Gesundheitsamt), Währungen, öffentliche Bauprojekte
  und Feste. Legitimität ergibt sich aus Zufriedenheit, Vertrauen in die Führung und Abstimmungserfahrung. Bei geringer Legitimität
  kann eine **Mehrheit aller Erwachsenen** die Ordnung ändern (Engine-Regel).
- **Justiz**: Taten sind objektive Ereignisse; Zeugen wissen nur, was sie gesehen haben; Opfer bemerken Verluste später und
  beschuldigen ggf. die falsche Person. **Behauptung ≠ Ermittlung ≠ Urteil.** Gerichte urteilen nach Zeugenaussagen; Aussagen, die eine
  andere Person als Täter nennen, entlasten. Ohne Institution: Konfrontation, ggf. Eskalation (abstrakt, nicht grafisch).
- **Information**: Fakten tragen ihre Quelle (beobachtet, erzählt, Gerücht, Aushang, Zeitung) und Sicherheit; jede Weitergabe senkt
  die Sicherheit. Aushänge an Versammlungshalle/Markt, Zeitungen (private Gründung) verbreiten Öffentliches.
- **Wissen & Kultur**: 15 Technologien mit Voraussetzungen; Forschen kostet Zeit; Wissen wird gelehrt, aufgeschrieben und gelesen.
  Kunstwerke (Titel ggf. modellgeneriert), Feste werden nach zweimaliger Feier zur Tradition.

## 4. Persistenz, Steuerung, Sicherheit

- Jede Welt hat eine eigene Datei `data/worlds/<id>/world.db`. Ein Checkpoint (alle 200 Ticks / 30 s, bei Pause/Stopp/Beenden)
  schreibt **in einer Transaktion** Ereignisse, Gedächtnisarchiv, Entscheidungen, Statistik und einen komprimierten Snapshot.
  Nach Laden läuft die Welt **bitgenau** weiter (Test: `test_memories_and_world_survive_restart`).
- Steuerung: Start, Pause, Stopp, Geschwindigkeit, Speichern, Backup (SQLite-Backup-API), neue getrennte Welt, Weltwechsel,
  Fehlerprotokoll, Grenzen (Bevölkerung, Gedächtnis, Modellanfragen), automatische Pause bei Fehlerhäufung.
- **Modellkontrolle**: Bewohner denken nur mit getesteten Versionen (Basis oder „bestanden“); eine **Testgruppe** (≤ 8 Bewohner)
  erlaubt schrittweise Einführung. Neue Chat-Aktivierungen ändern die Agenten nicht automatisch. Jede Entscheidung speichert
  Entscheider und Modellversion.
- Bewohner haben **keinen** Zugriff auf echte Aktionen (Netzwerk, Dateien, Zahlungen, Befehle). Simulierte Gesetze und
  Institutionen können die Entwicklersteuerung nicht beeinflussen.

## 5. Training aus der Simulation

`AI Lab → Daten hinzufügen → Aus Rubine World` startet den Job `sim_export`:
1. **Erfassung** aus der Welt-Datenbank, 2. **Qualitätskontrolle** (Filter, Länge), 3. **Verifikation** – die Antwort berechnet
die Engine aus echten Datensätzen (Tauschpreise, Stimmzählung, Vorratsplanung, Behauptung vs. Beobachtung), jede Aufgabe muss
gegen ihre Musterlösung bestehen, 4. **Deduplizierung**, 5. **Datenschutz/Sicherheit** (keine echten Nutzerdaten in der Welt;
Injection-/Token-Filter), 6. **versionierter Datensatz**, 7. **LoRA**, 8. **unabhängige Evaluation** – zusätzlich zu `eval-v1` gibt es
`eval-sim-v1` aus einer **separaten Evaluationswelt** (eigener Seed, nur Regeln), 9. **Vergleich**, 10. **manuelle Aktivierung**.
Dialogzeilen der Agenten sind nicht verifizierbar: Sie werden nur auf Wunsch exportiert, als „ausstehend“ und als selbst erzeugte
Quelle (höchstens 50 % eines Datensatzes).

## 6. Leistung

Siehe [STATUS.md](STATUS.md) für gemessene Werte. Die Architektur trennt deterministische Physik (billig, jeder Tick) von
ereignisgesteuerter Modellnutzung (teuer, budgetiert, mit Fristen). Größere Populationen sind vorgesehen (`max_population`), aber
**nur bis ~35 Bewohner tatsächlich getestet**.

## 7. Bekannte Grenzen (ehrlich)

- Mit dem 0,5-B-Modell sind Dialoge oft floskelhaft oder fallen aus der Rolle („Ich kann keine persönlichen …“). Auf der CPU schafft
  das Modell bei 20× und 100× nur einen Bruchteil der Entscheidungen; die übrigen trifft das Regelsystem (sichtbar markiert).
- Gesetzestypen sind eine feste Liste mechanisch durchsetzbarer Wirkungen; frei formulierte Gesetze ohne Mechanik gibt es nicht.
- Nicht umgesetzt: Föderationen zwischen Regionen, Diskriminierungsmechanik, Briefe, detaillierte Medizin, isometrische Grafik,
  Energieanlagen außer der Wassermühle als Gebäude (ohne Produktionsbonus).
- Wichtigkeit von Erinnerungen ist heuristisch (pro Art), Relevanz lexikalisch – aus Rechenzeitgründen.
- Die Welt-Datenbanken sind SQLite-Dateien (portabel, Backup = Dateikopie); PostgreSQL wird für die Welt nicht unterstützt.
