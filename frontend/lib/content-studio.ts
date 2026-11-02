import type { WorldMap } from "@/lib/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export type LocalizedText = { en: string; "zh-CN": string };

export type StudioInteractionPoint = {
  object_id: string;
  type: string;
  name: LocalizedText;
  description: LocalizedText;
  renderer_key: string;
  interaction_event_id?: string;
};

export type StudioFlowEffect =
  | { type: "advance_time"; minutes: number }
  | { type: "goto_node"; node_id: string }
  | { type: "complete_flow"; outcome_code: string }
  | { type: "start_event"; event_id: string }
  | { type: "schedule_event"; event_id: string; delay_minutes: number }
  | { type: "set_flag"; flag_id: string; value: boolean }
  | { type: "goal_update"; goal: { goal_id: string; status: string; title?: LocalizedText; description?: LocalizedText; target_location_id?: string; resolution?: string } }
  | { type: "relationship_delta"; target_agent_id: number; familiarity_delta?: number; trust_delta?: number; warmth_delta?: number; tension_delta?: number }
  | { type: "add_memory"; owner_agent_id: number; text: LocalizedText; tags?: string[] }
  | { type: "move_participant"; location_id: string }
  | { type: "show_message"; text: LocalizedText };

export type StudioLocation = {
  location_id: string;
  name: LocalizedText;
  description: LocalizedText;
  scene_type: string;
  version: string;
  connected_location_ids: string[];
  opening_hours: { always_open: boolean };
  interaction_points: StudioInteractionPoint[];
  allowed_actions: string[];
  event_pool_ids: string[];
};

export type StudioSchedule = {
  state_id: string;
  start_minute: number;
  end_minute: number;
  location_id: string;
  activity: LocalizedText;
  goal: LocalizedText;
  days?: number[];
};

export type StudioResidentAutonomy = {
  enabled: boolean;
  allowed_intents: Array<
    | "idle"
    | "inspect_object"
    | "socialize_resident"
    | "greet_participant"
    | "visit_adjacent_location"
  >;
  preferred_location_ids: string[];
  free_time_state_ids: string[];
  action_cooldown_minutes: number;
  idle_weight: number;
  inspect_weight: number;
  socialize_weight: number;
  greet_weight: number;
  travel_weight: number;
};

export type StudioResident = {
  agent_id: number;
  name: string;
  adult_age_range: string;
  role: LocalizedText;
  public_summary: LocalizedText;
  home_location_id: string;
  background: LocalizedText;
  personality: LocalizedText;
  values: LocalizedText[];
  preferences: LocalizedText[];
  communication_style: LocalizedText;
  goals: LocalizedText[];
  knowledge_boundaries: LocalizedText[];
  avoid_patterns: LocalizedText[];
  safety_rules: LocalizedText[];
  avatar_key: string;
  marker_color_key: string;
  profile_version: string;
  prompt_version: string;
  autonomy?: StudioResidentAutonomy;
  schedule: StudioSchedule[];
};

export type StudioEventAction = {
  action_id: string;
  label: LocalizedText;
  requires_text: boolean;
  outcome_key: string;
  follow_up_event_id?: string;
  memory_owner_agent_id?: number;
  memory_text?: LocalizedText;
  relationship_effect?: Record<string, number>;
};

export type StudioBehavioralEventAction = {
  action_id: string;
  label: LocalizedText;
  requires_text: boolean;
  action_type: string;
  next_stage_id?: string;
  terminal: boolean;
  outcome_code: string;
  action_minutes?: number;
  target_type?: string;
  target_id?: string;
  target_agent_id?: number;
  target_location_id?: string;
  state_updates?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  npc_response?: Record<string, unknown>;
  goal_effect?: Record<string, unknown>;
  effects?: StudioFlowEffect[];
};

export type StudioTriggerCondition = {
  type: "world_day" | "world_time" | "location" | "action_type" | "object_choice" | "resident_present" | "flag" | "goal_status" | "event_status";
  operator: "equals" | "at_least" | "at_most";
  value: string | number;
};

export type StudioBehavioralEventStage = {
  stage_id: string;
  title: LocalizedText;
  stimulus: LocalizedText;
  actions: StudioBehavioralEventAction[];
};

export type StudioSocialPublicationTemplate = {
  author_agent_id: number;
  content: LocalizedText;
};

export type StudioSocialPublication = {
  publication_id: string;
  trigger_outcomes: string[];
  eligible_author_ids: number[];
  witness_agent_ids: number[];
  visibility: "island_public" | "participants_only";
  post_type: string;
  max_posts: number;
  cooldown_minutes: number;
  allow_comments: boolean;
  generation_mode: "static_fallback" | "llm_with_fallback";
  facts: Record<string, string | number | boolean | number[]>;
  templates: StudioSocialPublicationTemplate[];
};

export type StudioEvent = {
  event_id: string;
  event_type: string;
  version: string;
  title: LocalizedText;
  stimulus: LocalizedText;
  location_ids: string[];
  event_pool_ids: string[];
  trigger: {
    type: string;
    time_window?: { start_minute: number; end_minute: number };
    conditions?: { mode: "all" | "any"; items: StudioTriggerCondition[] };
  };
  weight: number;
  cooldown_minutes: number;
  max_occurrences: number;
  prerequisites: Record<string, unknown>;
  exclusion_flags: { active_scenario?: boolean; active_event?: boolean };
  actions: StudioEventAction[];
  renderer_key?: string;
  initial_stage_id?: string;
  stages?: StudioBehavioralEventStage[];
  logging_config?: Record<string, unknown>;
  llm_context?: Record<string, unknown>;
  social_publications?: StudioSocialPublication[];
};

export type StudioManifest = {
  content_pack_version: string;
  world_version: string;
  event_pack_version: string;
  schema_version: string;
  authoring_only?: boolean;
  default_language: string;
  supported_languages: string[];
  start_location_id: string;
  calendar: {
    total_days: number;
    day_start_minute: number;
    day_end_minute: number;
    rollover: string;
  };
  action_minutes: Record<string, number>;
  experience?: {
    mode: "open_exploration";
    recommended_total_days: number;
    final_day_departure_required: boolean;
    departure_prompt: LocalizedText;
    behavior_audit_version: string;
  };
  files: Record<"map" | "locations" | "residents" | "events", string> & {
    visuals?: string;
    systems?: string;
  };
};

export type StudioNarrativeArc = { arc_id: string; version: "narrative-projection-v1"; label: LocalizedText; nodes: Array<{ node_id: string; recipe_id: string; requires_nodes: string[]; terminal_labels: Record<string, LocalizedText> }> };

export type StudioSystems = {
  contract_version?: string;
  action_definitions: Array<{
    action_id: string; label: LocalizedText; actor_types: string[];
    target_types: string[]; duration_minutes: number; consequences: Array<Record<string, unknown>>;
    execution_mode?: string; location_scope?: string; min_participants?: number; max_participants?: number;
    inputs?: Array<Record<string, unknown>>; preconditions?: Record<string, unknown>;
    effect_allowlist?: string[]; permission_keys?: string[]; capability_keys?: string[];
    interruptible?: boolean; failure_reason_codes?: string[];
  }>;
  affordances: Array<{
    affordance_id: string; action_id: string; location_ids: string[];
    object_ids: string[]; enabled: boolean; conditions?: Record<string, unknown>;
    permission_keys?: string[]; capability_keys?: string[];
  }>;
  activity_recipes: Array<{
    recipe_id: string; label: LocalizedText; location_ids: string[]; action_ids: string[];
    min_participants: number; max_participants: number; duration_minutes: number;
    conditions?: Record<string, unknown>; board_post_template?: LocalizedText;
    object_ids?: string[]; role_slots?: string[]; variant_recipe_ids?: string[];
    complexity?: string; player_facing?: boolean;
  }>;
  stage_recipes?: StudioStageRecipe[];
  plan_policy?: Record<string, unknown>;
  knowledge_policy?: Record<string, unknown>;
  candidate_policy?: Record<string, unknown>;
  llm_policy?: Record<string, unknown>;
  interaction_policy?: Record<string, unknown>;
  autonomy_policy?: Record<string, unknown>;
  narrative_arcs?: StudioNarrativeArc[];
  emergence_policy: {
    policy_id?: string; policy_version?: string; max_agent_actions_per_tick?: number;
    max_invitations_per_tick?: number; max_activity_creations_per_tick?: number;
    max_event_chain_depth?: number; [key: string]: unknown;
  };
};

export type StudioStageChoice = { choice_id: string; label: LocalizedText; action_id: string | null; object_id: string | null; inputs: Record<string, unknown>; next_stage_id: string | null; outcome: string | null };
export type StudioStageCard = { stage_id: string; label: LocalizedText; kind: "decision" | "action" | "closure"; role_goals: Record<string, string>; authority_roles: string[]; duration_minutes: number; timeout_outcome: string; absence_outcome: string; enter_conditions: Record<string, unknown>; choices: StudioStageChoice[] };
export type StudioStageRecipe = { stage_recipe_id: string; label: LocalizedText; allowed_action_ids: string[]; terminal_outcomes: string[]; max_stages: number; max_player_choices_per_stage: number; initial_stage_id?: string; stages?: StudioStageCard[] };
export type StudioAudit = {
  valid: boolean; complete: boolean; result_hash: string; projection_version: string;
  findings: Array<{ code: string; severity: string; file: string; json_path: string; detail: string }>;
  graph: { nodes: Array<{ id: string; kind: string; label: string; file: string; json_path: string }>; edges: Array<{ source: string; target: string; relation: string; missing: boolean; file: string; json_path: string }> };
  days: Array<{ day: number; new_player_facing_events: number; major_events: number; direct_invitations: number; candidates: Array<{ minute: number; recipe_id: string; reason_code: string; json_path: string; assumed_members: Array<string | number>; choices: string[] }> }>;
  assumptions?: Record<string, unknown>; facts?: Array<Record<string, unknown>>;
};

export async function auditStudioDraft(draft: StudioDraft, seed: number, response: string, publicConsent: boolean, signal?: AbortSignal) {
  const params = new URLSearchParams({ seed: String(seed), response, public_consent: String(publicConsent) });
  const result = await fetch(`${API_BASE_URL}/studio-api/audit?${params}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft), signal });
  if (!result.ok) throw new Error(`规则诊断失败 (${result.status})`);
  return result.json() as Promise<StudioAudit>;
}

export type StudioVisualSlotType =
  | "map_image"
  | "actor_map_thumbnail"
  | "location_map_thumbnail"
  | "actor_dialogue_portrait"
  | "location_scene_image";

export type StudioVisualAsset = {
  asset_key: string;
  file_name: string;
  mime_type: "image/png" | "image/jpeg" | "image/webp";
  width: number;
  height: number;
  sha256: string;
  source: string;
  license: string;
};

export type StudioVisualSlot = {
  slot_id: string;
  slot_type: StudioVisualSlotType;
  target_id: string;
  asset_key: string | null;
  fallback_palette_key: string;
  fallback_title: LocalizedText;
  fallback_description: LocalizedText;
};

export type StudioVisuals = {
  visual_version: string;
  visual_assets: StudioVisualAsset[];
  visual_slots: StudioVisualSlot[];
};

export type StudioDraft = {
  manifest: StudioManifest;
  map: WorldMap;
  locations: { locations: StudioLocation[] };
  residents: { residents: StudioResident[] };
  events: { events: StudioEvent[] };
  visuals?: StudioVisuals;
  systems?: StudioSystems;
  asset_urls?: Record<string, string>;
};

export type StudioAssetFiles = Record<string, Blob>;

export type StudioValidation = {
  valid: boolean;
  errors: Array<{
    file: string;
    json_path: string;
    reason: string;
    message: string;
  }>;
  version_conflicts: Array<{
    field: string;
    value: string;
    message: string;
  }>;
  summary: Record<string, unknown> | null;
};

export async function listStudioPacks() {
  return studioJson<{ packs: Array<{ directory_name: string; kind: "runtime_pack" | "authoring_template"; [key: string]: unknown }> }>(
    "/studio-api/packs",
  );
}

export async function getStudioPack(directoryName: string) {
  return studioJson<StudioDraft>(`/studio-api/packs/${encodeURIComponent(directoryName)}`);
}

export async function validateStudioDraft(
  draft: StudioDraft,
  assetFiles: StudioAssetFiles = {},
) {
  if (["content-pack-v2", "content-pack-v3", "content-pack-v4", "content-pack-v5"].includes(draft.manifest.schema_version)) {
    return studioMultipart<StudioValidation>("/studio-api/v2/validate", draft, assetFiles);
  }
  return studioJson<StudioValidation>("/studio-api/validate", {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

export async function exportStudioDraft(
  draft: StudioDraft,
  assetFiles: StudioAssetFiles = {},
) {
  const isV2 = ["content-pack-v2", "content-pack-v3", "content-pack-v4", "content-pack-v5"].includes(draft.manifest.schema_version);
  const response = await fetch(
    `${API_BASE_URL}${isV2 ? "/studio-api/v2/export" : "/studio-api/export"}`,
    isV2
      ? { method: "POST", body: studioFormData(draft, assetFiles) }
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        },
  );
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { detail?: { message?: string; errors?: Array<{ message?: string }> } | string }
      | null;
    const detail = body?.detail;
    const message = typeof detail === "string"
      ? detail
      : detail?.message ?? detail?.errors?.[0]?.message ?? "Export failed";
    throw new Error(message);
  }
  return {
    blob: await response.blob(),
    filename: response.headers.get("content-disposition")?.match(/filename="?([^";]+)"?/)?.[1] ?? "content-pack.zip",
  };
}

function studioFormData(draft: StudioDraft, assetFiles: StudioAssetFiles) {
  const form = new FormData();
  const serializableDraft = { ...draft };
  delete serializableDraft.asset_urls;
  form.append(
    "draft",
    new Blob([JSON.stringify(serializableDraft)], { type: "application/json" }),
    "draft.json",
  );
  for (const asset of draft.visuals?.visual_assets ?? []) {
    const blob = assetFiles[asset.asset_key];
    if (blob) {
      form.append(
        `asset:${asset.asset_key}`,
        blob,
        asset.file_name.split("/").at(-1) ?? "asset",
      );
    }
  }
  return form;
}

async function studioMultipart<T>(
  path: string,
  draft: StudioDraft,
  assetFiles: StudioAssetFiles,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    body: studioFormData(draft, assetFiles),
  });
  if (!response.ok) throw new Error(`Studio API returned ${response.status}`);
  return response.json() as Promise<T>;
}

async function studioJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) throw new Error(`Studio API returned ${response.status}`);
  return response.json() as Promise<T>;
}
