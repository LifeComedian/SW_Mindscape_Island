import type { StudioDraft, StudioSystems, StudioStageRecipe } from "./content-studio";

const label = (en: string, zh: string) => ({ en, "zh-CN": zh });
function fresh(values: string[], prefix: string) { let n = 1; while (values.includes(`${prefix}${n}`)) n++; return `${prefix}${n}`; }

export function modularAction(systems: StudioSystems) {
  return { action_id: fresh(systems.action_definitions.map(a => a.action_id), "action_"), label: label("New action", "新动作"), actor_types: ["participant", "resident"], target_types: ["object"], duration_minutes: 5, consequences: [], execution_mode: "execute", location_scope: "co_located", min_participants: 1, max_participants: 20, inputs: [], preconditions: {}, effect_allowlist: [], permission_keys: [], capability_keys: [], interruptible: true, failure_reason_codes: [] };
}
export function modularAffordance(draft: StudioDraft) {
  return { affordance_id: fresh(draft.systems!.affordances.map(a => a.affordance_id), "affordance_"), action_id: draft.systems!.action_definitions[0]?.action_id ?? "", location_ids: draft.locations.locations[0] ? [draft.locations.locations[0].location_id] : [], object_ids: draft.locations.locations[0]?.interaction_points[0] ? [draft.locations.locations[0].interaction_points[0].object_id] : [], enabled: true, conditions: {}, permission_keys: [], capability_keys: [] };
}
export function modularRecipe(draft: StudioDraft) {
  return { recipe_id: fresh(draft.systems!.activity_recipes.map(r => r.recipe_id), "activity_"), label: label("New group activity", "新集体活动"), location_ids: draft.locations.locations[0] ? [draft.locations.locations[0].location_id] : [], action_ids: draft.systems!.action_definitions[0] ? [draft.systems!.action_definitions[0].action_id] : [], object_ids: draft.locations.locations[0]?.interaction_points[0] ? [draft.locations.locations[0].interaction_points[0].object_id] : [], role_slots: ["organizer", "guest"], variant_recipe_ids: [], min_participants: 2, max_participants: 4, duration_minutes: 30, complexity: "coordinated", player_facing: true, conditions: { participant_mode: "required", invitee_role_ids: ["guest"], start_delay_minutes: 30, expires_after_minutes: 30, project_to_board: false, auto_emergence: false } };
}
export function modularStage(draft: StudioDraft): StudioStageRecipe {
  const systems = draft.systems!;
  const id = fresh((systems.stage_recipes ?? []).map(s => s.stage_recipe_id), "stage_recipe_");
  const action = systems.action_definitions[0]?.action_id ?? "";
  const object = systems.affordances.find(a => a.action_id === action)?.object_ids[0] ?? "";
  const choice = (kind: string) => ({ choice_id: "option_1", label: label("Option 1", "方案一"), action_id: kind === "action" ? action : null, object_id: kind === "action" ? object : null, inputs: {}, next_stage_id: kind === "decision" ? "implement" : "close", outcome: null });
  return { stage_recipe_id: id, label: label("Reusable stages", "通用阶段"), allowed_action_ids: action ? [action] : [], terminal_outcomes: ["completed", "timed_out", "not_completed"], max_stages: 3, max_player_choices_per_stage: 4, initial_stage_id: "discuss", stages: (["decision", "action", "closure"] as const).map((kind, i) => ({ stage_id: ["discuss", "implement", "close"][i], label: label(["Discuss", "Implement", "Close"][i], ["讨论并确认", "实际实施", "确认收束"][i]), kind, role_goals: { organizer: "确认合法方案并完成活动", guest: "提供建议，决定是否参加" }, authority_roles: ["organizer"], duration_minutes: 10, timeout_outcome: "timed_out", absence_outcome: "not_completed", enter_conditions: {}, choices: kind === "closure" ? [{ choice_id: "finish", label: label("Finish", "完成"), action_id: null, object_id: null, inputs: {}, next_stage_id: null, outcome: "completed" }] : [choice(kind)] })) };
}
export function upgradeModular(draft: StudioDraft, template: StudioSystems) {
  draft.manifest.schema_version = "content-pack-v5";
  draft.manifest.files.systems = "systems.json";
  const current = draft.systems;
  draft.systems = structuredClone(template);
  if (!current) return;
  draft.systems = { ...draft.systems, ...current, contract_version: template.contract_version };
  draft.systems.action_definitions = current.action_definitions.map(a => ({ ...modularAction(template), ...a, effect_allowlist: a.effect_allowlist ?? Array.from(new Set(a.consequences.map(e => String(e.effect_type)))) }));
  draft.systems.affordances = current.affordances.map(a => ({ conditions: {}, permission_keys: [], capability_keys: [], ...a }));
  draft.systems.activity_recipes = current.activity_recipes.map(r => ({ object_ids: [], role_slots: [], variant_recipe_ids: [], complexity: "ordinary", player_facing: true, conditions: {}, ...r }));
  draft.systems.emergence_policy = { ...template.emergence_policy, ...current.emergence_policy };
}
