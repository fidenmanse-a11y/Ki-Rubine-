export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  model_version_id: string | null;
  training_consent: boolean;
  preview?: string | null;
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "complete" | "streaming" | "stopped" | "error";
  seq: number;
  model_version_id: string | null;
  feedback: number;
  stats: { tokens?: number; seconds?: number; tok_per_s?: number; error?: string } | null;
  created_at: string;
};

export type VersionInfo = {
  id: string;
  name: string;
  status: string;
  chat_allowed: boolean;
  active: boolean;
  created_at: string;
  accuracy?: number | null;
};

export type EngineInfo = {
  status: "idle" | "loading" | "ready" | "error" | "disabled";
  error: string | null;
  device: string | null;
  base_model: string;
  license: string;
  loaded_adapters: string[];
  busy: boolean;
  last_tok_per_s: number | null;
};

export type Job = {
  id: string;
  type: string;
  status: string;
  progress: number;
  message: string | null;
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  metrics?: { step: number; loss: number | null; lr: number | null; kind: string; extra: Record<string, unknown> | null }[];
  log_tail?: string;
};

export type FamilyStats = Record<string, { n: number; correct: number; accuracy: number }>;

export type ModelVersion = {
  id: string;
  name: string;
  parent_id: string | null;
  status: string;
  dataset_id: string | null;
  job_id: string | null;
  base_model: string;
  hyperparams: Record<string, unknown> | null;
  metrics: {
    train?: Record<string, number | string | null>;
    eval?: { accuracy: number; eval_loss: number; n: number; per_family: FamilyStats };
    parent_eval?: { accuracy: number; eval_loss: number; n: number; per_family: FamilyStats };
    gate?: { passed: boolean; reasons: string[] };
  } | null;
  notes: string | null;
  created_at: string;
  active: boolean;
  chat_allowed: boolean;
};

export type AgentView = {
  id: string; name: string; x: number; y: number; location: string | null; activity: string;
  status: string; speech: string | null; color: string; occupation: string;
};

export type WorldEvent = { id?: number; kind: string; content: string; agents: string[]; clock: string };

export type WorldState = {
  version: number;
  clock: { day: number; weekday: string; hour: number; minute: number; label: string };
  running: boolean;
  tick_seconds: number;
  agents: AgentView[];
  task: null | {
    id: string; family: string; prompt: string; team: string[]; reviewer: string; stage: string;
    proposals: { agent: string; answer: string | null; correct?: boolean }[];
    outcome: null | { correct: number; total: number; expected: string; examples_added: number; consensus_correct: boolean };
  };
  queue: number;
  llm_note: string | null;
  llm: { available: boolean; detail: string };
  events?: WorldEvent[];
};

export type WorldMap = {
  width: number; height: number;
  locations: { id: string; name: string; kind: string; x: number; y: number; w: number; h: number; color: string }[];
};
