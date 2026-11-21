export type Calendar = { year: number; season: number; season_name: string; day_of_season: number; day: number; hour: number; minute: number; label: string };

export type W2Agent = {
  id: string; name: string; family: string; x: number; y: number; alive: boolean; age: number; activity: string;
  cat: string | null; asleep: boolean; ill: boolean; origin: string; child: boolean; thinking: boolean; health: number;
};

export type W2Building = { id: string; type: string; label: string; x: number; y: number; condition: number; owner: string | null; name: string | null };
export type W2Site = { id: string; type: string; label: string; x: number; y: number; progress: number; missing: Record<string, number>; owner: string | null };
export type W2Settlement = { id: string; name: string; x: number; y: number; active: boolean };

export type W2Event = {
  id: number; tick: number; cat: string; kind: string; text: string; actors: string[]; x: number | null; y: number | null;
  region: number | null; data: Record<string, unknown>; cause: number | null; public: boolean; calendar?: string;
};

export type W2State = {
  tick: number; calendar: Calendar; running: boolean; speed: number; tick_rate: number; version: number; map_version: number;
  weather: Record<string, { type: string; label: string; temp: number }>; daylight: number; river_level: number;
  agents: W2Agent[]; population: number; paused_reason: string | null;
  buildings?: W2Building[]; sites?: W2Site[]; settlements?: W2Settlement[]; events?: W2Event[];
};

export type W2Map = {
  w: number; h: number; terrain: string[]; terrain_legend: Record<string, string>; wood: string[]; region: string[];
  regions: string[]; roads: number[][]; bridges: number[][]; flooded: number[][]; map_version: number;
  buildings: W2Building[]; sites: W2Site[]; settlements: W2Settlement[];
};

export const SPEEDS = [0, 1, 5, 20, 100];

export const CAT_LABEL: Record<string, string> = {
  umwelt: "Umwelt", leben: "Leben", wirtschaft: "Wirtschaft", bau: "Bau", politik: "Politik", justiz: "Justiz",
  sozial: "Soziales", wissen: "Wissen & Kultur", system: "System",
};

export const ORIGIN_COLOR: Record<string, string> = {
  Flussbauern: "#86efac", Bergvolk: "#fcd34d", Waldleute: "#5eead4", "Küstenfischer": "#93c5fd", "geboren im Tal": "#f0abfc",
};

export const NEED_LABEL: Record<string, string> = { hunger: "Hunger", thirst: "Durst", energy: "Energie", social: "Einsamkeit", stress: "Stress" };
export const PERS_LABEL: Record<string, string> = {
  openness: "Offenheit", conscientiousness: "Gewissenhaftigkeit", agreeableness: "Hilfsbereitschaft", risk: "Risikobereitschaft",
  ambition: "Ehrgeiz", patience: "Geduld", trust: "Vertrauen", conflict_avoidance: "Konfliktvermeidung", self_control: "Selbstkontrolle",
  curiosity: "Neugier", extraversion: "Geselligkeit",
};
export const VALUE_LABEL: Record<string, string> = {
  fairness: "Gerechtigkeit", tradition: "Tradition", freedom: "Freiheit", security: "Sicherheit", wealth: "Wohlstand", community: "Gemeinschaft",
};
export const ITEM_LABEL: Record<string, string> = { food: "Nahrung", wood: "Holz", stone: "Stein", herbs: "Kräuter", tools: "Werkzeug", medicine: "Medizin" };
export const itemLabel = (k: string) => (k.startsWith("coin:") ? "Münzen" : ITEM_LABEL[k] ?? k);
