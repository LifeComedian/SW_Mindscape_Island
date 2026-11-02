import type { Language } from "@/lib/i18n";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
export const CONSENT_VERSION = "v0.3" as const;

export function resolveApiAssetUrl(path: string) {
  return /^(?:https?:|blob:)/i.test(path) ? path : `${API_BASE_URL}${path}`;
}

export type Agent = {
  id: number;
  name: string;
  role: string;
  personality: string;
  avatar: string;
};

export type WorldActionType =
  | "move"
  | "observe"
  | "approach"
  | "end_conversation"
  | "wait"
  | "end_day"
  | "event_action"
  | "seat_view"
  | "seat_select"
  | "seat_change"
  | "scenario_response"
  | "scenario_skip"
  | "defined_action";

export type WorldActionDescriptor =
  | WorldActionType
  | {
      action_type: WorldActionType;
      target_id?: string | number | null;
      target_location_id?: string | null;
      target_agent_id?: number | null;
      target_object_id?: string | null;
      label?: string | Partial<Record<Language, string>>;
      action_id?: string;
      target_object_ids?: string[];
      affordance_id?: string;
      inputs?: Array<{input_id: string; value_type: string; required: boolean; max_length?: number}>;
      enabled?: boolean;
    };

export type WorldInteractionPoint = {
  object_id: string;
  name?: string | Partial<Record<Language, string>>;
  type?: string;
  interaction_type?: string;
  label?: string | Partial<Record<Language, string>>;
  label_zh_cn?: string;
  description?: string | Partial<Record<Language, string>>;
  description_zh_cn?: string;
  available?: boolean;
  metadata?: Record<string, unknown>;
  renderer_key?: string;
};

export type WorldLocation = {
  location_id: string;
  name: string;
  name_zh_cn?: string;
  description?: string;
  description_zh_cn?: string;
  scene_type?: string;
  connected_location_ids?: string[];
  opening_hours?: Record<string, unknown>;
  is_open?: boolean;
  interaction_points?: WorldInteractionPoint[];
  allowed_actions?: WorldActionType[];
  translations?: Partial<
    Record<Language, { name?: string; description?: string }>
  >;
  metadata?: Record<string, unknown>;
};

export type WorldResident = {
  agent_id: number;
  name: string;
  role?: string;
  role_zh_cn?: string;
  avatar?: string;
  avatar_key?: string;
  marker_color_key?: string;
  public_summary?: string;
  current_location_id?: string;
  current_activity?: string;
  current_activity_zh_cn?: string;
  current_goal?: string;
  current_goal_zh_cn?: string;
  schedule_state?: string;
  intent_type?: string;
  intent_status?: string;
  intent_summary?: string;
  intent_target_location_id?: string | null;
  intent_target_agent_id?: number | null;
  intent_target_object_id?: string | null;
  intent_due_day?: number | null;
  intent_due_time_minutes?: number | null;
  is_busy?: boolean;
  visible?: boolean;
  is_visible?: boolean;
  generation_mode?: string | null;
  model_name?: string | null;
  translations?: Partial<
    Record<
      Language,
      { role?: string; current_activity?: string; current_goal?: string }
    >
  >;
  metadata?: Record<string, unknown>;
};

export type WorldMapPoint = [number, number];

export type WorldMapPath = {
  path_id: string;
  from_location_id: string;
  to_location_id: string;
  points: WorldMapPoint[];
};

export type WorldMapLocationNode = {
  location_id: string;
  x: number;
  y: number;
  click_radius: number;
  icon_key: string;
  label_offset: WorldMapPoint;
};

export type WorldSceneLayout = {
  location_id: string;
  width: number;
  height: number;
  participant_spawn: WorldMapPoint;
  resident_slots: WorldMapPoint[];
  interaction_point_positions: Record<string, WorldMapPoint>;
  hotspots?: Array<{
    hotspot_id: string;
    shape: "circle" | "rectangle";
    target_object_id: string;
    x: number;
    y: number;
    width?: number | null;
    height?: number | null;
    radius?: number | null;
    label: Partial<Record<Language, string>>;
    log_code: string;
  }>;
};

export type WorldMap = {
  map_id: string;
  version: string;
  width: number;
  height: number;
  background: Record<string, string>;
  land_polygon: WorldMapPoint[];
  paths: WorldMapPath[];
  location_nodes: WorldMapLocationNode[];
  scene_layouts: WorldSceneLayout[];
};

export type WorldActor = {
  actor_type: "participant" | "resident";
  actor_id: string;
  agent_id: number | null;
  name: string;
  avatar_key: string;
  marker_color_key: string;
  location_id: string;
  x: number | null;
  y: number | null;
  scene_x: number | null;
  scene_y: number | null;
  current_activity?: string;
  role?: string;
  public_summary?: string;
  intent_type?: string;
  intent_summary?: string;
  is_busy?: boolean;
  is_current_participant: boolean;
};

export type WorldVisualAsset = {
  asset_key: string;
  url: string;
  mime_type: string;
  width: number;
  height: number;
  sha256: string;
  source: string;
  license: string;
};

export type WorldVisualSlot = {
  slot_id: string;
  slot_type: string;
  target_id: string;
  asset_key: string | null;
  fallback_palette_key: string;
  fallback_title: string;
  fallback_description: string;
  asset: WorldVisualAsset | null;
};

export type WorldVisuals = {
  visual_version: string;
  slots: Record<string, WorldVisualSlot>;
};

export type WorldSimulationPulse = {
  pulse_id: number;
  sequence: number;
  source: string;
  status: string;
  reason_code: string;
  requested_revision: number;
  accepted_revision: number | null;
  before_day: number;
  before_time_minutes: number;
  after_day: number;
  after_time_minutes: number;
  action_ids: number[];
  policy_id: string;
  policy_version: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type WorldSimulation = {
  mode: "running" | "paused";
  pulse_interval_hint_ms: number;
  pulse_minutes: number;
  can_pulse: boolean;
  paused_reason: string | null;
  effective_paused?: boolean;
  active_conversation_id?: number | null;
  last_pulse: WorldSimulationPulse | null;
};

export type WorldState = {
  session_id?: number;
  current_day: number;
  total_days?: number;
  current_time: string;
  current_time_minutes?: number;
  current_location_id: string;
  participant_location_id?: string;
  participant_move_minutes_per_edge?: number;
  rest_location_id?: string;
  world_version?: string;
  scenario_pack_version?: string;
  experience_mode?: string | null;
  can_finish?: boolean;
  day_transition_pending?:boolean;
  location_hours?:Record<string,{hours:string;open:boolean;closing_in:number|null}>;
  departure_prompt?: Partial<Record<Language, string>>;
  [key: string]: unknown;
};

export type WorldScenarioOption = {
  option_id?: string;
  id?: string;
  value?: string;
  object_id?: string;
  target_object_id?: string;
  response_code?: string;
  label?: string | Partial<Record<Language, string>>;
  label_zh_cn?: string;
  description?: string | Partial<Record<Language, string>>;
  description_zh_cn?: string;
  available?: boolean;
  attributes?: string[];
  display_order?: number;
  metadata?: Record<string, unknown>;
};

export type WorldScenario = {
  scenario_instance_id: number | string;
  scenario_id?: string;
  version?: string;
  form?: string;
  scenario_type?: string;
  stage?: string;
  status?: string;
  title?: string;
  title_zh_cn?: string;
  description?: string;
  description_zh_cn?: string;
  prompt?: string;
  prompt_zh_cn?: string;
  stimulus_text?: string;
  options?: WorldScenarioOption[];
  visible_options?: WorldScenarioOption[];
  seat_options?: WorldScenarioOption[];
  available_actions?: WorldActionDescriptor[];
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
};

export type WorldEventAction = {
  action_id: string;
  label?: string;
  label_zh_cn?: string;
  labels?: Partial<Record<Language, string>>;
  kind?: string;
  enabled?: boolean;
  requires_text?: boolean;
  target_object_id?: string | null;
  metadata?: Record<string, unknown>;
};

export type WorldEvent = {
  event_instance_id: number | string;
  event_type: string;
  version?: string;
  status?: string;
  location_id?: string;
  renderer_key?: string;
  title?: string;
  title_zh_cn?: string;
  stimulus_text?: string;
  stimulus_text_zh_cn?: string;
  titles?: Partial<Record<Language, string>>;
  stimuli?: Partial<Record<Language, string>>;
  actions?: WorldEventAction[];
  state?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
};

export type WorldActionRecord = {
  action_id: number | string;
  action_type: string;
  actor_id?: number | string | null;
  target_id?: number | string | null;
  target_agent_id?: number | null;
  target_location_id?: string | null;
  target_object_id?: string | null;
  created_at?: string;
  world_time?: string;
  metadata?: Record<string, unknown>;
};

export type WorldConversationTurn = {
  turn_id?: number | string;
  conversation_id?: number | string;
  agent_id?: number;
  speaker_type?: "participant" | "user" | "agent" | string;
  speaker_id?: number | string | null;
  speaker_name?: string;
  content: string;
  created_at?: string;
  generation_mode?: string | null;
  model_provider?: string | null;
  model_name?: string | null;
  safety_flag?: boolean;
};

export type WorldConversationParticipant = {
  participant_id?: number | null;
  member_type: "participant" | "resident" | "system" | string;
  agent_id: number | null;
  member_role: string;
  joined_at?: string | null;
  left_at?: string | null;
  leave_reason_code?: string | null;
};

export type WorldConversation = {
  conversation_id: number | string;
  agent_id?: number;
  resident_id?: number;
  turns?: WorldConversationTurn[];
  status?: string;
  location_id?: string;
  conversation_kind?: "participant_resident" | "resident_resident" | string;
  initiator_type?: "participant" | "resident" | "system" | string;
  initiator_agent_id?: number | null;
  visibility?: "public" | "session_private" | string;
  ended_reason_code?: string | null;
  participants?: WorldConversationParticipant[];
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
};

export type WorldInteractionPrompt = {
  prompt_id: number;
  initiator_agent_id: number;
  location_id: string;
  prompt_kind: string;
  status: "pending" | "accepted" | "later" | "declined" | "expired" | "closed" | string;
  opening_text: Partial<Record<Language, string>>;
  display_opening_text: string;
  allowed_responses: Array<"accept" | "later" | "decline" | string>;
  created_day: number;
  created_time_minutes: number;
  expiry_day: number;
  expiry_time_minutes: number;
  resolved_day?: number | null;
  resolved_time_minutes?: number | null;
  response_code?: string | null;
  source_intent_id?: number | null;
  source_pulse_id?: number | null;
  source_action_id?: number | null;
  response_action_id?: number | null;
  reason_code: string;
  policy_id: string;
  policy_version: string;
  metadata?: Record<string, unknown>;
};

export type WorldCapabilities = {
  events?: boolean;
  conversations?: boolean;
  memory_view?: boolean;
  [capability: string]: boolean | undefined;
};

export type StageChoice = {
  choice_id: string;
  label: Partial<Record<Language, string>>;
  input_fields?: Array<{input_id: string; value_type: string; required?: boolean; max_length?: number; allowed_values?: string[]}>;
};

export type StageCard = {
  feedback?: string;
  discussion?: Array<{id: number; text: string; speaker: string; reply: string; mode: string}>;
  activity_label?: Partial<Record<Language, string>>;
  location_label?: Partial<Record<Language, string>>;
  viewer_response?: string;
  runtime_id: number;
  commitment_id: number;
    plan_revision?: number;
    plan_controls?: Array<"start" | "arrive" | "leave" | "cancel" | "accept" | "withdraw">;
    plan_status?: string;
    scheduled_day?: number;
    scheduled_time_minutes?: number;
    missed_stages?: string[];
  location_id: string;
  status: "waiting" | "active" | "completed" | "failed";
  revision: number;
  stage_id: string;
  kind: "decision" | "action" | "closure";
  label: Partial<Record<Language, string>>;
  choices: StageChoice[];
  can_confirm: boolean;
  needs_confirmation?: boolean;
  can_finish: boolean;
  ready_to_begin?: boolean;
  is_present: boolean;
  proposal: { choice_id: string; actor_key: string } | null;
  outcome: string | null;
  public_consent: boolean;
  facts: Array<{ fact_id: number; visibility: string; payload: Record<string, unknown> }>;
};

export type StageOperation = "discuss" | "suggest" | "confirm" | "reject" | "execute" | "finish" | "allow_publication" | "revoke_publication";

export function getStageCards(sessionId: number) {
  return requestJson<{ cards: StageCard[]; interaction_time_policy?: boolean;
    interaction_focus?: {runtime_id: number; focus_token: string; lease_expires_at: string} | null
  }>(`/sessions/${sessionId}/world/stages`);
}

export type ResidentDecisionPreview = {
  audit_id: number; status: string; kind: string; generation_mode: string;
  fallback_reason?: string | null; expression?: string;
  preview?: {summary: string; kind: string; payload: Record<string, unknown>; requires_confirmation: boolean};
};

export function previewResidentDecision(sessionId: number, agentId: number, decisionType: string) {
  return requestJson<ResidentDecisionPreview>(`/sessions/${sessionId}/world/development/residents/${agentId}/decisions`, {
    method: "POST", body: JSON.stringify({ decision_type: decisionType, execution_mode: "shadow",
      idempotency_key: crypto.randomUUID(), language: "zh-CN" }),
  });
}

export function commitResidentDecision(sessionId: number, agentId: number, auditId: number, key: string) {
  return requestJson<ResidentDecisionPreview>(`/sessions/${sessionId}/world/development/residents/${agentId}/decision-previews/${auditId}/commit`, {
    method: "POST", body: JSON.stringify({ idempotency_key: key, language: "zh-CN" }),
  });
}

export function sendStageAction(sessionId: number, runtimeId: number, body: {
  operation: StageOperation; choice_id?: string; focus_token?: string; expected_revision: number;
  idempotency_key: string; language: Language;
  inputs?: Record<string, string | boolean>;
}) {
  return requestJson<StageCard>(`/sessions/${sessionId}/world/emergence/events/${runtimeId}/stage-actions`, {
    method: "POST", body: JSON.stringify(body),
  });
}

export type WorldSnapshot = {
  contract_version?: string;
  revision?: number;
  snapshot_updated_at?: string;
  capabilities?: WorldCapabilities;
  session: {
    session_id: number;
    nickname?: string;
    user_alias?: string;
    status?: string;
    current_day?: number;
    total_days?: number;
    simulation_seed?: number;
  };
  world: WorldState;
  simulation?: WorldSimulation;
  map?: WorldMap | null;
  actors?: WorldActor[];
  visuals?: WorldVisuals | null;
  locations: WorldLocation[];
  current_location?: WorldLocation;
  interaction_points?: WorldInteractionPoint[];
  residents: WorldResident[];
  visible_residents?: WorldResident[];
  available_actions: WorldActionDescriptor[];
  active_scenario: WorldScenario | null;
  active_event?: WorldEvent | null;
  recent_actions: WorldActionRecord[];
  recent_follow_up: Record<string, unknown> | string | null;
  conversations: Array<WorldConversation | WorldConversationTurn>;
  ambient_conversations?: WorldConversation[];
  pending_interaction_prompt?: WorldInteractionPrompt | null;
  interaction_prompts?: WorldInteractionPrompt[];
  commitments?: Array<Record<string, unknown>>;
  board_posts?: WorldBoardPost[];
  emergence_decisions?: Array<Record<string, unknown>>;
  versions?: Record<string, string>;
};

export type WorldActionInput = {
  idempotency_key: string;
  action_type: WorldActionType;
  target_location_id?: string;
  target_agent_id?: number;
  target_object_id?: string;
  scenario_instance_id?: number | string;
  event_instance_id?: number | string;
  event_action_id?: string;
  response_text?: string;
  response_latency_ms?: number;
  metadata?: Record<string, unknown>;
  language: Language;
};

export type WorldActionResult = {
  status: string;
  action_id: number | string;
  flow_messages?: Array<Partial<Record<"en" | "zh-CN", string>>>;
  world: WorldState | WorldSnapshot | Record<string, unknown>;
};

export type WorldConversationResult = {
  conversation?: WorldConversation;
  user_turn?: WorldConversationTurn;
  agent_turn?: WorldConversationTurn;
  world?: WorldState | WorldSnapshot | Record<string, unknown>;
  [key: string]: unknown;
};

export type WorldPulseResult = {
  status:
    | "accepted"
    | "duplicate"
    | "rate_limited"
    | "stale_revision"
    | "paused"
    | "blocked"
    | "finished";
  reason_code: string;
  original_status?: string;
  pulse: WorldSimulationPulse;
  world: WorldSnapshot;
};

export type Post = {
  id: number;
  agent_id: number;
  agent_name: string;
  agent_role: string;
  content: string;
  scenario_tag: string;
  event_key?: string;
  translations?: Partial<
    Record<
      Language,
      {
        agent_role: string;
        content: string;
        scenario_label: string;
      }
    >
  >;
};

export type CommunityActivity = {
  activity_id: number;
  activity_type: "comment" | "reply";
  post_id: number;
  parent_activity_id: number | null;
  actor: {
    agent_id: number;
    name: string;
    avatar: string;
  };
  target: {
    agent_id: number;
    name: string;
  } | null;
  content: string;
  translations: Partial<Record<Language, { content: string }>>;
  response_latency_ms: number | null;
  generation_mode: string | null;
  model_provider: string | null;
  model_name: string | null;
  prompt_version: string | null;
  safety_flag: boolean;
  metadata: Record<string, unknown>;
  day: number;
  time: string;
  world_day?: number;
  world_time_minutes?: number | null;
};

export type SimulationPost = Post & {
  is_user_post: boolean;
  day: number;
  time: string;
  virtual_date: string;
  simulated_at: string;
  is_current_day: boolean;
  community_like_count: number;
  community_comments: CommunityActivity[];
  post_type: "personal" | "announcement" | "activity" | string;
  author_type: "participant" | "resident" | "system" | string;
  author_agent_id?: number | null;
  world_time_minutes: number;
  visibility: string;
  source: { type?: string | null; id?: number | null };
  location_id?: string | null;
  structured_facts: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  allow_comments: boolean;
};

export type SimulationNotification = {
  notification_id: number;
  day: number;
  agent_id: number | null;
  agent_name: string | null;
  post_id: number | null;
  notification_type: string;
  content: string;
  translations: Partial<Record<Language, { content: string }>>;
  is_read: boolean;
  created_at: string;
  world_day?: number;
  world_time_minutes?: number | null;
};

export type SimulationEvent = {
  event_id: number;
  event_key: string;
  source_post_id: number;
  outcome_post_id: number;
  resolved_day: number;
  branch: "commented" | "liked" | "skipped" | "observed";
  metadata: Record<string, unknown>;
};

export type SimulationFeed = {
  session: {
    session_id: number;
    nickname: string;
    status: string;
    current_day: number;
    total_days: number;
    simulation_seed: number;
    virtual_start_date: string;
  };
  timeline: {
    current_day: number;
    current_time: string;
    current_time_minutes: number;
    total_days: number;
    virtual_date: string;
    days: Array<{
      day: number;
      date: string;
      is_unlocked: boolean;
    }>;
  };
  posts: SimulationPost[];
  notifications: SimulationNotification[];
  events: SimulationEvent[];
  user_interactions: InteractionRecord[];
  world_board_posts?: WorldBoardPost[];
};

export type WorldBoardPost = {
  board_post_id: number;
  commitment_id?: number | null;
  author_type: string;
  author_agent_id?: number | null;
  content: Partial<Record<Language, string>>;
  day?: number;
  world_day?: number;
  time_minutes?: number;
  world_time_minutes?: number;
  metadata: Record<string, unknown>;
};

export type PhoneInvitationCard = {
  can_respond?:boolean;
  response_feedback?:{agent_id:number;name:string;status:string;text:string}[];
  location_label?: Record<string, string>;
  post_id: number;
  post_type: "invitation";
  fact_chain_id: number;
  activity_id: number;
  plan_id: number;
  author: { actor_type: string; agent_id?: number | null; alias: string };
  message: string;
  language: string;
  created_day: number;
  created_time_minutes?: number | null;
  audience_scope: "direct" | "targeted" | "public";
  organizer_attending: boolean;
  scheduled_day: number;
  scheduled_time_minutes: number;
  duration_minutes: number;
  location_id: string;
  recipe_id: string;
  label: Partial<Record<Language, string>>;
  action_ids: string[];
  object_ids: string[];
  variant_recipe_ids: string[];
  deadline_day?: number | null;
  deadline_time_minutes?: number | null;
  wait_minutes: number;
  open_admission_until_end?: boolean;
  min_participants: number;
  max_participants: number;
  accepted_count: number;
  pending_count: number;
  remaining_capacity: number;
  actual_attendance_count: number;
  formation_count_is_attendance: false;
  status: string;
  revision: number;
  reschedule_generation: number;
  ended_reason_code?: string | null;
  viewer_response?: "proposed" | "accepted" | "deferred" | "rejected" | "withdrawn" | null;
  private_response_reasons_exposed: false;
};

export type PhonePlanPost = PhoneInvitationCard | {
  post_id: number;
  post_type: "record";
  fact_chain_id: number;
  activity_id: number;
  plan_id: number;
  author: { actor_type: string; agent_id?: number | null; alias: string };
  message: string;
  language: string;
  created_day: number;
  created_time_minutes?: number | null;
  visibility: string;
  facts: Record<string, unknown>;
};

export type WorldPhone = {
  runtime_version: string;
  world_day: number;
  world_time_minutes: number;
  viewer_actor_key: string;
  posts: PhonePlanPost[];
};

export type InteractionInput = {
  session_id: number;
  post_id?: number;
  agent_id?: number;
  action_type?: EventType;
  event_type?: EventType;
  content?: string;
  response_latency_ms?: number;
  metadata?: Record<string, unknown>;
};

export type EventType =
  | "post_view"
  | "like"
  | "unlike"
  | "skip"
  | "comment"
  | "agent_reply"
  | "user_post"
  | "day_advance"
  | "finish_session";

export type InteractionRecord = {
  interaction_id: number;
  session_id: number;
  event_type: EventType;
  post_id: number;
  agent_id: number | null;
  parent_interaction_id: number | null;
  parent_community_activity_id: number | null;
  content: string;
  created_at: string;
  response_latency_ms: number | null;
  generation_mode: string | null;
  model_provider: string | null;
  model_name: string | null;
  prompt_version: string | null;
  safety_flag: boolean;
  world_day: number | null;
  world_time_minutes: number | null;
  metadata: Record<string, unknown>;
};

export type AgentReplyResult = {
  comment: InteractionRecord;
  agent_reply: InteractionRecord;
  generation_metadata: Record<string, unknown>;
};

export type ScoreResult = {
  session_id: number;
  session_status: string;
  prototype_score: number;
  prototype_signal_label: string;
  prototype_signal_description: string;
  score_version: string;
  score_breakdown: Record<string, unknown>;
  has_sufficient_data: boolean;
  disclaimer: string;
  summary: string;
  text_features: Record<string, number>;
  behavior_features: Record<string, number>;
  data_quality: Record<string, unknown>;
  risk_score: number | null;
  risk_level: string | null;
  crisis_detected: boolean;
};

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type ActivityExperience = {
  world_version?: string;
  runtime_id: number; title: string; location: string; kind: string; status: string; revision: number;
  people: {id: number; name: string}[]; history: {id: number; speaker: string; text: string; kind: string}[];
  suggestions: {id: string; label: string; object_id: string}[];
  catalogue: {id: string; label: string; object_id: string}[];
  speech_done: boolean; pending: {until: string} | null; last_generation_mode?: string;
  demonstration_work?:{work_id:string;title:string;text:string;author:string;day:number;design?:ObjectItem['design']}|null;
  game: {top: string; hand: string[]; finished: boolean; turn: number; mode?:string;target?:number;score?:number;
    winner?:string;others?:{name:string;count:number}[];color?:string;direction?:number;current_name?:string;your_turn?:boolean;playable?:string[];drawn?:string|null;uno_declared?:boolean;rules_version?:string} | null;
};
export const getActivityExperience = (sid: number) => requestJson<{activity: ActivityExperience | null}>(`/sessions/${sid}/world/activity-experience`);
export const changeActivityExperience = (sid: number, rid: number, body: {operation: string; idempotency_key: string; expected_revision?: number; message?: string; speaker_id?: number; actor_agent_id?: number; choice_id?: string; participant_ids?: number[]; inputs?: Record<string,string>}) => requestJson<ActivityExperience>(`/sessions/${sid}/world/activity-experience/${rid}`, {method: "POST", body: JSON.stringify(body)});

export type ObjectItem = {id:string; name:string; text:string;price?:number;art_id?:string;source_url?:string;
  author?:string;day?:number;note?:string;pages?:string[];attribution?:string;source_type?:string;source_action_id?:number;
  design?:{mode?:string;vessel?:string;pieces?:{kind:string;x:number;y:number;angle?:number}[];moves?:{x:number;y:number}[]};
  strokes?:number[][][];stroke_styles?:{color:string;width:number;erase:boolean}[]};
export type ObjectOperation = {id:string;name:string;kind:string;items:ObjectItem[];postcard_status?:{written_today:boolean;can_write:boolean;remaining:number};steps?:string[];venue?:string;can_order?:boolean;order_unavailable_reason?:string;geometry_version?:string;daily_materials?:string[];daily_hint?:string;scenes?:{id:number;name:string;art_id:string;targets:{id:string;name:string}[]}[]};
export type IslandObject = {id:string;name:string;location_id:string;actions:ObjectOperation[];day:number|null;unavailable_reason?:string;daily_note?:string};
export type ObjectExperience = {
  separate_dining?:boolean;
  minute?:number;hours?:{hours:string;open:boolean;closing_in:number|null};
  world_version?:string; residents?:{id:number;name:string;detail:string}[]; objects:IslandObject[]; day:number; seats:Record<string,ObjectItem[]>;
  state:{progress?:Record<string,Record<string,unknown>>;orders?:Record<string,{cart:Record<string,number>;seat:string|null;status:string;owner:string;group?:string;contributions?:Record<string,Record<string,number>>;selections?:string[];items?:Record<string,ObjectItem>;total_price?:number}|null>;rest_seats?:Record<string,string>;public_cards?:{text:string;day:number}[]};
  locations:{id:string;name:string;text:string}[];
  map:{location_nodes:{location_id:string;x:number;y:number}[];paths:{points:number[][]}[]}|null;
};
export const getObjectExperience = (sid:number) => requestJson<ObjectExperience>(`/sessions/${sid}/world/object-experience`);
export type IslandGuide = {id: string; title: string; detail: string; progress: number; total: number};
export const getIslandGuides = (sid: number) => requestJson<{guides: IslandGuide[]; exploration?:IslandGuide[]}>(`/sessions/${sid}/world/holiday-guides`);
export const visitHolidayPhone = (sid: number) => requestJson(`/sessions/${sid}/world/holiday-phone-open`, {method:'POST'});

export async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  headers.set("Content-Type", "application/json");

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    let code: string | undefined;
    try {
      const body = await response.json() as { detail?: string | {message?:string;reason_code?:string}; code?: string };
      const detail = body.detail;
      message = typeof detail === "string" ? detail : detail?.message ?? message;
      code = typeof body.code === "string" ? body.code : typeof detail === "object" ? detail.reason_code : undefined;
    } catch {
      // Keep the generic message if the backend did not return JSON.
    }
    throw new ApiError(
      message,
      response.status,
      code,
      response.headers.get("x-request-id") ?? undefined,
    );
  }

  return response.json() as Promise<T>;
}

export function createSession(
  nickname: string,
  consent: boolean,
  worldVersion?: string,
) {
  return requestJson<{
    session_id: number;
    nickname: string;
    current_day: number;
    total_days: number;
    simulation_seed: number;
    world_version: string;
  }>("/sessions", {
      method: "POST",
      body: JSON.stringify({
        nickname,
        consent,
        consent_version: CONSENT_VERSION,
        ...(worldVersion ? { world_version: worldVersion } : {}),
      }),
    });
}

export function getPosts() {
  return requestJson<Post[]>("/posts");
}

export async function getLocations() {
  const result = await requestJson<
    WorldLocation[] | { locations: WorldLocation[] }
  >("/locations");
  return Array.isArray(result) ? result : result.locations;
}

export function getSessionWorld(sessionId: number, language: Language = "en") {
  return requestJson<WorldSnapshot>(
    `/sessions/${sessionId}/world?language=${encodeURIComponent(language)}`,
  );
}

export function performWorldAction(sessionId: number, input: WorldActionInput) {
  return requestJson<WorldActionResult>(`/sessions/${sessionId}/world/actions`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function sendWorldPulse(
  sessionId: number,
  input: {
    idempotency_key: string;
    expected_revision: number;
    source?: "foreground_timer" | "manual_test";
    language: Language;
  },
) {
  return requestJson<WorldPulseResult>(`/sessions/${sessionId}/island/pulse`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function setWorldSimulationMode(
  sessionId: number,
  input: {
    mode: "running" | "paused";
    idempotency_key: string;
    expected_revision: number;
    language: Language;
  },
) {
  return requestJson<{
    status: "updated" | "unchanged" | "duplicate";
    action_id: number | string;
    world: WorldSnapshot;
  }>(`/sessions/${sessionId}/island/simulation`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function sendWorldConversation(
  sessionId: number,
  input: {
    conversation_id?: number;
    focus_token?: string;
    agent_id: number;
    message: string;
    idempotency_key: string;
    language: Language;
    response_latency_ms?: number;
  },
) {
  return requestJson<WorldConversationResult>(
    `/sessions/${sessionId}/world/conversations`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function startWorldConversation(
  sessionId: number,
  input: {
    agent_id: number;
    duration_minutes?: 5 | 10;
    idempotency_key: string;
    language: Language;
  },
) {
  return requestJson<{
    status: "saved" | "existing";
    action_id?: number | string | null;
    conversation: WorldConversation;
    world: WorldSnapshot;
  }>(`/sessions/${sessionId}/world/conversations/start`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function changeInteractionFocus(sessionId: number, input: {
  operation: "acquire" | "renew" | "release" | "abandon";
  runtime_id?: number; conversation_id?: number; focus_token?: string; idempotency_key: string;
}) {
  return requestJson<{ status: string; applied_minutes: number; focus_token: string }>(
    `/sessions/${sessionId}/world/interaction-focus`, { method: "POST", body: JSON.stringify(input) },
  );
}

export function respondToWorldInteractionPrompt(
  sessionId: number,
  promptId: number,
  input: {
    response: "accept" | "later" | "decline";
    idempotency_key: string;
    language: Language;
    response_latency_ms?: number;
  },
) {
  return requestJson<{
    status: "accepted" | "resolved" | "duplicate";
    action_id: number | string;
    conversation_id?: number | null;
    prompt: WorldInteractionPrompt;
    world: WorldSnapshot;
  }>(
    `/sessions/${sessionId}/world/interaction-prompts/${promptId}/response`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function getSessionFeed(sessionId: number) {
  return requestJson<SimulationFeed>(`/sessions/${sessionId}/feed`);
}

export function getWorldPhone(sessionId: number) {
  return requestJson<WorldPhone>(`/sessions/${sessionId}/world/phone`);
}

export type PlayerActivity = {recipe_id: string; label: Partial<Record<Language, string>>; object_ids: string[]; min_participants?:number; max_participants?:number;
  location_id: string; duration_minutes: number; required_resident_ids: number[]; needs_partner: boolean};

export function getPlayerActivities(sessionId: number) {
  return requestJson<{activities: PlayerActivity[]}>(`/sessions/${sessionId}/world/activity-catalog`);
}

export function getPlayerRecords(sessionId: number) {
  return requestJson<{works?:Array<{title:string;text?:string;day:number;strokes?:number[][][]}>;history: Array<{id: number; world_day: number; time_minutes: number; text: string}>; records: Array<{id: number; body: string; visibility: string; world_day: number}>}>(`/sessions/${sessionId}/world/player-records`);
}

export function invitePlayerActivity(sessionId: number, activity: PlayerActivity, day: number, minute: number, language: Language, residentId?: number | number[], invitationMessage?: string) {
  const ids = activity.required_resident_ids.length ? activity.required_resident_ids : Array.isArray(residentId) ? residentId : residentId ? [residentId] : [];
  return requestJson<{invitation: PhoneInvitationCard}>(`/sessions/${sessionId}/world/phone/invitations`, {
    method: "POST", body: JSON.stringify({recipe_id: activity.recipe_id, idempotency_key: crypto.randomUUID(),
      audience_scope: ids.length ? "targeted" : "public", invitees: ids.map(agent_id => ({actor_type: "resident", agent_id, ...(ids.length===1?{role_id:"guest"}:{}), required: true})),
      location_id: activity.location_id, start_day: day, start_time_minutes: minute,
      project_to_board: false, message: invitationMessage?.trim() || `想约大家一起${activity.label[language] ?? activity.label.en ?? activity.recipe_id}，有空来吗？`, language}),
  });
}

export function changePlayerPlan(sessionId: number, planId: number, revision: number, operation: "start" | "arrive" | "leave" | "cancel" | "accept" | "withdraw") {
  return requestJson(`/sessions/${sessionId}/world/plans/${planId}/transitions`, {
    method: "POST", body: JSON.stringify({transition: operation, expected_revision: revision,
      idempotency_key: crypto.randomUUID(), reason_code: "participant_choice"}),
  });
}

export function viewWorldPhonePost(sessionId: number, postId: number) {
  return requestJson<{ status: string; knowledge_acquired: boolean }>(
    `/sessions/${sessionId}/world/phone/posts/${postId}/view`,
    {
      method: "POST",
      body: JSON.stringify({ idempotency_key: `phone-ui-view:${postId}` }),
    },
  );
}

export function respondWorldPhoneInvitation(
  sessionId: number,
  postId: number,
  input: {
    response: "accept" | "reject" | "defer" | "withdraw";
    expected_revision: number;
    reason_code: string;
    idempotency_key: string;
  },
) {
  return requestJson<{ status: string; invitation: PhoneInvitationCard }>(
    `/sessions/${sessionId}/world/phone/invitations/${postId}/responses`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function advanceSessionDay(sessionId: number, expectedDay: number) {
  return requestJson<{
    session_id: number;
    current_day: number;
    total_days: number;
    virtual_date: string;
    resolved_event: SimulationEvent | null;
  }>(`/sessions/${sessionId}/advance-day`, {
    method: "POST",
    body: JSON.stringify({ expected_day: expectedDay }),
  });
}

export function markNotificationRead(sessionId: number, notificationId: number) {
  return requestJson<{ notification_id: number; is_read: boolean }>(
    `/sessions/${sessionId}/notifications/${notificationId}/read`,
    { method: "POST" },
  );
}

export function saveInteraction(interaction: InteractionInput) {
  return requestJson<{ status: string; interaction_id: number; event_type: EventType }>("/interactions", {
    method: "POST",
    body: JSON.stringify(interaction),
  });
}

export function scoreSession(sessionId: number, language: Language = "en") {
  return requestJson<ScoreResult>(
    `/sessions/${sessionId}/score?language=${encodeURIComponent(language)}`,
  );
}

export async function createAgentReply(input: {
  session_id: number;
  post_id: number;
  agent_id: number;
  user_comment: string;
  parent_interaction_id?: number;
  parent_community_activity_id?: number;
  response_latency_ms?: number;
  language?: Language;
}) {
  const signature=JSON.stringify({...input,response_latency_ms:undefined}),storageKey=`phone-comment:${input.session_id}:${input.post_id}`;
  let pending:{signature:string;key:string}|null=null;
  try{pending=JSON.parse(sessionStorage.getItem(storageKey)??'null');}catch{}
  const key=pending?.signature===signature?pending.key:crypto.randomUUID();
  sessionStorage.setItem(storageKey,JSON.stringify({signature,key}));
  const result=await requestJson<AgentReplyResult>(`/sessions/${input.session_id}/agent-reply`, {
    method: "POST",
    body: JSON.stringify({
      idempotency_key: key,
      post_id: input.post_id,
      agent_id: input.agent_id,
      user_comment: input.user_comment,
      parent_interaction_id: input.parent_interaction_id,
      parent_community_activity_id: input.parent_community_activity_id,
      response_latency_ms: input.response_latency_ms,
      language: input.language ?? "en",
    }),
  });
  sessionStorage.removeItem(storageKey);
  return result;
}

export function publishUserPost(
  sessionId: number,
  content: string,
  language: Language = "en",
  idempotencyKey?: string,
) {
  return requestJson<{
    status: "published" | "existing";
    post_id: number;
    day: number;
    time_minutes: number | null;
    content: string;
    created_at: string;
    interaction_id: number | null;
    source_action_id: number | null;
  }>(`/sessions/${sessionId}/posts`, {
    method: "POST",
    body: JSON.stringify({ content, language, idempotency_key: idempotencyKey }),
  });
}

export type NarrativeProjection = { projection_version: string; arcs: Array<{ arc_id: string; label: Record<string, string>; status: string; nodes: Array<{ node_id: string; status: string; label: Record<string, string>; fact_ids: number[] }> }> };
export function getNarratives(sessionId: number) {
  return requestJson<NarrativeProjection>(`/sessions/${sessionId}/world/narratives`);
}

export type DayReview = {day: number; events: Array<{event_id: number; minute: number; label: string}>; pending_arrangements: Array<{plan_id: number; revision: number; label: string}>; empty_message: string};
export function getDayReview(sessionId: number, language: Language) {
  return requestJson<DayReview>(`/sessions/${sessionId}/world/day-review?language=${language}`);
}

export function finishSession(sessionId: number) {
  return requestJson<{ session_id: number; status: string; ended_at: string }>(
    `/sessions/${sessionId}/finish`,
    {
      method: "POST",
    },
  );
}

export function exportSessionUrl(
  sessionId: number,
  format?: "json",
  scope?: "legacy" | "island",
): string;
export function exportSessionUrl(
  sessionId: number,
  format: "csv",
  scope?: "legacy",
): string;
export function exportSessionUrl(
  sessionId: number,
  format: "json" | "csv" = "json",
  scope: "legacy" | "island" = "legacy",
) {
  if (format === "csv" && scope === "island") {
    throw new Error("Island research export is available as JSON only.");
  }
  return `${API_BASE_URL}/sessions/${sessionId}/export?format=${format}&scope=${scope}`;
}
