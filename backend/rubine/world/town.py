"""Rubine World: the town map and its 25 residents."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

WIDTH, HEIGHT = 48, 32


@dataclass
class Location:
    id: str
    name: str
    kind: str
    x: int
    y: int
    w: int
    h: int
    color: str

    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


LOCATIONS: list[Location] = [
    Location("haus_nord", "Wohnhaus Nord", "home", 2, 2, 7, 5, "#3b3355"),
    Location("haus_ost", "Wohnhaus Ost", "home", 39, 2, 7, 5, "#3b3355"),
    Location("haus_sued", "Wohnhaus Süd", "home", 2, 25, 7, 5, "#3b3355"),
    Location("haus_west", "Wohnhaus West", "home", 39, 25, 7, 5, "#3b3355"),
    Location("haus_mitte", "Wohnhaus Mitte", "home", 21, 26, 7, 4, "#3b3355"),
    Location("cafe", "Rubin Café", "cafe", 12, 3, 8, 6, "#6d3b5e"),
    Location("bibliothek", "Bibliothek", "library", 28, 3, 9, 6, "#2f4a6d"),
    Location("rathaus", "Rathaus (Aufgabenbrett)", "townhall", 19, 12, 10, 7, "#5b4b8a"),
    Location("akademie", "Akademie", "school", 2, 11, 8, 7, "#2f5d6d"),
    Location("labor", "Prüflabor", "lab", 36, 11, 9, 7, "#2d5a4a"),
    Location("park", "Park", "park", 12, 20, 8, 5, "#1f4d32"),
    Location("markt", "Markt", "market", 30, 20, 8, 5, "#6d5a2f"),
    Location("werkstatt", "Werkstatt", "workshop", 11, 11, 6, 6, "#5a3a2a"),
]
LOC = {l.id: l for l in LOCATIONS}


@dataclass
class Persona:
    id: str
    name: str
    age: int
    occupation: str
    traits: list[str]
    goals: list[str]
    skills: list[str]  # curriculum families the agent likes to work on
    home: str
    work: str
    color: str
    background: str
    schedule: dict[int, str] = field(default_factory=dict)  # hour -> location id

    def to_dict(self) -> dict:
        return asdict(self)


def _schedule(home: str, work: str, social: str, evening: str, early: bool = False) -> dict[int, str]:
    start = 7 if early else 8
    sch = {h: home for h in range(24)}
    for h in range(start, 12):
        sch[h] = work
    sch[12] = social
    for h in range(13, 17):
        sch[h] = work
    sch[17] = evening
    sch[18] = evening
    sch[19] = social
    return sch


_P = [
    # id, name, age, occupation, traits, goals, skills, home, work, social, evening, color, background
    ("anna", "Anna Berger", 34, "Mathematiklehrerin", ["geduldig", "strukturiert"],
     ["Kindern Freude an Mathe vermitteln", "Ein Rätselbuch schreiben"], ["arithmetic", "word_problem"],
     "haus_nord", "akademie", "cafe", "park", "#a78bfa", "Unterrichtet seit zehn Jahren an der Akademie."),
    ("ben", "Ben Okafor", 41, "Bibliothekar", ["ruhig", "belesen"],
     ["Die Bibliothek digitalisieren", "Jede Woche ein Buch empfehlen"], ["string_reverse", "letter_count"],
     "haus_ost", "bibliothek", "cafe", "bibliothek", "#60a5fa", "Kennt jedes Buch im Regal beim Namen."),
    ("clara", "Clara Weiß", 29, "Prüfingenieurin", ["kritisch", "genau"],
     ["Keine falsche Antwort durchlassen", "Prüfverfahren verbessern"], ["sorting", "arithmetic"],
     "haus_sued", "labor", "markt", "labor", "#34d399", "Leitet das Prüflabor, in dem Lösungen verifiziert werden."),
    ("david", "David Nguyen", 26, "Softwareentwickler", ["neugierig", "schnell"],
     ["Ein eigenes Spiel entwickeln", "Algorithmen verstehen"], ["sorting", "string_reverse"],
     "haus_west", "werkstatt", "cafe", "park", "#f472b6", "Baut in der Werkstatt kleine Programme."),
    ("elif", "Elif Demir", 38, "Bäckerin", ["herzlich", "praktisch"],
     ["Neues Rezept erfinden", "Mengen exakt kalkulieren"], ["unit_conversion", "word_problem"],
     "haus_mitte", "cafe", "markt", "haus_mitte", "#fbbf24", "Betreibt das Rubin Café und rechnet Rezepte um.", True),
    ("felix", "Felix Hartmann", 52, "Bürgermeister", ["diplomatisch", "optimistisch"],
     ["Die Stadt gemeinsam verbessern", "Mehr Aufgaben gemeinsam lösen"], ["ordering_logic", "weekday_math"],
     "haus_nord", "rathaus", "cafe", "rathaus", "#c084fc", "Verwaltet das Aufgabenbrett im Rathaus."),
    ("greta", "Greta Lind", 19, "Studentin", ["wissbegierig", "ungeduldig"],
     ["Prüfungen bestehen", "Logik lernen"], ["ordering_logic", "arithmetic"],
     "haus_ost", "akademie", "park", "bibliothek", "#93c5fd", "Studiert an der Akademie."),
    ("hamid", "Hamid Rahimi", 45, "Händler", ["gesellig", "rechnet im Kopf"],
     ["Faire Preise machen", "Den Markt vergrößern"], ["word_problem", "unit_conversion"],
     "haus_sued", "markt", "cafe", "markt", "#f59e0b", "Hat den beliebtesten Stand auf dem Markt."),
    ("ines", "Ines Moreau", 31, "Linguistin", ["präzise", "humorvoll"],
     ["Ein Wörterbuch der Stadt anlegen", "Buchstabenrätsel erfinden"], ["letter_count", "string_reverse"],
     "haus_west", "bibliothek", "cafe", "park", "#818cf8", "Forscht über Sprache und Wörter."),
    ("jakob", "Jakob Schmid", 60, "Uhrmacher", ["pünktlich", "bedächtig"],
     ["Die Rathausuhr reparieren", "Kalender exakt führen"], ["weekday_math", "arithmetic"],
     "haus_mitte", "werkstatt", "cafe", "haus_mitte", "#a3a3a3", "Repariert Uhren und denkt in Wochentagen.", True),
    ("kira", "Kira Volkova", 27, "Datenanalystin", ["analytisch", "direkt"],
     ["Fehlerquellen finden", "Statistiken verständlich machen"], ["sorting", "arithmetic"],
     "haus_nord", "labor", "markt", "bibliothek", "#2dd4bf", "Wertet die Ergebnisse des Prüflabors aus."),
    ("leon", "Leon Fischer", 23, "Gärtner", ["ruhig", "naturverbunden"],
     ["Den Park erweitern", "Pflanzen zählen und ordnen"], ["sorting", "letter_count"],
     "haus_ost", "park", "cafe", "park", "#4ade80", "Pflegt den Park.", True),
    ("mara", "Mara Costa", 36, "Journalistin", ["neugierig", "kommunikativ"],
     ["Über Fortschritte der Stadt berichten", "Gute Fragen stellen"], ["ordering_logic", "letter_count"],
     "haus_sued", "rathaus", "cafe", "markt", "#fb7185", "Schreibt für die Stadtzeitung."),
    ("nils", "Nils Andersen", 44, "Handwerker", ["zuverlässig", "pragmatisch"],
     ["Werkstatt modernisieren", "Maße genau umrechnen"], ["unit_conversion", "arithmetic"],
     "haus_west", "werkstatt", "markt", "haus_west", "#fdba74", "Baut Möbel nach Maß.", True),
    ("olga", "Olga Petrova", 55, "Ärztin", ["fürsorglich", "sorgfältig"],
     ["Gesundheit der Stadt fördern", "Dosierungen fehlerfrei berechnen"], ["unit_conversion", "arithmetic"],
     "haus_mitte", "akademie", "cafe", "park", "#f87171", "Unterrichtet auch Erste Hilfe."),
    ("paul", "Paul Wagner", 33, "Logiker", ["skeptisch", "gründlich"],
     ["Beweise statt Behauptungen", "Denkfehler aufdecken"], ["ordering_logic", "weekday_math"],
     "haus_nord", "labor", "cafe", "bibliothek", "#7dd3fc", "Prüft Argumente auf Schlüssigkeit."),
    ("quinn", "Quinn Baker", 28, "Musikerin", ["kreativ", "spontan"],
     ["Ein Konzert im Park geben", "Rhythmen zählen"], ["letter_count", "weekday_math"],
     "haus_ost", "park", "cafe", "park", "#e879f9", "Spielt abends im Park."),
    ("rosa", "Rosa Jiménez", 47, "Architektin", ["visionär", "präzise"],
     ["Neues Rathaus entwerfen", "Flächen korrekt berechnen"], ["arithmetic", "unit_conversion"],
     "haus_sued", "werkstatt", "markt", "bibliothek", "#fca5a5", "Plant Gebäude für Rubine World."),
    ("samir", "Samir Haddad", 39, "Koch", ["leidenschaftlich", "schnell"],
     ["Kochkurs anbieten", "Zutaten genau abwiegen"], ["unit_conversion", "word_problem"],
     "haus_west", "cafe", "markt", "haus_west", "#facc15", "Kocht mittags im Café.", True),
    ("tara", "Tara Singh", 24, "Lehramtsstudentin", ["freundlich", "fleißig"],
     ["Gute Erklärungen schreiben", "Selbst Mathe unterrichten"], ["word_problem", "sorting"],
     "haus_mitte", "akademie", "park", "bibliothek", "#c4b5fd", "Assistiert Anna im Unterricht."),
    ("ugo", "Ugo Romano", 66, "Rentner & Schachspieler", ["bedacht", "weise"],
     ["Jüngeren Schach beibringen", "Logische Rätsel lösen"], ["ordering_logic", "sorting"],
     "haus_nord", "park", "cafe", "cafe", "#d4d4d8", "Spielt täglich Schach im Park."),
    ("vera", "Vera Novak", 42, "Archivarin", ["ordentlich", "geduldig"],
     ["Das Stadtarchiv sortieren", "Daten korrekt datieren"], ["sorting", "weekday_math"],
     "haus_ost", "bibliothek", "cafe", "haus_ost", "#a5b4fc", "Führt das Archiv der Stadt."),
    ("wim", "Wim de Jong", 35, "Ingenieur", ["systematisch", "hilfsbereit"],
     ["Bessere Werkzeuge bauen", "Lösungen gegenprüfen"], ["arithmetic", "unit_conversion"],
     "haus_sued", "labor", "markt", "werkstatt", "#5eead4", "Entwickelt Messgeräte für das Labor."),
    ("xenia", "Xenia Ivanova", 30, "Übersetzerin", ["sprachbegabt", "aufmerksam"],
     ["Texte fehlerfrei übertragen", "Wörter rückwärts lesen lernen"], ["string_reverse", "letter_count"],
     "haus_west", "bibliothek", "cafe", "park", "#f0abfc", "Übersetzt Bücher für die Bibliothek."),
    ("yara", "Yara Haddad", 21, "Informatikstudentin", ["ehrgeizig", "verspielt"],
     ["Eine eigene KI verstehen", "Sortieralgorithmen meistern"], ["sorting", "string_reverse"],
     "haus_mitte", "akademie", "cafe", "werkstatt", "#67e8f9", "Studiert Informatik und hilft im Labor."),
]


def build_personas() -> list[Persona]:
    out = []
    for row in _P:
        (pid, name, age, occ, traits, goals, skills, home, work, social, evening, color, bg, *rest) = row
        early = bool(rest and rest[0])
        out.append(Persona(pid, name, age, occ, traits, goals, skills, home, work, color, bg,
                           _schedule(home, work, social, evening, early)))
    assert len(out) == 25
    return out


PERSONAS = build_personas()
PERSONA = {p.id: p for p in PERSONAS}
