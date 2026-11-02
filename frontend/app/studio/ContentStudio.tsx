"use client";

import { useEffect, useRef, useState, type ChangeEvent, type ReactNode } from "react";

import { IslandMap } from "@/components/island/IslandMap";
import { LocationScene } from "@/components/island/LocationScene";
import { NarrativeChoiceOverlay } from "@/components/game/NarrativeChoiceOverlay";
import type {
  WorldActor,
  WorldEvent,
  WorldInteractionPoint,
  WorldLocation,
  WorldVisuals,
} from "@/lib/api";
import { resolveApiAssetUrl } from "@/lib/api";
import {
  exportStudioDraft,
  getStudioPack,
  listStudioPacks,
  validateStudioDraft,
  type LocalizedText,
  type StudioDraft,
  type StudioEvent,
  type StudioFlowEffect,
  type StudioLocation,
  type StudioResident,
  type StudioSocialPublication,
  type StudioTriggerCondition,
  type StudioVisualAsset,
  type StudioVisualSlot,
  type StudioValidation,
} from "@/lib/content-studio";
import type { Language } from "@/lib/i18n";
import { ModularEditor } from "@/components/studio/ModularEditor";
import { modularAction, modularAffordance, modularRecipe } from "@/lib/studio-modular";

type Tab = "manifest" | "map" | "locations" | "residents" | "events" | "systems" | "modular" | "art" | "preview";

type LocalAssetFile = { blob: File; previewUrl: string };

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "manifest", label: "Manifest / Calendar" },
  { id: "map", label: "Map / Paths" },
  { id: "locations", label: "Locations / Objects" },
  { id: "residents", label: "Agents / Schedules" },
  { id: "events", label: "Declarative Events" },
  { id: "systems", label: "Actions / Activities" },
  { id: "modular", label: "模块规则 / 七日模拟" },
  { id: "art", label: "Art Assets" },
  { id: "preview", label: "Scene / Event Preview" },
];

const supportsTypedFlows = (schemaVersion: string) =>
  ["content-pack-v3", "content-pack-v4", "content-pack-v5"].includes(schemaVersion);

export function ContentStudio() {
  const [draft, setDraft] = useState<StudioDraft | null>(null);
  const [packs, setPacks] = useState<Array<{ directory_name: string; kind: "runtime_pack" | "authoring_template" }>>([]);
  const [selectedPack, setSelectedPack] = useState("island_v06");
  const [tab, setTab] = useState<Tab>("manifest");
  const [language, setLanguage] = useState<Language>("en");
  const [selectedLocationId, setSelectedLocationId] = useState("");
  const [selectedResidentId, setSelectedResidentId] = useState<number | null>(null);
  const [selectedEventId, setSelectedEventId] = useState("");
  const [validation, setValidation] = useState<StudioValidation | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [assetFiles, setAssetFiles] = useState<Record<string, LocalAssetFile>>({});
  const [assetErrors, setAssetErrors] = useState<Record<string, string>>({});
  const assetFilesRef = useRef<Record<string, LocalAssetFile>>({});
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void listStudioPacks()
      .then((result) => {
        const names = result.packs.map((pack) => pack.directory_name);
        setPacks(result.packs);
        if (names.length && !names.includes(selectedPack)) setSelectedPack(names[0]);
      })
      .catch((error: unknown) => setNotice(errorMessage(error)));
  }, [selectedPack]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    assetFilesRef.current = assetFiles;
  }, [assetFiles]);

  useEffect(() => () => {
    Object.values(assetFilesRef.current).forEach((item) => URL.revokeObjectURL(item.previewUrl));
  }, []);

  const locations = draft?.locations.locations ?? [];
  const residents = draft?.residents.residents ?? [];
  const events = draft?.events.events ?? [];
  const selectedLocation = locations.find((item) => item.location_id === selectedLocationId) ?? locations[0];
  const selectedResident = residents.find((item) => item.agent_id === selectedResidentId) ?? residents[0];
  const selectedEvent = events.find((item) => item.event_id === selectedEventId) ?? events[0];

  function replaceDraft(next: StudioDraft, changed = true) {
    setDraft(next);
    setDirty(changed);
    setValidation(null);
    setNotice("");
    setAssetErrors({});
    setSelectedLocationId((current) => next.locations.locations.some((item) => item.location_id === current) ? current : next.locations.locations[0]?.location_id ?? "");
    setSelectedResidentId((current) => next.residents.residents.some((item) => item.agent_id === current) ? current : next.residents.residents[0]?.agent_id ?? null);
    setSelectedEventId((current) => next.events.events.some((item) => item.event_id === current) ? current : next.events.events[0]?.event_id ?? "");
  }

  function updateDraft(mutator: (next: StudioDraft) => void) {
    if (!draft) return;
    const next = clone(draft);
    mutator(next);
    replaceDraft(next);
  }

  function clearAssetFiles() {
    Object.values(assetFilesRef.current).forEach((item) => URL.revokeObjectURL(item.previewUrl));
    setAssetFiles({});
  }

  async function importSample(asNew = false) {
    setBusy(true);
    setNotice("");
    try {
      const imported = await getStudioPack(selectedPack);
      clearAssetFiles();
      const next = asNew ? withNewVersions(imported) : imported;
      replaceDraft(next, asNew);
      setNotice(asNew ? "Created a new versioned starter draft." : "Installed sample imported into browser draft.");
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function importJsonFiles(changeEvent: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(changeEvent.target.files ?? []);
    if (!files.length) return;
    try {
      const firstHeader = files.length === 1
        ? new Uint8Array(await files[0].slice(0, 4).arrayBuffer())
        : null;
      const looksLikeZip = Boolean(
        firstHeader &&
        firstHeader[0] === 0x50 &&
        firstHeader[1] === 0x4b &&
        [0x03, 0x05, 0x07].includes(firstHeader[2]) &&
        [0x04, 0x06, 0x08].includes(firstHeader[3]),
      );
      if (files.length === 1 && (files[0].name.toLowerCase().endsWith(".zip") || looksLikeZip)) {
        const imported = await importStudioZip(files[0]);
        clearAssetFiles();
        setAssetFiles(imported.assetFiles);
        replaceDraft(imported.draft);
        setNotice("ZIP imported into an isolated browser draft.");
        return;
      }
      const parts: Partial<StudioDraft> = {};
      for (const file of files) {
        const document = JSON.parse(await file.text()) as Record<string, unknown>;
        if (file.name === "manifest.json" || "schema_version" in document) parts.manifest = document as StudioDraft["manifest"];
        else if (file.name === "map.json" || "map_id" in document) parts.map = document as StudioDraft["map"];
        else if (file.name === "locations.json" || "locations" in document) parts.locations = document as StudioDraft["locations"];
        else if (file.name === "residents.json" || "residents" in document) parts.residents = document as StudioDraft["residents"];
        else if (file.name === "events.json" || "events" in document) parts.events = document as StudioDraft["events"];
        else if (file.name === "visuals.json" || "visual_slots" in document) parts.visuals = document as StudioDraft["visuals"];
        else if (file.name === "systems.json" || "action_definitions" in document) parts.systems = document as StudioDraft["systems"];
      }
      const needsVisuals = ["content-pack-v2", "content-pack-v3", "content-pack-v4", "content-pack-v5"].includes(parts.manifest?.schema_version ?? "");
      const needsSystems = ["content-pack-v4", "content-pack-v5"].includes(parts.manifest?.schema_version ?? "");
      if (!parts.manifest || !parts.map || !parts.locations || !parts.residents || !parts.events || (needsVisuals && !parts.visuals) || (needsSystems && !parts.systems)) {
        throw new Error("Select every JSON document listed by the manifest (including visuals.json and systems.json when required). ");
      }
      clearAssetFiles();
      replaceDraft(parts as StudioDraft);
      setNotice("JSON files imported into browser draft.");
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      changeEvent.target.value = "";
    }
  }

  async function runValidation() {
    if (!draft) return;
    setBusy(true);
    try {
      const result = await validateStudioDraft(draft, localAssetBlobs(assetFiles));
      setValidation(result);
      setNotice(result.valid ? "Runtime-schema validation passed." : "Validation found an issue.");
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function runExport() {
    if (!draft) return;
    setBusy(true);
    try {
      const checked = await validateStudioDraft(draft, localAssetBlobs(assetFiles));
      setValidation(checked);
      if (!checked.valid || checked.version_conflicts.length) {
        setNotice("Fix validation errors and version conflicts before export.");
        return;
      }
      const result = await exportStudioDraft(draft, localAssetBlobs(assetFiles));
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = result.filename;
      anchor.click();
      URL.revokeObjectURL(url);
      setDirty(false);
      setNotice(`Exported ${result.filename}. No installed content or session was changed.`);
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-stone-100 px-4 py-8 text-stone-900">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.2em] text-teal-700">Local development tool</p>
              <h1 className="mt-1 text-3xl font-black">MindScape Content Studio</h1>
              <p className="mt-2 max-w-3xl text-sm text-stone-600">
                Edit an isolated browser draft, validate it with the runtime schema, then download a new ZIP. This page never reads sessions or writes installed packs.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => setLanguage("en")} className={pill(language === "en")}>EN</button>
              <button type="button" onClick={() => setLanguage("zh-CN")} className={pill(language === "zh-CN")}>中文</button>
              <span data-testid="unsaved-status" className={`rounded-full px-3 py-1 text-xs font-bold ${dirty ? "bg-amber-100 text-amber-900" : "bg-emerald-100 text-emerald-900"}`}>
                {dirty ? "Unsaved draft" : "No unsaved changes"}
              </span>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-2">
            <select value={selectedPack} onChange={(event) => setSelectedPack(event.target.value)} className={inputClass} aria-label="Installed sample pack">
              {packs.map((pack) => <option key={pack.directory_name} value={pack.directory_name}>{pack.directory_name}{pack.kind === "authoring_template" ? " · blank authoring template" : " · installed runtime pack"}</option>)}
            </select>
            <button data-testid="studio-import-sample" type="button" disabled={busy || !packs.length} onClick={() => void importSample()} className={buttonClass}>Import sample</button>
            <button data-testid="studio-new-pack" type="button" disabled={busy || !packs.length} onClick={() => void importSample(true)} className={buttonClass}>New starter pack</button>
            <button type="button" onClick={() => fileInput.current?.click()} className={buttonClass}>Import ZIP / JSON</button>
            <input ref={fileInput} type="file" accept="application/zip,.zip,application/json,.json" multiple hidden onChange={(event) => void importJsonFiles(event)} />
            <button data-testid="studio-validate" type="button" disabled={busy || !draft} onClick={() => void runValidation()} className={primaryButtonClass}>Validate</button>
            <button data-testid="studio-export" type="button" disabled={busy || !draft} onClick={() => void runExport()} className={primaryButtonClass}>Export new ZIP</button>
          </div>
          {notice ? <p role="status" className="mt-3 text-sm font-medium text-stone-700">{notice}</p> : null}
        </header>

        {validation ? <ValidationPanel validation={validation} /> : null}

        {!draft ? (
          <section className="rounded-2xl border border-dashed border-stone-300 bg-white p-12 text-center text-stone-600">
            Import an installed sample, create a starter draft, or select the five JSON files from an existing content pack.
          </section>
        ) : (
          <>
            <nav className="flex flex-wrap gap-2" aria-label="Studio editors">
              {TABS.map((item) => (
                <button key={item.id} data-studio-tab={item.id} type="button" onClick={() => setTab(item.id)} className={pill(tab === item.id)}>{item.label}</button>
              ))}
            </nav>
            <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
              {tab === "manifest" ? <ManifestEditor draft={draft} update={updateDraft} /> : null}
              {tab === "map" ? <MapEditor draft={draft} selectedLocationId={selectedLocation?.location_id ?? ""} setSelectedLocationId={setSelectedLocationId} update={updateDraft} language={language} /> : null}
              {tab === "locations" ? <LocationEditor draft={draft} selected={selectedLocation} select={setSelectedLocationId} selectEvent={setSelectedEventId} update={updateDraft} /> : null}
              {tab === "residents" ? <ResidentEditor draft={draft} selected={selectedResident} select={setSelectedResidentId} update={updateDraft} /> : null}
              {tab === "events" ? <EventEditor draft={draft} selected={selectedEvent} select={setSelectedEventId} update={updateDraft} /> : null}
              {tab === "systems" ? <SystemsEditor draft={draft} update={updateDraft} /> : null}
              {tab === "modular" ? <ModularEditor draft={draft} update={updateDraft} /> : null}
              {tab === "art" ? <ArtEditor draft={draft} update={updateDraft} assetFiles={assetFiles} setAssetFiles={setAssetFiles} assetErrors={assetErrors} setAssetErrors={setAssetErrors} language={language} selectedLocation={selectedLocation} selectLocation={setSelectedLocationId} /> : null}
              {tab === "preview" ? <PreviewPanel draft={draft} location={selectedLocation} event={selectedEvent} language={language} selectLocation={setSelectedLocationId} assetFiles={assetFiles} /> : null}
            </section>
          </>
        )}
      </div>
    </main>
  );
}

function ManifestEditor({ draft, update }: EditorProps) {
  const manifest = draft.manifest;
  return (
    <EditorSection title="Package identity and calendar" description="All exported identifiers must be new. Location and event item versions must match their manifest versions.">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Field label="Content pack version"><TextInput testId="content-pack-version" value={manifest.content_pack_version} onChange={(value) => update((next) => { next.manifest.content_pack_version = value; })} /></Field>
        <Field label="World version"><TextInput testId="world-version" value={manifest.world_version} onChange={(value) => update((next) => { next.manifest.world_version = value; next.locations.locations.forEach((location) => { location.version = value; }); })} /></Field>
        <Field label="Event pack version"><TextInput testId="event-pack-version" value={manifest.event_pack_version} onChange={(value) => update((next) => { next.manifest.event_pack_version = value; next.events.events.forEach((item) => { item.version = value; }); })} /></Field>
        <Field label="Map version"><TextInput testId="map-version" value={draft.map.version} onChange={(value) => update((next) => { next.map.version = value; })} /></Field>
        {draft.visuals ? <Field label="Visual version"><TextInput testId="visual-version" value={draft.visuals.visual_version} onChange={(value) => update((next) => { next.visuals!.visual_version = value; })} /></Field> : null}
        <Field label="Start location"><SelectInput value={manifest.start_location_id} options={draft.locations.locations.map((item) => item.location_id)} onChange={(value) => update((next) => { next.manifest.start_location_id = value; })} /></Field>
        <Field label="Total days"><NumberInput value={manifest.calendar.total_days} onChange={(value) => update((next) => { next.manifest.calendar.total_days = value; })} /></Field>
        <Field label="Day start minute"><NumberInput value={manifest.calendar.day_start_minute} onChange={(value) => update((next) => { next.manifest.calendar.day_start_minute = value; })} /></Field>
        <Field label="Day end minute"><NumberInput value={manifest.calendar.day_end_minute} onChange={(value) => update((next) => { next.manifest.calendar.day_end_minute = value; })} /></Field>
        <Field label="Rollover"><SelectInput value={manifest.calendar.rollover} options={["next_day", "clamp"]} onChange={(value) => update((next) => { next.manifest.calendar.rollover = value; })} /></Field>
      </div>
      {manifest.experience ? (
        <section className="mt-6 rounded-xl border border-teal-200 bg-teal-50 p-4">
          <h3 className="font-black text-teal-950">Open exploration and departure</h3>
          <div className="mt-3 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            <Field label="Recommended days"><NumberInput value={manifest.experience.recommended_total_days} onChange={(value) => update((next) => { next.manifest.experience!.recommended_total_days = value; })} /></Field>
            <Field label="Audit contract"><TextInput value={manifest.experience.behavior_audit_version} onChange={(value) => update((next) => { next.manifest.experience!.behavior_audit_version = value; })} /></Field>
            <label className="flex items-center gap-2 text-sm font-bold"><input type="checkbox" checked={manifest.experience.final_day_departure_required} onChange={(event) => update((next) => { next.manifest.experience!.final_day_departure_required = event.target.checked; })} /> Require final-day departure</label>
            <LocalizedFields label="Departure prompt" value={manifest.experience.departure_prompt} onChange={(locale, value) => update((next) => { next.manifest.experience!.departure_prompt[locale] = value; })} />
          </div>
        </section>
      ) : null}
      <h3 className="mt-6 text-lg font-bold">Action duration defaults</h3>
      <div className="mt-3 grid gap-3 md:grid-cols-3 lg:grid-cols-5">
        {Object.entries(manifest.action_minutes).map(([actionType, minutes]) => (
          <Field key={actionType} label={actionType}><NumberInput value={minutes} onChange={(value) => update((next) => { next.manifest.action_minutes[actionType] = value; })} /></Field>
        ))}
      </div>
      <button data-testid="studio-new-versions" type="button" className={`${buttonClass} mt-5`} onClick={() => update((next) => Object.assign(next, withNewVersions(next)))}>Prepare new versions</button>
    </EditorSection>
  );
}

function MapEditor({ draft, selectedLocationId, setSelectedLocationId, update, language }: EditorProps & { selectedLocationId: string; setSelectedLocationId: (id: string) => void; language: Language }) {
  const [connectionTarget, setConnectionTarget] = useState("");
  const node = draft.map.location_nodes.find((item) => item.location_id === selectedLocationId) ?? draft.map.location_nodes[0];
  const layout = draft.map.scene_layouts.find((item) => item.location_id === node?.location_id);
  function moveLocation(locationId: string, x: number, y: number) {
    update((next) => {
      const node = next.map.location_nodes.find((item) => item.location_id === locationId);
      if (!node) return;
      node.x = x;
      node.y = y;
      next.map.paths.forEach((path) => {
        if (path.from_location_id === locationId) path.points[0] = [x, y];
        if (path.to_location_id === locationId) path.points[path.points.length - 1] = [x, y];
      });
    });
  }
  return (
    <EditorSection title="Map and paths" description="Select and drag a place marker. Endpoint coordinates of connected paths follow automatically.">
      <div className="mb-5 grid gap-3 rounded-xl border border-stone-200 bg-stone-50 p-4 md:grid-cols-3 lg:grid-cols-6">
        <Field label="Map ID"><TextInput value={draft.map.map_id} onChange={(value) => update((next) => { next.map.map_id = value; if (next.visuals) { const slot = next.visuals.visual_slots.find((item) => item.slot_id === "map.image"); if (slot) slot.target_id = value; } })} /></Field>
        <Field label="Width"><NumberInput value={draft.map.width} onChange={(value) => update((next) => { next.map.width = value; })} /></Field>
        <Field label="Height"><NumberInput value={draft.map.height} onChange={(value) => update((next) => { next.map.height = value; })} /></Field>
        <Field label="Style"><SelectInput value={draft.map.background.style_key} options={["island_day", "island_sunset", "minimal"]} onChange={(value) => update((next) => { next.map.background.style_key = value; })} /></Field>
        <Field label="Sea"><SelectInput value={draft.map.background.sea_color_key} options={["sea_blue", "sea_teal"]} onChange={(value) => update((next) => { next.map.background.sea_color_key = value; })} /></Field>
        <Field label="Land"><SelectInput value={draft.map.background.land_color_key} options={["land_green", "land_sand"]} onChange={(value) => update((next) => { next.map.background.land_color_key = value; })} /></Field>
      </div>
      <IslandMap
        map={draft.map}
        locations={worldLocations(draft)}
        actors={[]}
        language={language}
        currentLocationId={selectedLocationId}
        selectedLocationId={selectedLocationId}
        selectedActorId={null}
        statusForLocation={() => "reachable"}
        statusLabelForLocation={() => "Editable"}
        onSelectLocation={setSelectedLocationId}
        onSelectActor={() => undefined}
        editable
        onMoveLocation={moveLocation}
      />
      {node && layout ? (
        <section data-testid="studio-map-node-settings" className="mt-5 rounded-xl border border-stone-200 p-4">
          <h3 className="font-black">Selected place geometry: {node.location_id}</h3>
          <div className="mt-3 grid gap-3 md:grid-cols-3 lg:grid-cols-6">
            <Field label="Map X"><NumberInput value={node.x} onChange={(value) => moveLocation(node.location_id, value, node.y)} /></Field>
            <Field label="Map Y"><NumberInput value={node.y} onChange={(value) => moveLocation(node.location_id, node.x, value)} /></Field>
            <Field label="Click radius"><NumberInput value={node.click_radius} onChange={(value) => update((next) => { next.map.location_nodes.find((item) => item.location_id === node.location_id)!.click_radius = value; })} /></Field>
            <Field label="Icon"><SelectInput value={node.icon_key} options={["cottage", "homes", "square", "harbor", "restaurant", "shop", "lighthouse"]} onChange={(value) => update((next) => { next.map.location_nodes.find((item) => item.location_id === node.location_id)!.icon_key = value; })} /></Field>
            <Field label="Scene width"><NumberInput value={layout.width} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.width = value; })} /></Field>
            <Field label="Scene height"><NumberInput value={layout.height} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.height = value; })} /></Field>
            <Field label="Spawn X"><NumberInput value={layout.participant_spawn[0]} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.participant_spawn[0] = value; })} /></Field>
            <Field label="Spawn Y"><NumberInput value={layout.participant_spawn[1]} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.participant_spawn[1] = value; })} /></Field>
          </div>
          {["content-pack-v4", "content-pack-v5"].includes(draft.manifest.schema_version) ? (
            <div className="mt-5 border-t border-stone-200 pt-4">
              <div className="flex items-center justify-between gap-3">
                <div><h4 className="font-black">Image hotspots</h4><p className="text-xs text-stone-600">Transparent keyboard-accessible regions over the scene image, linked to an interaction point.</p></div>
                <button data-testid="studio-add-hotspot" type="button" disabled={!draft.locations.locations.find((item) => item.location_id === node.location_id)?.interaction_points.length} className={buttonClass} onClick={() => update((next) => addSceneHotspot(next, node.location_id))}>Add hotspot</button>
              </div>
              <div className="mt-3 space-y-3">
                {(layout.hotspots ?? []).map((hotspot, hotspotIndex) => (
                  <div key={hotspot.hotspot_id} data-testid={`studio-hotspot-${hotspot.hotspot_id}`} className="grid gap-3 rounded-lg border border-stone-200 p-3 md:grid-cols-3 lg:grid-cols-6">
                    <Field label="Hotspot ID"><TextInput value={hotspot.hotspot_id} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.hotspots![hotspotIndex].hotspot_id = value; })} /></Field>
                    <Field label="Target object"><SelectInput value={hotspot.target_object_id} options={draft.locations.locations.find((item) => item.location_id === node.location_id)?.interaction_points.map((item) => item.object_id) ?? []} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.hotspots![hotspotIndex].target_object_id = value; })} /></Field>
                    <Field label="Shape"><SelectInput value={hotspot.shape} options={["circle", "rectangle"]} onChange={(value) => update((next) => setHotspotShape(next, node.location_id, hotspotIndex, value as "circle" | "rectangle"))} /></Field>
                    <Field label="X"><NumberInput value={hotspot.x} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.hotspots![hotspotIndex].x = value; })} /></Field>
                    <Field label="Y"><NumberInput value={hotspot.y} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.hotspots![hotspotIndex].y = value; })} /></Field>
                    {hotspot.shape === "circle" ? <Field label="Radius"><NumberInput value={hotspot.radius ?? 30} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.hotspots![hotspotIndex].radius = value; })} /></Field> : <><Field label="Width"><NumberInput value={hotspot.width ?? 60} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.hotspots![hotspotIndex].width = value; })} /></Field><Field label="Height"><NumberInput value={hotspot.height ?? 60} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.hotspots![hotspotIndex].height = value; })} /></Field></>}
                    <LocalizedFields label="Accessible label" value={{ en: hotspot.label.en ?? "", "zh-CN": hotspot.label["zh-CN"] ?? "" }} onChange={(locale, value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.hotspots![hotspotIndex].label[locale] = value; })} />
                    <Field label="Log code"><TextInput value={hotspot.log_code} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.hotspots![hotspotIndex].log_code = value; })} /></Field>
                    <button type="button" className={dangerButtonClass} onClick={() => update((next) => { next.map.scene_layouts.find((item) => item.location_id === node.location_id)!.hotspots!.splice(hotspotIndex, 1); })}>Remove hotspot</button>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}
      <section className="mt-5 rounded-xl border border-stone-200 p-4">
        <h3 className="font-black">Land boundary</h3>
        <p className="mt-1 text-xs text-stone-600">At least three vertices are required once the world has locations.</p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          {draft.map.land_polygon.map((point, index) => (
            <div key={index} className="grid grid-cols-[1fr_1fr_auto] gap-2">
              <NumberInput value={point[0]} onChange={(value) => update((next) => { next.map.land_polygon[index][0] = value; })} />
              <NumberInput value={point[1]} onChange={(value) => update((next) => { next.map.land_polygon[index][1] = value; })} />
              <button type="button" disabled={draft.map.land_polygon.length <= 3} className={dangerButtonClass} onClick={() => update((next) => { next.map.land_polygon.splice(index, 1); })}>Remove</button>
            </div>
          ))}
        </div>
        <button type="button" className={`${buttonClass} mt-3`} onClick={() => update((next) => { next.map.land_polygon.push([next.map.width / 2, next.map.height / 2]); })}>Add boundary vertex</button>
      </section>
      {node && draft.map.location_nodes.length > 1 ? (
        <section className="mt-5 flex flex-wrap items-end gap-3 rounded-xl border border-stone-200 p-4">
          <Field label="Connect selected place to"><SelectInput value={connectionTarget || draft.map.location_nodes.find((item) => item.location_id !== node.location_id)?.location_id || ""} options={draft.map.location_nodes.filter((item) => item.location_id !== node.location_id).map((item) => item.location_id)} onChange={setConnectionTarget} /></Field>
          <button data-testid="studio-add-map-connection" type="button" className={buttonClass} onClick={() => update((next) => addMapConnection(next, node.location_id, connectionTarget || next.map.location_nodes.find((item) => item.location_id !== node.location_id)?.location_id || ""))}>Add connection</button>
        </section>
      ) : null}
      <div className="mt-5 space-y-3">
        {draft.map.paths.map((path, index) => {
          const midpointIndex = Math.floor(path.points.length / 2);
          const midpoint = path.points[midpointIndex];
          return (
            <div key={path.path_id} data-testid={`studio-path-${path.path_id}`} className="grid items-end gap-3 rounded-lg border border-stone-200 p-3 md:grid-cols-[1fr_1fr_110px_110px_auto]">
              <Field label="Path ID"><TextInput value={path.path_id} onChange={(value) => update((next) => { next.map.paths[index].path_id = value; })} /></Field>
              <p className="pb-2 text-sm text-stone-600">{path.from_location_id} → {path.to_location_id}</p>
              <Field label="Midpoint X"><NumberInput value={midpoint[0]} onChange={(value) => update((next) => { next.map.paths[index].points[midpointIndex][0] = value; })} /></Field>
              <Field label="Midpoint Y"><NumberInput value={midpoint[1]} onChange={(value) => update((next) => { next.map.paths[index].points[midpointIndex][1] = value; })} /></Field>
              <button type="button" className={dangerButtonClass} onClick={() => update((next) => removePath(next, index))}>Remove path</button>
            </div>
          );
        })}
      </div>
    </EditorSection>
  );
}

function LocationEditor({ draft, selected, select, selectEvent, update }: EditorProps & { selected?: StudioLocation; select: (id: string) => void; selectEvent: (id: string) => void }) {
  if (!selected) return (
    <EditorSection title="Locations and interaction points" description="Start an empty world by creating its first location. It becomes the initial location and creates only new blank map/scene scaffolding.">
      <div className="rounded-xl border border-dashed border-teal-300 bg-teal-50 p-8 text-center">
        <p className="text-sm text-teal-950">This authoring template has no locations or objects yet.</p>
        <button data-testid="studio-add-first-location" type="button" className={`${primaryButtonClass} mt-4`} onClick={() => update((next) => addLocation(next, ""))}>Create first location</button>
      </div>
    </EditorSection>
  );
  const index = draft.locations.locations.findIndex((item) => item.location_id === selected.location_id);
  return (
    <EditorSection title="Locations and interaction points" description="Additions include a map node, scene layout, and a bidirectional path to the selected place.">
      <EntityToolbar values={draft.locations.locations.map((item) => ({ id: item.location_id, label: item.name.en }))} selected={selected.location_id} onSelect={select} selectTestId="studio-location-select" onAdd={() => update((next) => addLocation(next, selected.location_id))} addTestId="studio-add-location" addLabel="Add connected location" onDelete={() => update((next) => deleteLocation(next, selected.location_id))} />
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <Field label="Location ID"><RenamableIdInput key={selected.location_id} value={selected.location_id} onCommit={(value) => { update((next) => renameLocation(next, selected.location_id, value)); select(value); }} /></Field>
        <Field label="Scene type"><TextInput value={selected.scene_type} onChange={(value) => update((next) => { next.locations.locations[index].scene_type = value; })} /></Field>
        <LocalizedFields label="Name" value={selected.name} onChange={(locale, value) => update((next) => { next.locations.locations[index].name[locale] = value; })} />
        <LocalizedFields label="Description" value={selected.description} multiline onChange={(locale, value) => update((next) => { next.locations.locations[index].description[locale] = value; })} />
        <Field label="Event pool IDs (comma separated)"><TextInput value={selected.event_pool_ids.join(", ")} onChange={(value) => update((next) => { next.locations.locations[index].event_pool_ids = csv(value); })} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selected.opening_hours.always_open} onChange={(event) => update((next) => { next.locations.locations[index].opening_hours.always_open = event.target.checked; })} />Always open</label>
      </div>
      <h3 className="mt-6 text-lg font-bold">Allowed player actions</h3>
      <div className="mt-2 flex flex-wrap gap-3">
        {["move", "observe", "approach", "wait", "end_day", "end_conversation", "event_action"].map((actionType) => (
          <label key={actionType} className="flex items-center gap-2 rounded-lg border border-stone-200 px-3 py-2 text-sm"><input type="checkbox" checked={selected.allowed_actions.includes(actionType)} onChange={(event) => update((next) => toggleString(next.locations.locations[index].allowed_actions, actionType, event.target.checked))} />{actionType}</label>
        ))}
      </div>
      <h3 className="mt-6 text-lg font-bold">Interaction points</h3>
      <div className="mt-3 space-y-3">
        {selected.interaction_points.map((point, pointIndex) => (
          <div key={point.object_id} className="grid gap-3 rounded-lg border border-stone-200 p-3 md:grid-cols-3">
            <Field label="Object ID"><RenamableIdInput value={point.object_id} onCommit={(value) => update((next) => renameInteractionPoint(next, selected.location_id, point.object_id, value))} /></Field>
            <Field label="Type"><TextInput value={point.type} onChange={(value) => update((next) => { next.locations.locations[index].interaction_points[pointIndex].type = value; })} /></Field>
            <Field label="Renderer"><SelectInput value={point.renderer_key} options={["desk", "notice", "garden", "table", "books", "bench", "railing", "counter", "shelf", "display", "landmark", "seat"]} onChange={(value) => update((next) => { next.locations.locations[index].interaction_points[pointIndex].renderer_key = value; })} /></Field>
            <LocalizedFields label="Name" value={point.name} onChange={(locale, value) => update((next) => { next.locations.locations[index].interaction_points[pointIndex].name[locale] = value; })} />
            <LocalizedFields label="Description" value={point.description} multiline onChange={(locale, value) => update((next) => { next.locations.locations[index].interaction_points[pointIndex].description[locale] = value; })} />
            {(() => {
              const position = draft.map.scene_layouts.find((item) => item.location_id === selected.location_id)?.interaction_point_positions[point.object_id];
              return position ? <><Field label="Scene X"><NumberInput value={position[0]} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === selected.location_id)!.interaction_point_positions[point.object_id][0] = value; })} /></Field><Field label="Scene Y"><NumberInput value={position[1]} onChange={(value) => update((next) => { next.map.scene_layouts.find((item) => item.location_id === selected.location_id)!.interaction_point_positions[point.object_id][1] = value; })} /></Field></> : null;
            })()}
            {["content-pack-v3", "content-pack-v4", "content-pack-v5"].includes(draft.manifest.schema_version) ? (
              <div className="md:col-span-3 rounded-lg border border-teal-200 bg-teal-50 p-3">
                <p className="text-xs font-black uppercase tracking-wide text-teal-800">Interaction options and consequences</p>
                {point.interaction_event_id ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span className="text-sm text-teal-950">Linked flow: <code>{point.interaction_event_id}</code></span>
                    <button data-testid={`studio-edit-object-flow-${point.object_id}`} type="button" className={buttonClass} onClick={() => { selectEvent(point.interaction_event_id!); document.querySelector<HTMLButtonElement>('button[data-studio-tab="events"]')?.click(); }}>Edit in flow designer</button>
                    <button type="button" className={dangerButtonClass} onClick={() => update((next) => { delete next.locations.locations[index].interaction_points[pointIndex].interaction_event_id; })}>Unlink flow</button>
                  </div>
                ) : (
                  <button data-testid={`studio-create-object-flow-${point.object_id}`} type="button" className={`${primaryButtonClass} mt-2`} onClick={() => update((next) => createInteractionFlow(next, selected.location_id, point.object_id))}>Create interaction flow</button>
                )}
              </div>
            ) : null}
            <button type="button" className={dangerButtonClass} onClick={() => update((next) => deleteInteractionPoint(next, selected.location_id, point.object_id))}>Remove object</button>
          </div>
        ))}
      </div>
      <button data-testid="studio-add-interaction" type="button" className={`${buttonClass} mt-3`} onClick={() => update((next) => addInteractionPoint(next, selected.location_id))}>Add interaction point</button>
    </EditorSection>
  );
}

function ResidentEditor({ draft, selected, select, update }: EditorProps & { selected?: StudioResident; select: (id: number) => void }) {
  if (!selected) return (
    <EditorSection title="Agents and schedules" description="Create residents from new safe defaults; no existing character is copied.">
      <div className="rounded-xl border border-dashed border-teal-300 bg-teal-50 p-8 text-center">
        <p className="text-sm text-teal-950">{draft.locations.locations.length ? "No residents yet." : "Create a location before adding a resident."}</p>
        <button data-testid="studio-add-first-resident" type="button" disabled={!draft.locations.locations.length} className={`${primaryButtonClass} mt-4`} onClick={() => update(addResident)}>Create first resident</button>
      </div>
    </EditorSection>
  );
  const index = draft.residents.residents.findIndex((item) => item.agent_id === selected.agent_id);
  return (
    <EditorSection title="Agents and schedules" description="Each resident remains data-only. Runtime validation checks schedule coverage, overlaps, locations, and travel continuity.">
      <EntityToolbar values={draft.residents.residents.map((item) => ({ id: String(item.agent_id), label: item.name }))} selected={String(selected.agent_id)} onSelect={(id) => select(Number(id))} selectTestId="studio-resident-select" onAdd={() => update(addResident)} addTestId="studio-add-resident" addLabel="Add agent with schedule" onDelete={() => update((next) => deleteResident(next, selected.agent_id))} />
      <div className="mt-5 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Field label="Agent ID"><RenamableIdInput key={selected.agent_id} value={String(selected.agent_id)} numeric onCommit={(value) => { const id = Number(value); update((next) => renameResident(next, selected.agent_id, id)); select(id); }} /></Field>
        <Field label="Name"><TextInput value={selected.name} onChange={(value) => update((next) => { next.residents.residents[index].name = value; })} /></Field>
        <Field label="Adult age range"><TextInput value={selected.adult_age_range} onChange={(value) => update((next) => { next.residents.residents[index].adult_age_range = value; })} /></Field>
        <Field label="Home"><SelectInput value={selected.home_location_id} options={draft.locations.locations.map((item) => item.location_id)} onChange={(value) => update((next) => { next.residents.residents[index].home_location_id = value; })} /></Field>
        <Field label="Avatar"><SelectInput value={selected.avatar_key} options={["mira", "leo", "chen", "nova", "kai", "resident_default"]} onChange={(value) => update((next) => { next.residents.residents[index].avatar_key = value; })} /></Field>
        <Field label="Marker color"><SelectInput value={selected.marker_color_key} options={["resident_teal", "resident_blue", "resident_amber", "resident_rose", "resident_violet"]} onChange={(value) => update((next) => { next.residents.residents[index].marker_color_key = value; })} /></Field>
        <Field label="Profile version"><TextInput value={selected.profile_version} onChange={(value) => update((next) => { next.residents.residents[index].profile_version = value; })} /></Field>
        <Field label="Prompt version"><TextInput value={selected.prompt_version} onChange={(value) => update((next) => { next.residents.residents[index].prompt_version = value; })} /></Field>
        <LocalizedFields label="Role" value={selected.role} onChange={(locale, value) => update((next) => { next.residents.residents[index].role[locale] = value; })} />
        <LocalizedFields label="Public summary" value={selected.public_summary} onChange={(locale, value) => update((next) => { next.residents.residents[index].public_summary[locale] = value; })} />
        <LocalizedFields label="Background" value={selected.background} multiline onChange={(locale, value) => update((next) => { next.residents.residents[index].background[locale] = value; })} />
        <LocalizedFields label="Personality" value={selected.personality} multiline onChange={(locale, value) => update((next) => { next.residents.residents[index].personality[locale] = value; })} />
        <LocalizedFields label="Communication style" value={selected.communication_style} multiline onChange={(locale, value) => update((next) => { next.residents.residents[index].communication_style[locale] = value; })} />
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        {(["values", "preferences", "goals", "knowledge_boundaries", "avoid_patterns", "safety_rules"] as const).map((key) => (
          <LocalizedListEditor key={key} label={key.replaceAll("_", " ")} values={selected[key]} onChange={(values) => update((next) => { next.residents.residents[index][key] = values; })} />
        ))}
      </div>
      {selected.autonomy ? (
        <section data-testid="studio-resident-autonomy" className="mt-6 rounded-xl border border-indigo-200 bg-indigo-50 p-4">
          <h3 className="font-black">Resident autonomy</h3>
          <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={selected.autonomy.enabled} onChange={(event) => update((next) => { next.residents.residents[index].autonomy!.enabled = event.target.checked; })} />Enable autonomous actions</label>
          <div className="mt-3 flex flex-wrap gap-2">
            {(["idle", "inspect_object", "socialize_resident", "greet_participant", "visit_adjacent_location"] as const).map((intent) => <label key={intent} className="flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm"><input type="checkbox" checked={selected.autonomy!.allowed_intents.includes(intent)} onChange={(event) => update((next) => toggleString(next.residents.residents[index].autonomy!.allowed_intents, intent, event.target.checked))} />{intent}</label>)}
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-3 lg:grid-cols-6">
            <Field label="Cooldown"><NumberInput value={selected.autonomy.action_cooldown_minutes} onChange={(value) => update((next) => { next.residents.residents[index].autonomy!.action_cooldown_minutes = value; })} /></Field>
            {(["idle_weight", "inspect_weight", "socialize_weight", "greet_weight", "travel_weight"] as const).map((key) => <Field key={key} label={key.replace("_weight", "")}><NumberInput value={selected.autonomy![key]} onChange={(value) => update((next) => { next.residents.residents[index].autonomy![key] = value; })} /></Field>)}
            <Field label="Preferred places"><TextInput value={selected.autonomy.preferred_location_ids.join(", ")} onChange={(value) => update((next) => { next.residents.residents[index].autonomy!.preferred_location_ids = csv(value); })} /></Field>
            <Field label="Free-time states"><TextInput value={selected.autonomy.free_time_state_ids.join(", ")} onChange={(value) => update((next) => { next.residents.residents[index].autonomy!.free_time_state_ids = csv(value); })} /></Field>
          </div>
        </section>
      ) : null}
      <h3 className="mt-6 text-lg font-bold">Schedule blocks</h3>
      <div className="mt-3 space-y-3">
        {selected.schedule.map((block, blockIndex) => (
          <div key={`${block.state_id}-${blockIndex}`} data-testid="studio-schedule-block" className="grid items-end gap-3 rounded-lg border border-stone-200 p-3 md:grid-cols-5">
            <Field label="State ID"><TextInput value={block.state_id} onChange={(value) => update((next) => { next.residents.residents[index].schedule[blockIndex].state_id = value; })} /></Field>
            <Field label="Start"><NumberInput value={block.start_minute} onChange={(value) => update((next) => { next.residents.residents[index].schedule[blockIndex].start_minute = value; })} /></Field>
            <Field label="End"><NumberInput value={block.end_minute} onChange={(value) => update((next) => { next.residents.residents[index].schedule[blockIndex].end_minute = value; })} /></Field>
            <Field label="Location"><SelectInput value={block.location_id} options={draft.locations.locations.map((item) => item.location_id)} onChange={(value) => update((next) => { next.residents.residents[index].schedule[blockIndex].location_id = value; })} /></Field>
            <Field label="Days (blank = every day)"><TextInput value={block.days?.join(", ") ?? ""} onChange={(value) => update((next) => { const target = next.residents.residents[index].schedule[blockIndex]; const days = csv(value).map(Number).filter(Number.isInteger); if (days.length) target.days = days; else delete target.days; })} /></Field>
            <button type="button" className={dangerButtonClass} onClick={() => update((next) => { next.residents.residents[index].schedule.splice(blockIndex, 1); })}>Remove block</button>
            <LocalizedFields label="Activity" value={block.activity} onChange={(locale, value) => update((next) => { next.residents.residents[index].schedule[blockIndex].activity[locale] = value; })} />
            <LocalizedFields label="Goal" value={block.goal} onChange={(locale, value) => update((next) => { next.residents.residents[index].schedule[blockIndex].goal[locale] = value; })} />
          </div>
        ))}
      </div>
      <button type="button" className={`${buttonClass} mt-3`} onClick={() => update((next) => addScheduleBlock(next, selected.agent_id))}>Add schedule block</button>
    </EditorSection>
  );
}

function EventEditor({ draft, selected, select, update }: EditorProps & { selected?: StudioEvent; select: (id: string) => void }) {
  if (!selected) return (
    <EditorSection title="Declarative events" description="Events can be created after the world has a location to reference.">
      <div className="rounded-xl border border-dashed border-teal-300 bg-teal-50 p-8 text-center">
        <p className="text-sm text-teal-950">{draft.locations.locations.length ? "No events yet." : "Create a location before adding an event."}</p>
        <button data-testid="studio-add-first-event" type="button" disabled={!draft.locations.locations.length} className={`${primaryButtonClass} mt-4`} onClick={() => update(addEvent)}>Create first event</button>
      </div>
    </EditorSection>
  );
  const index = draft.events.events.findIndex((item) => item.event_id === selected.event_id);
  const behavioralStages = selected.stages ?? [];
  return (
    <EditorSection title="Declarative events" description="References, trigger windows, follow-ups, action payloads, and event-pool membership use the same validator as runtime loading.">
      <EntityToolbar values={draft.events.events.map((item) => ({ id: item.event_id, label: item.title.en }))} selected={selected.event_id} onSelect={select} selectTestId="studio-event-select" onAdd={() => update((next) => addEvent(next))} addTestId="studio-add-event" addLabel="Add event" onDelete={() => update((next) => { next.events.events = next.events.events.filter((item) => item.event_id !== selected.event_id); })} />
      <div className="mt-5 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Field label="Event ID"><RenamableIdInput key={selected.event_id} value={selected.event_id} onCommit={(value) => { update((next) => renameEvent(next, selected.event_id, value)); select(value); }} /></Field>
        <Field label="Event type"><TextInput value={selected.event_type} onChange={(value) => update((next) => { next.events.events[index].event_type = value; })} /></Field>
        <Field label="Trigger"><SelectInput value={selected.trigger.type} options={["on_location_enter", "on_world_tick", "on_time_window", "on_object_interact"]} onChange={(value) => update((next) => { const trigger = next.events.events[index].trigger; trigger.type = value; if (value === "on_time_window") trigger.time_window ??= { start_minute: next.manifest.calendar.day_start_minute, end_minute: next.manifest.calendar.day_end_minute }; })} /></Field>
        <Field label="Location IDs (comma separated)"><TextInput testId="studio-event-location-ids" value={selected.location_ids.join(", ")} onChange={(value) => update((next) => { next.events.events[index].location_ids = csv(value); })} /></Field>
        <Field label="Pool IDs (comma separated)"><TextInput value={selected.event_pool_ids.join(", ")} onChange={(value) => update((next) => { next.events.events[index].event_pool_ids = csv(value); })} /></Field>
        <Field label="Weight"><NumberInput value={selected.weight} step="0.1" onChange={(value) => update((next) => { next.events.events[index].weight = value; })} /></Field>
        <Field label="Cooldown minutes"><NumberInput value={selected.cooldown_minutes} onChange={(value) => update((next) => { next.events.events[index].cooldown_minutes = value; })} /></Field>
        <Field label="Maximum occurrences"><NumberInput value={selected.max_occurrences} onChange={(value) => update((next) => { next.events.events[index].max_occurrences = value; })} /></Field>
        <Field label="Renderer key"><TextInput value={selected.renderer_key ?? "behavioral_event"} onChange={(value) => update((next) => { next.events.events[index].renderer_key = value; })} /></Field>
        {selected.trigger.type === "on_time_window" ? <><Field label="Window start"><NumberInput value={selected.trigger.time_window?.start_minute ?? draft.manifest.calendar.day_start_minute} onChange={(value) => update((next) => { next.events.events[index].trigger.time_window ??= { start_minute: value, end_minute: next.manifest.calendar.day_end_minute }; next.events.events[index].trigger.time_window!.start_minute = value; })} /></Field><Field label="Window end"><NumberInput value={selected.trigger.time_window?.end_minute ?? draft.manifest.calendar.day_end_minute} onChange={(value) => update((next) => { next.events.events[index].trigger.time_window ??= { start_minute: next.manifest.calendar.day_start_minute, end_minute: value }; next.events.events[index].trigger.time_window!.end_minute = value; })} /></Field></> : null}
        <LocalizedFields label="Title" value={selected.title} onChange={(locale, value) => update((next) => { next.events.events[index].title[locale] = value; })} />
        <LocalizedFields label="Stimulus" value={selected.stimulus} multiline onChange={(locale, value) => update((next) => { next.events.events[index].stimulus[locale] = value; })} />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selected.exclusion_flags.active_scenario ?? false} onChange={(event) => update((next) => { next.events.events[index].exclusion_flags.active_scenario = event.target.checked; })} />Exclude while a scenario is active</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selected.exclusion_flags.active_event ?? false} onChange={(event) => update((next) => { next.events.events[index].exclusion_flags.active_event = event.target.checked; })} />Exclude while another event is active</label>
      </div>
      <details className="mt-5 rounded-xl border border-stone-200 bg-stone-50 p-4">
        <summary className="cursor-pointer font-bold">Advanced prerequisites, logging, and context</summary>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <JsonObjectField key={`${selected.event_id}:prerequisites`} label="Prerequisites" value={selected.prerequisites} onChange={(value) => update((next) => { next.events.events[index].prerequisites = value; })} />
          <JsonObjectField key={`${selected.event_id}:logging-v3`} label="Logging config" value={selected.logging_config} onChange={(value) => update((next) => { next.events.events[index].logging_config = value; })} />
          <JsonObjectField key={`${selected.event_id}:llm-v3`} label="LLM context" value={selected.llm_context} onChange={(value) => update((next) => { next.events.events[index].llm_context = value; })} />
        </div>
      </details>
      <SocialPropagationEditor draft={draft} eventIndex={index} update={update} />
      {["content-pack-v3", "content-pack-v4", "content-pack-v5"].includes(draft.manifest.schema_version) ? <TriggerConditionBuilder draft={draft} eventIndex={index} update={update} /> : null}
      {["content-pack-v3", "content-pack-v4", "content-pack-v5"].includes(draft.manifest.schema_version) && selected.stages?.length ? (
        <FlowEditor draft={draft} eventIndex={index} update={update} />
      ) : selected.stages?.length ? (
        <section className="mt-6 space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Renderer key"><TextInput value={selected.renderer_key ?? "behavioral_event"} onChange={(value) => update((next) => { next.events.events[index].renderer_key = value; })} /></Field>
            <Field label="Initial stage"><SelectInput value={selected.initial_stage_id ?? selected.stages[0].stage_id} options={selected.stages.map((stage) => stage.stage_id)} onChange={(value) => update((next) => { next.events.events[index].initial_stage_id = value; })} /></Field>
            <JsonObjectField key={`${selected.event_id}:logging`} label="Logging config" value={selected.logging_config} onChange={(value) => update((next) => { next.events.events[index].logging_config = value; })} />
            <JsonObjectField key={`${selected.event_id}:llm`} label="LLM context" value={selected.llm_context} onChange={(value) => update((next) => { next.events.events[index].llm_context = value; })} />
          </div>
          <p className="rounded-lg border border-teal-200 bg-teal-50 p-3 text-sm text-teal-950">Stages and actions are data-only. Raw behavioral annotations remain in event actions; derived features are calculated later from the action timeline.</p>
          {selected.stages.map((stage, stageIndex) => (
            <article key={`${stage.stage_id}-${stageIndex}`} className="rounded-xl border border-stone-300 bg-stone-50 p-4">
              <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                <Field label="Stage ID"><TextInput value={stage.stage_id} onChange={(value) => update((next) => { next.events.events[index].stages![stageIndex].stage_id = value; })} /></Field>
                <LocalizedFields label="Stage title" value={stage.title} onChange={(locale, value) => update((next) => { next.events.events[index].stages![stageIndex].title[locale] = value; })} />
                <LocalizedFields label="Stage stimulus" value={stage.stimulus} multiline onChange={(locale, value) => update((next) => { next.events.events[index].stages![stageIndex].stimulus[locale] = value; })} />
              </div>
              <h4 className="mt-4 font-black">Stage actions</h4>
              <div className="mt-2 space-y-3">
                {stage.actions.map((action, actionIndex) => (
                  <div key={`${action.action_id}-${actionIndex}`} className="grid items-end gap-3 rounded-lg border border-stone-200 bg-white p-3 md:grid-cols-2 lg:grid-cols-4">
                    <Field label="Action ID"><TextInput value={action.action_id} onChange={(value) => update((next) => { next.events.events[index].stages![stageIndex].actions[actionIndex].action_id = value; })} /></Field>
                    <Field label="Raw action type"><TextInput value={action.action_type} onChange={(value) => update((next) => { next.events.events[index].stages![stageIndex].actions[actionIndex].action_type = value; })} /></Field>
                    <Field label="Outcome code"><TextInput value={action.outcome_code} onChange={(value) => update((next) => { next.events.events[index].stages![stageIndex].actions[actionIndex].outcome_code = value; })} /></Field>
                    <Field label="Minutes"><NumberInput value={action.action_minutes ?? 5} onChange={(value) => update((next) => { next.events.events[index].stages![stageIndex].actions[actionIndex].action_minutes = value; })} /></Field>
                    <LocalizedFields label="Label" value={action.label} onChange={(locale, value) => update((next) => { next.events.events[index].stages![stageIndex].actions[actionIndex].label[locale] = value; })} />
                    <Field label="Target type"><TextInput value={action.target_type ?? ""} onChange={(value) => update((next) => { const target = next.events.events[index].stages![stageIndex].actions[actionIndex]; if (value) target.target_type = value; else delete target.target_type; })} /></Field>
                    <Field label="Target ID"><TextInput value={action.target_id ?? ""} onChange={(value) => update((next) => { const target = next.events.events[index].stages![stageIndex].actions[actionIndex]; if (value) target.target_id = value; else delete target.target_id; })} /></Field>
                    {!action.terminal ? <Field label="Next stage"><SelectInput value={action.next_stage_id ?? behavioralStages[0].stage_id} options={behavioralStages.map((item) => item.stage_id)} onChange={(value) => update((next) => { next.events.events[index].stages![stageIndex].actions[actionIndex].next_stage_id = value; })} /></Field> : null}
                    <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={action.requires_text} onChange={(event) => update((next) => { next.events.events[index].stages![stageIndex].actions[actionIndex].requires_text = event.target.checked; })} />Requires text</label>
                    <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={action.terminal} onChange={(event) => update((next) => { const target = next.events.events[index].stages![stageIndex].actions[actionIndex]; target.terminal = event.target.checked; if (target.terminal) delete target.next_stage_id; else target.next_stage_id = next.events.events[index].initial_stage_id ?? next.events.events[index].stages![0].stage_id; })} />Ends event</label>
                    <button type="button" className={dangerButtonClass} onClick={() => update((next) => { next.events.events[index].stages![stageIndex].actions.splice(actionIndex, 1); })}>Remove action</button>
                    <details className="lg:col-span-4 rounded-lg border border-stone-200 bg-stone-50 p-3">
                      <summary className="cursor-pointer text-sm font-bold">Advanced data: logging, NPC response, goal effect</summary>
                      <div className="mt-3 grid gap-3 md:grid-cols-2">
                        <JsonObjectField label="Action metadata" value={action.metadata} onChange={(value) => update((next) => { next.events.events[index].stages![stageIndex].actions[actionIndex].metadata = value; })} />
                        <JsonObjectField label="State updates" value={action.state_updates} onChange={(value) => update((next) => { next.events.events[index].stages![stageIndex].actions[actionIndex].state_updates = value; })} />
                        <JsonObjectField label="NPC response" value={action.npc_response} onChange={(value) => update((next) => { const target = next.events.events[index].stages![stageIndex].actions[actionIndex]; if (Object.keys(value).length) target.npc_response = value; else delete target.npc_response; })} />
                        <JsonObjectField label="Goal effect" value={action.goal_effect} onChange={(value) => update((next) => { const target = next.events.events[index].stages![stageIndex].actions[actionIndex]; if (Object.keys(value).length) target.goal_effect = value; else delete target.goal_effect; })} />
                      </div>
                    </details>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" className={buttonClass} onClick={() => update((next) => addBehavioralStageAction(next, selected.event_id, stageIndex))}>Add stage action</button>
                <button type="button" className={dangerButtonClass} disabled={selected.stages!.length <= 1} onClick={() => update((next) => { next.events.events[index].stages!.splice(stageIndex, 1); })}>Remove stage</button>
              </div>
            </article>
          ))}
          <button type="button" className={buttonClass} onClick={() => update((next) => addBehavioralStage(next, selected.event_id))}>Add stage</button>
        </section>
      ) : (
        <section>
          <h3 className="mt-6 text-lg font-bold">Actions</h3>
          <div className="mt-3 space-y-3">
            {selected.actions.map((action, actionIndex) => (
              <div key={`${action.action_id}-${actionIndex}`} className="grid items-end gap-3 rounded-lg border border-stone-200 p-3 md:grid-cols-4">
                <Field label="Action ID"><TextInput value={action.action_id} onChange={(value) => update((next) => { next.events.events[index].actions[actionIndex].action_id = value; })} /></Field>
                <Field label="Outcome"><SelectInput value={action.outcome_key} options={["complete", "leave", "remember", "relationship_delta", "schedule_follow_up"]} onChange={(value) => update((next) => { next.events.events[index].actions[actionIndex].outcome_key = value; })} /></Field>
                <LocalizedFields label="Label" value={action.label} onChange={(locale, value) => update((next) => { next.events.events[index].actions[actionIndex].label[locale] = value; })} />
                <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={action.requires_text} onChange={(event) => update((next) => { next.events.events[index].actions[actionIndex].requires_text = event.target.checked; })} />Requires text</label>
                <button type="button" className={dangerButtonClass} onClick={() => update((next) => { next.events.events[index].actions.splice(actionIndex, 1); })}>Remove action</button>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className={buttonClass} onClick={() => update((next) => addEventAction(next, selected.event_id))}>Add action</button>
            <button type="button" className={buttonClass} onClick={() => update((next) => convertToBehavioralEvent(next, selected.event_id))}>Convert to staged event</button>
          </div>
        </section>
      )}
    </EditorSection>
  );
}

function SocialPropagationEditor({ draft, eventIndex, update }: EditorProps & { eventIndex: number }) {
  const event = draft.events.events[eventIndex];
  const publications = event.social_publications ?? [];
  return (
    <section className="mt-6 rounded-xl border border-violet-200 bg-violet-50/60 p-4" data-testid="studio-social-propagation">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-black text-violet-950">Social propagation</h3>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-violet-900">
            Turn selected event outcomes into grounded resident posts. Only witnesses can be authors; facts entered here are public and may be quoted. Never add private dialogue, research labels, diagnoses, or another character&apos;s private state.
          </p>
        </div>
        <button data-testid="studio-add-social-publication" type="button" className={primaryButtonClass} onClick={() => update((next) => addSocialPublication(next, eventIndex))}>Add publication rule</button>
      </div>
      {!publications.length ? (
        <div className="mt-4 rounded-lg border border-dashed border-violet-300 bg-white p-5 text-sm text-stone-700">
          This event does not publish to the island feed. The empty v0.7 template stays empty until you add a rule here.
        </div>
      ) : (
        <div className="mt-4 space-y-5">
          {publications.map((publication, publicationIndex) => (
            <SocialPublicationCard key={`${publication.publication_id}:${publicationIndex}`} draft={draft} eventIndex={eventIndex} publicationIndex={publicationIndex} publication={publication} update={update} />
          ))}
        </div>
      )}
    </section>
  );
}

function SocialPublicationCard({ draft, eventIndex, publicationIndex, publication, update }: EditorProps & { eventIndex: number; publicationIndex: number; publication: StudioSocialPublication }) {
  const [simulatedOutcome, setSimulatedOutcome] = useState(publication.trigger_outcomes[0] ?? "");
  const event = draft.events.events[eventIndex];
  const outcomes = Array.from(new Set([
    ...event.actions.map((action) => action.outcome_key),
    ...(event.stages ?? []).flatMap((stage) => stage.actions.map((action) => action.outcome_code)),
  ])).sort();
  const target = (next: StudioDraft) => next.events.events[eventIndex].social_publications![publicationIndex];
  const previewTemplate = publication.templates.find((item) => publication.eligible_author_ids.includes(item.author_agent_id));
  const previewAuthor = draft.residents.residents.find((item) => item.agent_id === previewTemplate?.author_agent_id);
  const facts = Object.entries(publication.facts);
  const simulatedAllowed = publication.trigger_outcomes.includes(simulatedOutcome);
  const eligibleNames = draft.residents.residents.filter((resident) => publication.eligible_author_ids.includes(resident.agent_id)).map((resident) => resident.name);
  return (
    <article className="rounded-xl border border-violet-300 bg-white p-4 shadow-sm" data-testid={`studio-social-publication-${publicationIndex}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.18em] text-violet-700">Event → fact → candidate → post</p>
          <h4 className="mt-1 font-black text-stone-950">{publication.publication_id || "Untitled publication rule"}</h4>
        </div>
        <button type="button" className={dangerButtonClass} onClick={() => update((next) => { next.events.events[eventIndex].social_publications!.splice(publicationIndex, 1); })}>Remove rule</button>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <Field label="Publication ID"><TextInput value={publication.publication_id} onChange={(value) => update((next) => { target(next).publication_id = value; })} /></Field>
        <Field label="Post type"><TextInput value={publication.post_type} onChange={(value) => update((next) => { target(next).post_type = value; })} /></Field>
        <Field label="Visibility"><SelectInput value={publication.visibility} options={["island_public", "participants_only"]} onChange={(value) => update((next) => { target(next).visibility = value as StudioSocialPublication["visibility"]; })} /></Field>
        <Field label="Expression"><SelectInput value={publication.generation_mode} options={["static_fallback", "llm_with_fallback"]} onChange={(value) => update((next) => { target(next).generation_mode = value as StudioSocialPublication["generation_mode"]; })} /></Field>
        <Field label="Maximum posts"><NumberInput value={publication.max_posts} onChange={(value) => update((next) => { target(next).max_posts = value; })} /></Field>
        <Field label="Cooldown minutes"><NumberInput value={publication.cooldown_minutes} onChange={(value) => update((next) => { target(next).cooldown_minutes = value; })} /></Field>
        <label className="flex items-center gap-2 self-end pb-2 text-sm font-bold"><input type="checkbox" checked={publication.allow_comments} onChange={(change) => update((next) => { target(next).allow_comments = change.target.checked; })} /> Allow ordinary comments</label>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <div>
          <h5 className="font-black">1 · Publishable outcomes</h5>
          <p className="mt-1 text-xs leading-5 text-stone-600">A completion post is impossible unless the event ends with a checked outcome.</p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {outcomes.map((outcome) => <label key={outcome} className="flex items-start gap-2 rounded-lg border border-stone-200 p-2 text-sm"><input type="checkbox" checked={publication.trigger_outcomes.includes(outcome)} onChange={(change) => update((next) => { const list = target(next).trigger_outcomes; target(next).trigger_outcomes = change.target.checked ? Array.from(new Set([...list, outcome])) : list.filter((item) => item !== outcome); })} /><code className="break-all">{outcome}</code></label>)}
          </div>
        </div>
        <div>
          <h5 className="font-black">2 · Knowledge and authorship</h5>
          <p className="mt-1 text-xs leading-5 text-stone-600">An author must also be a witness. Turning off witness access removes author eligibility.</p>
          <div className="mt-2 space-y-2">
            {draft.residents.residents.map((resident) => {
              const witness = publication.witness_agent_ids.includes(resident.agent_id);
              const author = publication.eligible_author_ids.includes(resident.agent_id);
              return <div key={resident.agent_id} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 rounded-lg border border-stone-200 px-3 py-2 text-sm"><span><strong>{resident.name}</strong> <span className="text-stone-500">#{resident.agent_id}</span></span><label className="flex items-center gap-1"><input type="checkbox" checked={witness} onChange={(change) => update((next) => setSocialWitness(target(next), resident, change.target.checked))} /> Witness</label><label className="flex items-center gap-1"><input type="checkbox" checked={author} disabled={!witness} onChange={(change) => update((next) => setSocialAuthor(target(next), resident, change.target.checked))} /> Author</label></div>;
            })}
          </div>
        </div>
      </div>

      <div className="mt-5">
        <div className="flex flex-wrap items-center justify-between gap-2"><div><h5 className="font-black">3 · Public fact envelope</h5><p className="mt-1 text-xs text-stone-600">The LLM may phrase only these fact IDs. Values are exported as authored strings.</p></div><button type="button" className={buttonClass} onClick={() => update((next) => { const rule = target(next); let number = Object.keys(rule.facts).length + 1; while (`fact_${number}` in rule.facts) number += 1; rule.facts[`fact_${number}`] = "public value"; })}>Add fact</button></div>
        <div className="mt-2 space-y-2">
          {facts.map(([factId, factValue], factIndex) => <div key={`${factId}:${factIndex}`} className="grid gap-2 rounded-lg border border-stone-200 p-2 md:grid-cols-[1fr_2fr_auto]"><TextInput value={factId} onChange={(value) => update((next) => renameSocialFact(target(next), factId, value))} /><TextInput value={Array.isArray(factValue) ? factValue.join(", ") : String(factValue)} onChange={(value) => update((next) => { target(next).facts[factId] = value; })} /><button type="button" className={dangerButtonClass} onClick={() => update((next) => { delete target(next).facts[factId]; })}>Remove</button></div>)}
        </div>
      </div>

      <div className="mt-5">
        <h5 className="font-black">4 · Safe fallback wording</h5>
        <p className="mt-1 text-xs text-stone-600">Every eligible author needs bilingual fallback text so model failure never blocks the world.</p>
        <div className="mt-2 space-y-3">
          {publication.eligible_author_ids.map((authorId) => {
            const resident = draft.residents.residents.find((item) => item.agent_id === authorId);
            const templateIndex = publication.templates.findIndex((item) => item.author_agent_id === authorId);
            const template = publication.templates[templateIndex];
            if (!resident || !template) return <p key={authorId} className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800">Missing fallback for resident #{authorId}. Toggle author eligibility off and on to repair it.</p>;
            return <div key={authorId} className="rounded-lg border border-stone-200 p-3"><p className="mb-2 font-bold">{resident.name}</p><LocalizedFields label="Post text" value={template.content} multiline onChange={(locale, value) => update((next) => { target(next).templates[templateIndex].content[locale] = value; })} /></div>;
          })}
        </div>
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-2">
        <div className="rounded-xl border border-sky-200 bg-sky-50 p-4">
          <h5 className="font-black text-sky-950">Rule simulator</h5>
          <div className="mt-3 grid gap-3 sm:grid-cols-2"><Field label="Observed outcome"><SelectInput value={simulatedOutcome} options={outcomes} onChange={setSimulatedOutcome} /></Field><div className="self-end rounded-lg bg-white p-3 text-sm"><strong>{simulatedAllowed ? `${eligibleNames.length} eligible author(s)` : "Blocked"}</strong><p className="mt-1 text-xs text-stone-600">{simulatedAllowed ? (eligibleNames.join(", ") || "No eligible witnesses") : "Reason: outcome is not publishable"}</p></div></div>
          <div className="mt-4 flex flex-wrap items-center gap-2 text-xs font-bold text-sky-950"><span className="rounded bg-white px-2 py-1">Event result</span><span>→</span><span className="rounded bg-white px-2 py-1">Public facts</span><span>→</span><span className="rounded bg-white px-2 py-1">Eligible witnesses</span><span>→</span><span className="rounded bg-white px-2 py-1">Agent decision / fallback</span><span>→</span><span className="rounded bg-white px-2 py-1">Phone post</span></div>
        </div>
        <div className="rounded-[1.5rem] border-[6px] border-stone-900 bg-stone-100 p-3 shadow-xl" aria-label="Phone post preview">
          <div className="rounded-xl bg-white p-4"><div className="flex items-center justify-between gap-2 text-xs text-stone-500"><span>Day 1 · 09:00</span><span>{publication.post_type}</span></div><p className="mt-3 font-black">{previewAuthor?.name ?? "Choose an eligible author"}</p><p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-stone-700">{previewTemplate?.content.en || "Add English fallback text to preview the final phone card."}</p><div className="mt-3 border-t border-stone-200 pt-2 text-xs text-stone-500">{event.location_ids[0] ?? "No location"} · source: {event.event_id} · {publication.allow_comments ? "comments allowed" : "read only"}</div></div>
        </div>
      </div>
    </article>
  );
}

function addSocialPublication(draft: StudioDraft, eventIndex: number) {
  const event = draft.events.events[eventIndex];
  const outcomes = Array.from(new Set([
    ...event.actions.map((action) => action.outcome_key),
    ...(event.stages ?? []).flatMap((stage) => stage.actions.map((action) => action.outcome_code)),
  ]));
  const firstResident = draft.residents.residents[0];
  const publication: StudioSocialPublication = {
    publication_id: `${event.event_id}_publication_${(event.social_publications?.length ?? 0) + 1}`,
    trigger_outcomes: outcomes.slice(0, 1),
    eligible_author_ids: firstResident ? [firstResident.agent_id] : [],
    witness_agent_ids: firstResident ? [firstResident.agent_id] : [],
    visibility: "island_public",
    post_type: "activity",
    max_posts: 1,
    cooldown_minutes: 1440,
    allow_comments: true,
    generation_mode: "static_fallback",
    facts: { event_id: event.event_id, location_id: event.location_ids[0] ?? "" },
    templates: firstResident ? [{ author_agent_id: firstResident.agent_id, content: { en: "A public update about what happened.", "zh-CN": "一条关于已发生事件的公开动态。" } }] : [],
  };
  event.social_publications ??= [];
  event.social_publications.push(publication);
}

function setSocialWitness(publication: StudioSocialPublication, resident: StudioResident, enabled: boolean) {
  publication.witness_agent_ids = enabled ? Array.from(new Set([...publication.witness_agent_ids, resident.agent_id])) : publication.witness_agent_ids.filter((id) => id !== resident.agent_id);
  if (!enabled) setSocialAuthor(publication, resident, false);
}

function setSocialAuthor(publication: StudioSocialPublication, resident: StudioResident, enabled: boolean) {
  publication.eligible_author_ids = enabled ? Array.from(new Set([...publication.eligible_author_ids, resident.agent_id])) : publication.eligible_author_ids.filter((id) => id !== resident.agent_id);
  if (enabled) {
    publication.witness_agent_ids = Array.from(new Set([...publication.witness_agent_ids, resident.agent_id]));
    if (!publication.templates.some((item) => item.author_agent_id === resident.agent_id)) publication.templates.push({ author_agent_id: resident.agent_id, content: { en: `${resident.name} shares a public update.`, "zh-CN": `${resident.name} 分享了一条公开动态。` } });
  } else publication.templates = publication.templates.filter((item) => item.author_agent_id !== resident.agent_id);
}

function renameSocialFact(publication: StudioSocialPublication, previous: string, next: string) {
  const clean = next.trim();
  if (!clean || clean === previous || clean in publication.facts) return;
  const entries = Object.entries(publication.facts).map(([key, value]) => key === previous ? [clean, value] : [key, value]);
  publication.facts = Object.fromEntries(entries);
}

function TriggerConditionBuilder({ draft, eventIndex, update }: EditorProps & { eventIndex: number }) {
  const event = draft.events.events[eventIndex];
  const conditions = event.trigger.conditions ?? { mode: "all" as const, items: [] };
  return (
    <section data-testid="studio-trigger-builder" className="mt-6 rounded-xl border border-indigo-200 bg-indigo-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-black text-indigo-950">Trigger conditions</h3>
          <p className="text-sm text-indigo-800">All/any rules decide whether the event starts. Flow branches are edited separately below.</p>
        </div>
        <Field label="Match"><SelectInput value={conditions.mode} options={["all", "any"]} onChange={(value) => update((next) => { next.events.events[eventIndex].trigger.conditions = { ...conditions, mode: value as "all" | "any" }; })} /></Field>
      </div>
      <div className="mt-3 space-y-2">
        {conditions.items.map((condition, conditionIndex) => (
          <div key={`${condition.type}-${conditionIndex}`} data-testid="studio-trigger-condition" className="grid items-end gap-2 rounded-lg bg-white p-3 md:grid-cols-4">
            <Field label="Condition"><SelectInput value={condition.type} options={["world_day", "world_time", "location", "action_type", "object_choice", "resident_present", "flag", "goal_status", "event_status"]} onChange={(value) => update((next) => { const target = next.events.events[eventIndex].trigger.conditions!.items[conditionIndex]; target.type = value as StudioTriggerCondition["type"]; target.operator = conditionOperators(target.type)[0] as StudioTriggerCondition["operator"]; target.value = defaultConditionValue(target.type, next); })} /></Field>
            <Field label="Operator"><SelectInput value={condition.operator} options={conditionOperators(condition.type)} onChange={(value) => update((next) => { next.events.events[eventIndex].trigger.conditions!.items[conditionIndex].operator = value as StudioTriggerCondition["operator"]; })} /></Field>
            <ConditionValueInput draft={draft} condition={condition} onChange={(value) => update((next) => { next.events.events[eventIndex].trigger.conditions!.items[conditionIndex].value = value; })} />
            <button type="button" className={dangerButtonClass} onClick={() => update((next) => { next.events.events[eventIndex].trigger.conditions!.items.splice(conditionIndex, 1); })}>Remove condition</button>
          </div>
        ))}
      </div>
      <button data-testid="studio-add-trigger-condition" type="button" className={`${buttonClass} mt-3`} onClick={() => update((next) => { const target = next.events.events[eventIndex].trigger; target.conditions ??= { mode: "all", items: [] }; target.conditions.items.push({ type: "world_day", operator: "at_least", value: 1 }); })}>Add condition</button>
    </section>
  );
}

function ConditionValueInput({ draft, condition, onChange }: { draft: StudioDraft; condition: StudioTriggerCondition; onChange: (value: string | number) => void }) {
  if (condition.type === "location") return <Field label="Value"><SelectInput value={String(condition.value)} options={draft.locations.locations.map((item) => item.location_id)} onChange={onChange} /></Field>;
  if (condition.type === "resident_present") return <Field label="Value"><SelectInput value={String(condition.value)} options={draft.residents.residents.map((item) => String(item.agent_id))} onChange={(value) => onChange(Number(value))} /></Field>;
  if (condition.type === "world_day" || condition.type === "world_time") return <Field label="Value"><NumberInput value={Number(condition.value)} onChange={onChange} /></Field>;
  if (condition.type === "action_type") return <Field label="Value"><SelectInput value={String(condition.value)} options={["move", "observe", "wait", "end_day", "event_action"]} onChange={onChange} /></Field>;
  return <Field label="Value"><TextInput value={String(condition.value)} onChange={onChange} /></Field>;
}

function FlowEditor({ draft, eventIndex, update }: EditorProps & { eventIndex: number }) {
  const event = draft.events.events[eventIndex];
  const nodes = event.stages ?? [];
  const [selectedNodeId, setSelectedNodeId] = useState(event.initial_stage_id ?? nodes[0]?.stage_id ?? "");
  const selectedNode = nodes.find((node) => node.stage_id === selectedNodeId) ?? nodes[0];
  const nodeIndex = nodes.findIndex((node) => node.stage_id === selectedNode?.stage_id);
  const problems = flowProblems(event);
  if (!selectedNode) return null;
  return (
    <section data-testid="studio-flow-editor" className="mt-6 space-y-4">
      <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)_300px]">
        <aside className="rounded-xl border border-stone-200 bg-stone-50 p-3">
          <h3 className="font-black">Flow nodes</h3>
          <div className="mt-2 space-y-2">
            {nodes.map((node) => (
              <button key={node.stage_id} type="button" data-testid={`flow-node-${node.stage_id}`} onClick={() => setSelectedNodeId(node.stage_id)} className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${node.stage_id === selectedNode.stage_id ? "border-teal-700 bg-teal-700 text-white" : "border-stone-300 bg-white"}`}>
                <span className="block font-bold">{node.title.en}</span><code className="text-xs opacity-80">{node.stage_id}</code>
              </button>
            ))}
          </div>
          <button data-testid="studio-add-flow-node" type="button" className={`${buttonClass} mt-3 w-full`} onClick={() => update((next) => addBehavioralStage(next, event.event_id))}>Add node</button>
        </aside>

        <div className="rounded-xl border border-stone-300 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-lg font-black">Edit node</h3>
            <div className="flex gap-2">
              <button type="button" className={buttonClass} onClick={() => update((next) => duplicateFlowNode(next, eventIndex, nodeIndex))}>Duplicate node</button>
              <button type="button" className={dangerButtonClass} disabled={nodes.length <= 1 || isFlowNodeReferenced(event, selectedNode.stage_id)} title={isFlowNodeReferenced(event, selectedNode.stage_id) ? "Redirect incoming choices before deleting this node." : undefined} onClick={() => update((next) => { next.events.events[eventIndex].stages!.splice(nodeIndex, 1); })}>Delete node</button>
            </div>
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <Field label="Node ID"><TextInput testId="studio-flow-node-id" value={selectedNode.stage_id} onChange={(value) => { const oldId = selectedNode.stage_id; setSelectedNodeId(value); update((next) => renameFlowNode(next.events.events[eventIndex], oldId, value)); }} /></Field>
            <Field label="Initial node"><SelectInput value={event.initial_stage_id ?? nodes[0].stage_id} options={nodes.map((node) => node.stage_id)} onChange={(value) => update((next) => { next.events.events[eventIndex].initial_stage_id = value; })} /></Field>
            <LocalizedFields label="Node title" value={selectedNode.title} onChange={(locale, value) => update((next) => { next.events.events[eventIndex].stages![nodeIndex].title[locale] = value; })} />
            <LocalizedFields label="Narrative text" value={selectedNode.stimulus} multiline onChange={(locale, value) => update((next) => { next.events.events[eventIndex].stages![nodeIndex].stimulus[locale] = value; })} />
          </div>
          <h4 className="mt-5 font-black">Choices and consequences</h4>
          <div className="mt-2 space-y-3">
            {selectedNode.actions.map((choice, choiceIndex) => (
              <article key={`${choice.action_id}-${choiceIndex}`} data-testid="studio-flow-choice" className="rounded-xl border border-stone-200 bg-stone-50 p-3">
                <div className="grid gap-3 md:grid-cols-2">
                  <Field label="Choice ID"><TextInput value={choice.action_id} onChange={(value) => update((next) => { next.events.events[eventIndex].stages![nodeIndex].actions[choiceIndex].action_id = value; })} /></Field>
                  <LocalizedFields label="Choice label" value={choice.label} onChange={(locale, value) => update((next) => { next.events.events[eventIndex].stages![nodeIndex].actions[choiceIndex].label[locale] = value; })} />
                  <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={choice.requires_text} onChange={(change) => update((next) => { next.events.events[eventIndex].stages![nodeIndex].actions[choiceIndex].requires_text = change.target.checked; })} />Require free text</label>
                </div>
                <div className="mt-3 space-y-2">
                  {(choice.effects ?? []).map((effect, effectIndex) => <FlowEffectEditor key={`${effect.type}-${effectIndex}`} draft={draft} eventIndex={eventIndex} nodeIndex={nodeIndex} choiceIndex={choiceIndex} effectIndex={effectIndex} effect={effect} update={update} />)}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button data-testid="studio-add-flow-effect" type="button" className={buttonClass} onClick={() => update((next) => { next.events.events[eventIndex].stages![nodeIndex].actions[choiceIndex].effects ??= []; next.events.events[eventIndex].stages![nodeIndex].actions[choiceIndex].effects!.push({ type: "show_message", text: { en: "New message", "zh-CN": "新消息" } }); })}>Add consequence</button>
                  <button type="button" className={buttonClass} onClick={() => update((next) => duplicateFlowChoice(next, eventIndex, nodeIndex, choiceIndex))}>Duplicate choice</button>
                  <button type="button" className={dangerButtonClass} disabled={selectedNode.actions.length <= 1} onClick={() => update((next) => { next.events.events[eventIndex].stages![nodeIndex].actions.splice(choiceIndex, 1); })}>Delete choice</button>
                </div>
              </article>
            ))}
          </div>
          <button data-testid="studio-add-flow-choice" type="button" className={`${buttonClass} mt-3`} onClick={() => update((next) => addBehavioralStageAction(next, event.event_id, nodeIndex))}>Add choice</button>
        </div>

        <aside className="space-y-3">
          <div data-testid="studio-flow-graph" className="rounded-xl border border-stone-200 bg-stone-50 p-3" aria-label="Flow branch graph">
            <h3 className="font-black">Branch map</h3>
            <div className="mt-2 space-y-2">
              {nodes.map((node) => <button key={node.stage_id} type="button" onClick={() => setSelectedNodeId(node.stage_id)} className="block w-full rounded-lg border border-stone-300 bg-white p-2 text-left text-xs"><strong>{node.stage_id}</strong><span className="mt-1 block text-stone-600">{flowTargets(node).length ? `→ ${flowTargets(node).join(", ")}` : "→ end"}</span></button>)}
            </div>
          </div>
          <div data-testid="studio-flow-problems" className={`rounded-xl border p-3 ${problems.length ? "border-amber-300 bg-amber-50" : "border-emerald-300 bg-emerald-50"}`}>
            <h3 className="font-black">Flow check</h3>
            {problems.length ? <ul className="mt-2 list-disc pl-5 text-sm">{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul> : <p className="mt-2 text-sm">All nodes are reachable and every choice has one control consequence.</p>}
          </div>
        </aside>
      </div>
    </section>
  );
}

function FlowEffectEditor({ draft, eventIndex, nodeIndex, choiceIndex, effectIndex, effect, update }: EditorProps & { eventIndex: number; nodeIndex: number; choiceIndex: number; effectIndex: number; effect: StudioFlowEffect }) {
  const setEffect = (mutator: (effect: StudioFlowEffect) => void) => update((next) => {
    const choice = next.events.events[eventIndex].stages![nodeIndex].actions[choiceIndex];
    mutator(choice.effects![effectIndex]);
    syncFlowChoice(choice);
  });
  return (
    <div data-testid="studio-flow-effect" className="grid items-end gap-2 rounded-lg border border-indigo-200 bg-white p-3 sm:grid-cols-2">
      <Field label="Consequence"><SelectInput testId="studio-flow-effect-type" value={effect.type} options={["advance_time", "goto_node", "complete_flow", "start_event", "schedule_event", "set_flag", "goal_update", "relationship_delta", "add_memory", "move_participant", "show_message"]} onChange={(value) => update((next) => replaceFlowEffect(next, eventIndex, nodeIndex, choiceIndex, effectIndex, value as StudioFlowEffect["type"]))} /></Field>
      {effect.type === "advance_time" ? <Field label="Minutes"><NumberInput value={effect.minutes} onChange={(value) => setEffect((target) => { if (target.type === "advance_time") target.minutes = value; })} /></Field> : null}
      {effect.type === "goto_node" ? <Field label="Next node"><SelectInput value={effect.node_id} options={draft.events.events[eventIndex].stages!.map((node) => node.stage_id)} onChange={(value) => setEffect((target) => { if (target.type === "goto_node") target.node_id = value; })} /></Field> : null}
      {effect.type === "complete_flow" ? <Field label="Outcome code"><TextInput value={effect.outcome_code} onChange={(value) => setEffect((target) => { if (target.type === "complete_flow") target.outcome_code = value; })} /></Field> : null}
      {effect.type === "start_event" || effect.type === "schedule_event" ? <Field label="Event"><SelectInput value={effect.event_id} options={draft.events.events.filter((_, index) => index !== eventIndex).map((item) => item.event_id)} onChange={(value) => setEffect((target) => { if (target.type === "start_event" || target.type === "schedule_event") target.event_id = value; })} /></Field> : null}
      {effect.type === "schedule_event" ? <Field label="Delay minutes"><NumberInput value={effect.delay_minutes} onChange={(value) => setEffect((target) => { if (target.type === "schedule_event") target.delay_minutes = value; })} /></Field> : null}
      {effect.type === "set_flag" ? <><Field label="Flag ID"><TextInput value={effect.flag_id} onChange={(value) => setEffect((target) => { if (target.type === "set_flag") target.flag_id = value; })} /></Field><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={effect.value} onChange={(change) => setEffect((target) => { if (target.type === "set_flag") target.value = change.target.checked; })} />True</label></> : null}
      {effect.type === "goal_update" ? <><Field label="Goal ID"><TextInput value={effect.goal.goal_id} onChange={(value) => setEffect((target) => { if (target.type === "goal_update") target.goal.goal_id = value; })} /></Field><Field label="Status"><TextInput value={effect.goal.status} onChange={(value) => setEffect((target) => { if (target.type === "goal_update") target.goal.status = value; })} /></Field><LocalizedOptionalFields label="Goal title" value={effect.goal.title} onChange={(value) => setEffect((target) => { if (target.type === "goal_update") target.goal.title = value; })} /><LocalizedOptionalFields label="Goal description" value={effect.goal.description} multiline onChange={(value) => setEffect((target) => { if (target.type === "goal_update") target.goal.description = value; })} /><Field label="Target place"><SelectInput value={effect.goal.target_location_id ?? ""} includeBlank options={draft.locations.locations.map((item) => item.location_id)} onChange={(value) => setEffect((target) => { if (target.type === "goal_update") { if (value) target.goal.target_location_id = value; else delete target.goal.target_location_id; } })} /></Field><Field label="Resolution"><TextInput value={effect.goal.resolution ?? ""} onChange={(value) => setEffect((target) => { if (target.type === "goal_update") { if (value) target.goal.resolution = value; else delete target.goal.resolution; } })} /></Field></> : null}
      {effect.type === "relationship_delta" ? <><Field label="Resident"><SelectInput value={String(effect.target_agent_id)} options={draft.residents.residents.map((item) => String(item.agent_id))} onChange={(value) => setEffect((target) => { if (target.type === "relationship_delta") target.target_agent_id = Number(value); })} /></Field>{(["familiarity_delta", "trust_delta", "warmth_delta", "tension_delta"] as const).map((key) => <Field key={key} label={key.replace("_delta", " delta")}><NumberInput value={effect[key] ?? 0} onChange={(value) => setEffect((target) => { if (target.type === "relationship_delta") target[key] = value; })} /></Field>)}</> : null}
      {effect.type === "add_memory" ? <><Field label="Resident"><SelectInput value={String(effect.owner_agent_id)} options={draft.residents.residents.map((item) => String(item.agent_id))} onChange={(value) => setEffect((target) => { if (target.type === "add_memory") target.owner_agent_id = Number(value); })} /></Field><LocalizedFields label="Memory" value={effect.text} onChange={(locale, value) => setEffect((target) => { if (target.type === "add_memory") target.text[locale] = value; })} /><Field label="Tags"><TextInput value={effect.tags?.join(", ") ?? ""} onChange={(value) => setEffect((target) => { if (target.type === "add_memory") target.tags = csv(value); })} /></Field></> : null}
      {effect.type === "move_participant" ? <Field label="Destination"><SelectInput value={effect.location_id} options={draft.locations.locations.map((item) => item.location_id)} onChange={(value) => setEffect((target) => { if (target.type === "move_participant") target.location_id = value; })} /></Field> : null}
      {effect.type === "show_message" ? <LocalizedFields label="Message" value={effect.text} onChange={(locale, value) => setEffect((target) => { if (target.type === "show_message") target.text[locale] = value; })} /> : null}
      <button type="button" className={dangerButtonClass} onClick={() => update((next) => { next.events.events[eventIndex].stages![nodeIndex].actions[choiceIndex].effects!.splice(effectIndex, 1); syncFlowChoice(next.events.events[eventIndex].stages![nodeIndex].actions[choiceIndex]); })}>Remove consequence</button>
    </div>
  );
}

function SystemsEditor({ draft, update }: EditorProps) {
  const [simulationActionId, setSimulationActionId] = useState("");
  const [simulationLocationId, setSimulationLocationId] = useState("");
  const [simulationParticipantCount, setSimulationParticipantCount] = useState(2);
  const systems = draft.systems;
  if (!systems) return <EditorSection title="Actions and activities" description="Available in content-pack-v4."><p>This draft has no systems.json.</p></EditorSection>;
  const simulatedAction = simulationActionId || systems.action_definitions[0]?.action_id || "";
  const simulatedLocation = simulationLocationId || draft.locations.locations[0]?.location_id || "";
  const simulatedCandidates = simulateActivityCandidates(systems, simulatedAction, simulatedLocation, simulationParticipantCount);
  return (
    <EditorSection title="Actions, affordances, and activities" description="Work top to bottom: define verbs, expose them at places or objects, then combine them into cooperative activities.">
      <SystemGroup title="1 · Action dictionary" description="Actor, target, duration and consequence contract." addLabel="Add action" testId="studio-add-action-definition" onAdd={() => update(addSystemAction)}>
        {systems.action_definitions.map((item, index) => <div key={`${item.action_id}:${index}`} className="grid gap-3 rounded-lg border border-stone-200 p-3 md:grid-cols-3"><Field label="Action ID"><TextInput value={item.action_id} onChange={(value) => update((next) => { next.systems!.action_definitions[index].action_id = value; })} /></Field><LocalizedFields label="Label" value={item.label} onChange={(locale, value) => update((next) => { next.systems!.action_definitions[index].label[locale] = value; })} /><Field label="Actors"><TextInput value={item.actor_types.join(", ")} onChange={(value) => update((next) => { next.systems!.action_definitions[index].actor_types = csv(value); })} /></Field><Field label="Targets"><TextInput value={item.target_types.join(", ")} onChange={(value) => update((next) => { next.systems!.action_definitions[index].target_types = csv(value); })} /></Field><Field label="Minutes"><NumberInput value={item.duration_minutes} onChange={(value) => update((next) => { next.systems!.action_definitions[index].duration_minutes = value; })} /></Field><p className="self-end pb-2 text-xs text-stone-600">{item.consequences.length} authored consequences</p><button type="button" className={dangerButtonClass} onClick={() => update((next) => removeSystemAction(next, index))}>Remove</button></div>)}
      </SystemGroup>
      <SystemGroup title="2 · Place/object affordances" description="Only enabled matching affordances become legal runtime actions." addLabel="Add affordance" testId="studio-add-affordance" disabled={!systems.action_definitions.length} onAdd={() => update(addSystemAffordance)}>
        {systems.affordances.map((item, index) => <div key={`${item.affordance_id}:${index}`} className="grid gap-3 rounded-lg border border-stone-200 p-3 md:grid-cols-3"><Field label="Affordance ID"><TextInput value={item.affordance_id} onChange={(value) => update((next) => { next.systems!.affordances[index].affordance_id = value; })} /></Field><Field label="Action"><SelectInput value={item.action_id} options={systems.action_definitions.map((action) => action.action_id)} onChange={(value) => update((next) => { next.systems!.affordances[index].action_id = value; })} /></Field><label className="flex items-center gap-2 text-sm font-bold"><input type="checkbox" checked={item.enabled} onChange={(event) => update((next) => { next.systems!.affordances[index].enabled = event.target.checked; })} /> Enabled</label><Field label="Location IDs"><TextInput value={item.location_ids.join(", ")} onChange={(value) => update((next) => { next.systems!.affordances[index].location_ids = csv(value); })} /></Field><Field label="Object IDs"><TextInput value={item.object_ids.join(", ")} onChange={(value) => update((next) => { next.systems!.affordances[index].object_ids = csv(value); })} /></Field><button type="button" className={dangerButtonClass} onClick={() => update((next) => { next.systems!.affordances.splice(index, 1); })}>Remove</button></div>)}
      </SystemGroup>
      <SystemGroup title="3 · Cooperative activities" description="Participant limits make activities such as games or meals available only with enough people." addLabel="Add activity" testId="studio-add-activity-recipe" disabled={!systems.action_definitions.length || !draft.locations.locations.length} onAdd={() => update(addActivityRecipe)}>
        {systems.activity_recipes.map((item, index) => <div key={`${item.recipe_id}:${index}`} className="grid gap-3 rounded-lg border border-stone-200 p-3 md:grid-cols-3"><Field label="Recipe ID"><TextInput value={item.recipe_id} onChange={(value) => update((next) => { next.systems!.activity_recipes[index].recipe_id = value; })} /></Field><LocalizedFields label="Label" value={item.label} onChange={(locale, value) => update((next) => { next.systems!.activity_recipes[index].label[locale] = value; })} /><Field label="Location IDs"><TextInput value={item.location_ids.join(", ")} onChange={(value) => update((next) => { next.systems!.activity_recipes[index].location_ids = csv(value); })} /></Field><Field label="Action IDs"><TextInput value={item.action_ids.join(", ")} onChange={(value) => update((next) => { next.systems!.activity_recipes[index].action_ids = csv(value); })} /></Field><Field label="Minimum people"><NumberInput value={item.min_participants} onChange={(value) => update((next) => { next.systems!.activity_recipes[index].min_participants = value; })} /></Field><Field label="Maximum people"><NumberInput value={item.max_participants} onChange={(value) => update((next) => { next.systems!.activity_recipes[index].max_participants = value; })} /></Field><Field label="Minutes"><NumberInput value={item.duration_minutes} onChange={(value) => update((next) => { next.systems!.activity_recipes[index].duration_minutes = value; })} /></Field><button type="button" className={dangerButtonClass} onClick={() => update((next) => { next.systems!.activity_recipes.splice(index, 1); })}>Remove</button></div>)}
      </SystemGroup>
      <section className="rounded-xl border border-violet-200 bg-violet-50 p-4">
        <h3 className="font-black text-violet-950">4 · Bounded emergence policy</h3>
        <p className="text-xs text-violet-800">Hard limits are deterministic. Candidate selections and rejection reasons are retained in the audit trail.</p>
        <div className="mt-3 grid gap-3 md:grid-cols-3"><Field label="Policy ID"><TextInput value={String(systems.emergence_policy.policy_id ?? "")} onChange={(value) => update((next) => { next.systems!.emergence_policy.policy_id = value; })} /></Field><Field label="Policy version"><TextInput value={String(systems.emergence_policy.policy_version ?? "")} onChange={(value) => update((next) => { next.systems!.emergence_policy.policy_version = value; })} /></Field>{(["max_agent_actions_per_tick", "max_invitations_per_tick", "max_activity_creations_per_tick", "max_event_chain_depth"] as const).map((key) => <Field key={key} label={key.replaceAll("_", " ")}><NumberInput value={Number(systems.emergence_policy[key] ?? 0)} onChange={(value) => update((next) => { next.systems!.emergence_policy[key] = value; })} /></Field>)}</div>
      </section>
      <section data-testid="studio-emergence-simulator" className="mt-5 rounded-xl border border-sky-200 bg-sky-50 p-4">
        <h3 className="font-black text-sky-950">Rule graph and dry-run simulator</h3>
        <p className="text-xs text-sky-800">This preview does not write sessions. It uses the same recipe ordering, participant gate and creation limit as runtime.</p>
        <div className="mt-3 grid gap-3 md:grid-cols-3"><Field label="Action"><SelectInput value={simulatedAction} options={systems.action_definitions.map((item) => item.action_id)} onChange={setSimulationActionId} /></Field><Field label="Location"><SelectInput value={simulatedLocation} options={draft.locations.locations.map((item) => item.location_id)} onChange={setSimulationLocationId} /></Field><Field label="People present"><NumberInput value={simulationParticipantCount} onChange={setSimulationParticipantCount} /></Field></div>
        <div className="mt-4 grid gap-2 md:grid-cols-[1fr_auto_1fr_auto_1fr] md:items-center"><div className="rounded-lg border border-sky-200 bg-white p-3 text-center text-sm font-bold">Verb<br/><code>{simulatedAction || "—"}</code></div><span className="text-center text-sky-700">→</span><div className="rounded-lg border border-sky-200 bg-white p-3 text-center text-sm font-bold">Matching affordances<br/><span>{systems.affordances.filter((item) => item.enabled && item.action_id === simulatedAction && (!item.location_ids.length || item.location_ids.includes(simulatedLocation))).length}</span></div><span className="text-center text-sky-700">→</span><div className="rounded-lg border border-sky-200 bg-white p-3 text-center text-sm font-bold">Activity candidates<br/><span>{simulatedCandidates.length}</span></div></div>
        <div className="mt-3 space-y-2">{simulatedCandidates.map(({ item, outcome, reason }) => <div key={item.recipe_id} className={`flex flex-wrap items-center justify-between gap-2 rounded-md border bg-white p-3 text-sm ${outcome === "selected" ? "border-emerald-300" : "border-amber-300"}`}><code>{item.recipe_id}</code><span className="font-bold">{outcome}</span><span className="text-xs text-stone-600">{reason}</span></div>)}{!simulatedCandidates.length ? <p className="rounded-md border border-dashed border-sky-300 p-3 text-sm text-sky-900">No recipe matches this verb and location.</p> : null}</div>
      </section>
    </EditorSection>
  );
}

function SystemGroup({ title, description, addLabel, testId, disabled = false, onAdd, children }: { title: string; description: string; addLabel: string; testId: string; disabled?: boolean; onAdd: () => void; children: ReactNode }) {
  return <section className="mb-5 rounded-xl border border-stone-200 p-4"><div className="flex items-center justify-between gap-3"><div><h3 className="font-black">{title}</h3><p className="text-xs text-stone-600">{description}</p></div><button data-testid={testId} type="button" disabled={disabled} className={buttonClass} onClick={onAdd}>{addLabel}</button></div><div className="mt-3 space-y-3">{children}</div></section>;
}

function ArtEditor({
  draft,
  update,
  assetFiles,
  setAssetFiles,
  assetErrors,
  setAssetErrors,
  language,
  selectedLocation,
  selectLocation,
}: EditorProps & {
  assetFiles: Record<string, LocalAssetFile>;
  setAssetFiles: React.Dispatch<React.SetStateAction<Record<string, LocalAssetFile>>>;
  assetErrors: Record<string, string>;
  setAssetErrors: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  language: Language;
  selectedLocation?: StudioLocation;
  selectLocation: (id: string) => void;
}) {
  if (!draft.visuals || !["content-pack-v2", "content-pack-v3", "content-pack-v4", "content-pack-v5"].includes(draft.manifest.schema_version)) {
    return (
      <EditorSection title="Art assets" description="Art slots use the content-pack-v2/v3 visual contract.">
        <p className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-950">
          Load a v2/v3 pack before adding images. Existing v1 JSON validation and export remain unchanged.
        </p>
      </EditorSection>
    );
  }
  const visuals = draft.visuals;
  const groups: Array<{ label: string; types: StudioVisualSlot["slot_type"][] }> = [
    { label: "Map", types: ["map_image"] },
    { label: "Character map thumbnails", types: ["actor_map_thumbnail"] },
    { label: "Location map thumbnails", types: ["location_map_thumbnail"] },
    { label: "Dialogue portraits", types: ["actor_dialogue_portrait"] },
    { label: "Location scene images", types: ["location_scene_image"] },
  ];

  async function upload(slot: StudioVisualSlot, file: File) {
    const mime = file.type as StudioVisualAsset["mime_type"];
    const extension = file.name.split(".").at(-1)?.toLowerCase() ?? "";
    const validExtension = mime === "image/jpeg"
      ? ["jpg", "jpeg"].includes(extension)
      : (mime === "image/png" && extension === "png") || (mime === "image/webp" && extension === "webp");
    if (!["image/png", "image/jpeg", "image/webp"].includes(mime) || !validExtension) {
      throw new Error("Choose a PNG, JPEG, or WebP whose extension matches its browser MIME type.");
    }
    if (file.size > 4_000_000) throw new Error("Each image must be no larger than 4 MB.");
    let bitmap: ImageBitmap;
    try {
      bitmap = await createImageBitmap(file);
    } catch {
      throw new Error("The browser could not decode this image.");
    }
    const width = bitmap.width;
    const height = bitmap.height;
    bitmap.close();
    if (width < 1 || height < 1 || width > 4096 || height > 4096 || width * height > 16_000_000) {
      throw new Error("Image dimensions must stay within 4096 x 4096 and 16 million pixels.");
    }
    const sha256 = await sha256Hex(file);
    const safeTarget = slot.target_id.replace(/[^A-Za-z0-9._-]+/g, "-").slice(0, 48);
    const assetKey = `visual-${slot.slot_type}-${safeTarget}-${sha256.slice(0, 16)}`.slice(0, 128);
    const suffix = mime === "image/jpeg" ? (extension === "jpeg" ? "jpeg" : "jpg") : extension;
    const oldKey = slot.asset_key;
    const oldWillBeOrphan = Boolean(oldKey && visuals.visual_slots.filter((item) => item.asset_key === oldKey).length === 1);
    const previewUrl = URL.createObjectURL(file);
    update((next) => {
      const nextVisuals = next.visuals!;
      if (!nextVisuals.visual_assets.some((item) => item.asset_key === assetKey)) {
        nextVisuals.visual_assets.push({
          asset_key: assetKey,
          file_name: `assets/${assetKey}.${suffix}`,
          mime_type: mime,
          width,
          height,
          sha256,
          source: "studio-upload",
          license: "user-provided",
        });
      }
      nextVisuals.visual_slots.find((item) => item.slot_id === slot.slot_id)!.asset_key = assetKey;
      if (oldKey && oldWillBeOrphan && oldKey !== assetKey) {
        nextVisuals.visual_assets = nextVisuals.visual_assets.filter((item) => item.asset_key !== oldKey);
      }
    });
    setAssetFiles((current) => {
      const next = { ...current };
      if (next[assetKey]) URL.revokeObjectURL(next[assetKey].previewUrl);
      next[assetKey] = { blob: file, previewUrl };
      if (oldKey && oldWillBeOrphan && oldKey !== assetKey && next[oldKey]) {
        URL.revokeObjectURL(next[oldKey].previewUrl);
        delete next[oldKey];
      }
      return next;
    });
    setAssetErrors((current) => {
      const next = { ...current };
      delete next[slot.slot_id];
      return next;
    });
  }

  function clearSlot(slot: StudioVisualSlot) {
    const oldKey = slot.asset_key;
    if (!oldKey) return;
    const oldWillBeOrphan = visuals.visual_slots.filter((item) => item.asset_key === oldKey).length === 1;
    update((next) => {
      const nextVisuals = next.visuals!;
      nextVisuals.visual_slots.find((item) => item.slot_id === slot.slot_id)!.asset_key = null;
      if (oldWillBeOrphan) nextVisuals.visual_assets = nextVisuals.visual_assets.filter((item) => item.asset_key !== oldKey);
    });
    if (oldWillBeOrphan) {
      setAssetFiles((current) => {
        const next = { ...current };
        if (next[oldKey]) URL.revokeObjectURL(next[oldKey].previewUrl);
        delete next[oldKey];
        return next;
      });
    }
  }

  const rendererVisuals = studioWorldVisuals(draft, assetFiles);
  const previewLocation = selectedLocation ?? draft.locations.locations[0];
  const previewLayout = draft.map.scene_layouts.find((item) => item.location_id === previewLocation?.location_id);
  return (
    <EditorSection title="Art assets" description="Every required slot can intentionally stay empty. Uploads are local browser Blobs until a validated ZIP is exported.">
      <div className="space-y-7">
        {groups.map((group) => (
          <section key={group.label}>
            <h3 className="mb-3 text-lg font-black">{group.label}</h3>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {visuals.visual_slots.filter((slot) => group.types.includes(slot.slot_type)).map((slot) => {
                const asset = visuals.visual_assets.find((item) => item.asset_key === slot.asset_key);
                const rawPreviewUrl = asset ? assetFiles[asset.asset_key]?.previewUrl ?? draft.asset_urls?.[asset.asset_key] : undefined;
                const previewUrl = rawPreviewUrl ? resolveApiAssetUrl(rawPreviewUrl) : undefined;
                return (
                  <article key={slot.slot_id} data-testid={`visual-slot-${slot.slot_id}`} className="overflow-hidden rounded-xl border border-stone-200 bg-stone-50">
                    <div className={`relative flex aspect-[16/10] items-center justify-center overflow-hidden bg-gradient-to-br ${paletteClass(slot.fallback_palette_key)}`}>
                      {previewUrl ? <>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={previewUrl} alt={slot.fallback_title[language]} className="h-full w-full object-cover" />
                      </> : (
                        <div className="p-5 text-center text-white drop-shadow"><strong className="block text-lg">{slot.fallback_title[language]}</strong><span className="mt-1 block text-xs">{slot.fallback_description[language]}</span></div>
                      )}
                    </div>
                    <div className="space-y-3 p-4">
                      <div><p className="break-all text-xs font-black text-stone-900">{slot.slot_id}</p><p className="text-xs text-stone-500">{asset ? `${asset.width} x ${asset.height} · ${asset.mime_type}` : "Placeholder active"}</p></div>
                      <div className="flex flex-wrap gap-2">
                        <label className={buttonClass}>{asset ? "Replace" : "Upload"}<input data-testid={`visual-upload-${slot.slot_id}`} type="file" accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(slot, file).catch((error) => setAssetErrors((current) => ({ ...current, [slot.slot_id]: errorMessage(error) }))); event.target.value = ""; }} /></label>
                        <button type="button" className={dangerButtonClass} disabled={!asset} onClick={() => clearSlot(slot)}>Clear</button>
                      </div>
                      {assetErrors[slot.slot_id] ? <p role="alert" className="text-xs font-semibold text-red-700">{assetErrors[slot.slot_id]}</p> : null}
                      {asset ? <div className="grid gap-2"><Field label="Source"><TextInput value={asset.source} onChange={(value) => update((next) => { next.visuals!.visual_assets.find((item) => item.asset_key === asset.asset_key)!.source = value; })} /></Field><Field label="License"><TextInput value={asset.license} onChange={(value) => update((next) => { next.visuals!.visual_assets.find((item) => item.asset_key === asset.asset_key)!.license = value; })} /></Field><p className="break-all text-[10px] text-stone-500">SHA-256 {asset.sha256}</p></div> : null}
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        ))}
        <section className="space-y-4 border-t border-stone-200 pt-6">
          <h3 className="text-lg font-black">Runtime renderer preview</h3>
          <IslandMap map={draft.map} locations={worldLocations(draft)} actors={[]} visuals={rendererVisuals} language={language} currentLocationId={previewLocation?.location_id ?? ""} selectedLocationId={previewLocation?.location_id ?? null} selectedActorId={null} statusForLocation={() => "reachable"} statusLabelForLocation={() => "Preview"} onSelectLocation={selectLocation} onSelectActor={() => undefined} />
          {previewLocation && previewLayout ? <LocationScene language={language} location={worldLocation(previewLocation)} layout={previewLayout} actors={[]} visuals={rendererVisuals} interactionPoints={worldInteractionPoints(previewLocation)} ambientConversations={[]} selectedObjectId={null} selectedActorId={null} busy onInspect={() => undefined} onSelectActor={() => undefined} /> : null}
        </section>
      </div>
    </EditorSection>
  );
}

function PreviewPanel({ draft, location, event, language, selectLocation, assetFiles }: { draft: StudioDraft; location?: StudioLocation; event?: StudioEvent; language: Language; selectLocation: (id: string) => void; assetFiles: Record<string, LocalAssetFile> }) {
  const layout = draft.map.scene_layouts.find((item) => item.location_id === location?.location_id);
  const previewEvent = event ? worldEvent(event) : null;
  const visuals = studioWorldVisuals(draft, assetFiles);
  const previewLocation = location ? worldLocation(location) : null;
  const sceneSlot = location ? visuals?.slots[`locations.${location.location_id}.scene_image`] : undefined;
  const locationLabel = previewLocation
    ? previewLocation.translations?.[language]?.name ?? (language === "zh-CN" ? previewLocation.name_zh_cn : previewLocation.name) ?? previewLocation.name
    : language === "zh-CN" ? "预览地点" : "Preview location";
  return (
    <EditorSection title="Runtime component previews" description="These are the same map, scene, and narrative-overlay components used by the island page.">
      <div className="space-y-6">
        <IslandMap map={draft.map} locations={worldLocations(draft)} actors={[]} visuals={visuals} language={language} currentLocationId={location?.location_id ?? ""} selectedLocationId={location?.location_id ?? null} selectedActorId={null} statusForLocation={() => "reachable"} statusLabelForLocation={() => "Preview"} onSelectLocation={selectLocation} onSelectActor={() => undefined} />
        {location && layout ? (
          <LocationScene language={language} location={worldLocation(location)} layout={layout} actors={[] as WorldActor[]} visuals={visuals} interactionPoints={worldInteractionPoints(location)} ambientConversations={[]} selectedObjectId={null} selectedActorId={null} busy onInspect={() => undefined} onSelectActor={() => undefined} />
        ) : null}
        {previewEvent ? (
          <div data-testid="studio-event-preview" className="relative min-h-[460px] overflow-hidden rounded-xl border border-stone-200 bg-stone-100">
            <NarrativeChoiceOverlay
              language={language}
              event={previewEvent}
              scenario={null}
              scenarioKind="unsupported"
              seats={[]}
              selectedSeatId=""
              locationName={locationLabel}
              locationSceneUrl={sceneSlot?.asset?.url}
              eventResponse=""
              customResponse=""
              busy={false}
              canAction={() => true}
              onEventResponseChange={() => undefined}
              onCustomResponseChange={() => undefined}
              onEventAction={() => undefined}
              onScenarioResponse={() => undefined}
              onSeatView={() => undefined}
              onSeatSelect={() => undefined}
              onScenarioSkip={() => undefined}
            />
          </div>
        ) : null}
      </div>
    </EditorSection>
  );
}

type EditorProps = { draft: StudioDraft; update: (mutator: (next: StudioDraft) => void) => void };

function ValidationPanel({ validation }: { validation: StudioValidation }) {
  return (
    <section data-testid="studio-validation" className={`rounded-2xl border p-5 ${validation.valid ? "border-emerald-300 bg-emerald-50" : "border-red-300 bg-red-50"}`}>
      <h2 className="font-bold">{validation.valid ? "Content is schema-valid" : "Validation errors"}</h2>
      {validation.errors.map((error) => <p key={`${error.file}${error.json_path}`} className="mt-2 text-sm"><strong>{error.file}:{error.json_path}</strong> — {error.reason}</p>)}
      {validation.version_conflicts.length ? (
        <div data-testid="studio-version-conflicts" className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
          <strong>Version conflicts:</strong>
          <ul className="mt-1 list-disc pl-5">{validation.version_conflicts.map((conflict) => <li key={conflict.field}>{conflict.message}</li>)}</ul>
        </div>
      ) : null}
    </section>
  );
}

function EditorSection({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return <div><h2 className="text-2xl font-black">{title}</h2><p className="mt-1 mb-5 text-sm text-stone-600">{description}</p>{children}</div>;
}

function EntityToolbar({ values, selected, onSelect, selectTestId, onAdd, addLabel, addTestId, onDelete }: { values: Array<{ id: string; label: string }>; selected: string; onSelect: (id: string) => void; selectTestId: string; onAdd: () => void; addLabel: string; addTestId: string; onDelete: () => void }) {
  return <div className="flex flex-wrap gap-2"><select data-testid={selectTestId} className={inputClass} value={selected} onChange={(event) => onSelect(event.target.value)}>{values.map((item) => <option key={item.id} value={item.id}>{item.label} ({item.id})</option>)}</select><button data-testid={addTestId} type="button" className={buttonClass} onClick={onAdd}>{addLabel}</button><button type="button" className={dangerButtonClass} onClick={onDelete} disabled={values.length <= 1}>Delete selected</button></div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block text-xs font-bold text-stone-600"><span className="mb-1 block">{label}</span>{children}</label>; }
function TextInput({ value, onChange, disabled, testId }: { value: string; onChange?: (value: string) => void; disabled?: boolean; testId?: string }) { return <input data-testid={testId} className={inputClass} value={value} disabled={disabled} onChange={(event) => onChange?.(event.target.value)} />; }
function NumberInput({ value, onChange, disabled, step = "1" }: { value: number; onChange?: (value: number) => void; disabled?: boolean; step?: string }) { return <input type="number" step={step} className={inputClass} value={value} disabled={disabled} onChange={(event) => onChange?.(Number(event.target.value))} />; }
function SelectInput({ value, options, onChange, testId, includeBlank = false }: { value: string; options: string[]; onChange: (value: string) => void; testId?: string; includeBlank?: boolean }) { return <select data-testid={testId} className={inputClass} value={value} onChange={(event) => onChange(event.target.value)}>{includeBlank ? <option value="">None</option> : null}{options.map((option) => <option key={option}>{option}</option>)}</select>; }
function RenamableIdInput({ value, onCommit, numeric = false }: { value: string; onCommit: (value: string) => void; numeric?: boolean }) {
  const [draftValue, setDraftValue] = useState(value);
  return <input data-testid="studio-renamable-id" type={numeric ? "number" : "text"} className={inputClass} value={draftValue} onChange={(event) => setDraftValue(event.target.value)} onBlur={() => { const normalized = draftValue.trim(); if (normalized && normalized !== value) onCommit(normalized); else setDraftValue(value); }} />;
}
function LocalizedFields({ label, value, onChange, multiline = false }: { label: string; value: LocalizedText; onChange: (locale: keyof LocalizedText, value: string) => void; multiline?: boolean }) {
  const Element = multiline ? "textarea" : "input";
  return <div className="grid gap-2"><Field label={`${label} (English)`}><Element className={inputClass} value={value.en} onChange={(event) => onChange("en", event.target.value)} /></Field><Field label={`${label} (中文)`}><Element className={inputClass} value={value["zh-CN"]} onChange={(event) => onChange("zh-CN", event.target.value)} /></Field></div>;
}

function LocalizedOptionalFields({ label, value, onChange, multiline = false }: { label: string; value?: LocalizedText; onChange: (value?: LocalizedText) => void; multiline?: boolean }) {
  if (!value) return <button type="button" className={buttonClass} onClick={() => onChange({ en: "", "zh-CN": "" })}>Add {label.toLowerCase()}</button>;
  return <div><LocalizedFields label={label} value={value} multiline={multiline} onChange={(locale, text) => onChange({ ...value, [locale]: text })} /><button type="button" className={`${dangerButtonClass} mt-2`} onClick={() => onChange(undefined)}>Remove {label.toLowerCase()}</button></div>;
}

function LocalizedListEditor({ label, values, onChange }: { label: string; values: LocalizedText[]; onChange: (values: LocalizedText[]) => void }) {
  return <section className="rounded-xl border border-stone-200 p-3"><h3 className="font-bold capitalize">{label}</h3><div className="mt-2 space-y-2">{values.map((value, index) => <div key={index} className="rounded-lg bg-stone-50 p-2"><LocalizedFields label={`Item ${index + 1}`} value={value} multiline onChange={(locale, text) => { const next = clone(values); next[index][locale] = text; onChange(next); }} /><button type="button" className={`${dangerButtonClass} mt-2`} onClick={() => onChange(values.filter((_, itemIndex) => itemIndex !== index))}>Remove item</button></div>)}</div><button type="button" className={`${buttonClass} mt-2`} onClick={() => onChange([...values, { en: "New item", "zh-CN": "New item" }])}>Add item</button></section>;
}

function JsonObjectField({ label, value, onChange }: { label: string; value?: Record<string, unknown>; onChange: (value: Record<string, unknown>) => void }) {
  const serialized = JSON.stringify(value ?? {}, null, 2);
  const [text, setText] = useState(serialized);
  const [error, setError] = useState("");
  return (
    <Field label={label}>
      <textarea
        className={`${inputClass} min-h-28 font-mono text-xs`}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => {
          try {
            const parsed = JSON.parse(text) as unknown;
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Use a JSON object.");
            setError("");
            onChange(parsed as Record<string, unknown>);
          } catch (caught) {
            setError(caught instanceof Error ? caught.message : "Invalid JSON object.");
          }
        }}
      />
      {error ? <span className="mt-1 block text-xs text-red-700">{error}</span> : null}
    </Field>
  );
}

const inputClass = "w-full min-w-0 rounded-md border border-stone-300 bg-white px-3 py-2 text-sm disabled:bg-stone-100";
const buttonClass = "rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-bold hover:bg-stone-50 disabled:opacity-50";
const primaryButtonClass = "rounded-md bg-teal-700 px-4 py-2 text-sm font-bold text-white hover:bg-teal-800 disabled:opacity-50";
const dangerButtonClass = "rounded-md border border-red-300 bg-white px-3 py-2 text-sm font-bold text-red-700 hover:bg-red-50 disabled:opacity-40";
function pill(active: boolean) { return `rounded-full border px-3 py-1.5 text-xs font-bold ${active ? "border-teal-700 bg-teal-700 text-white" : "border-stone-300 bg-white text-stone-700"}`; }

function simulateActivityCandidates(systems: NonNullable<StudioDraft["systems"]>, actionId: string, locationId: string, participantCount: number) {
  const limit = Number(systems.emergence_policy.max_activity_creations_per_tick ?? 0);
  let created = 0;
  return systems.activity_recipes.filter((item) => item.action_ids.includes(actionId) && item.location_ids.includes(locationId)).sort((left, right) => left.recipe_id.localeCompare(right.recipe_id)).map((item) => {
    if (participantCount < item.min_participants) return { item, outcome: "blocked", reason: "insufficient_participants" };
    if (created >= limit) return { item, outcome: "blocked", reason: "activity_rate_limit" };
    created += 1;
    return { item, outcome: "selected", reason: "authored_recipe_matched" };
  });
}

function addSystemAction(draft: StudioDraft) {
  if (!draft.systems) return;
  if (draft.manifest.schema_version === "content-pack-v5") { draft.systems.action_definitions.push(modularAction(draft.systems)); return; }
  const number = draft.systems.action_definitions.length + 1;
  draft.systems.action_definitions.push({ action_id: `action_${number}`, label: { en: "New action", "zh-CN": "新动作" }, actor_types: ["participant", "resident"], target_types: ["object"], duration_minutes: 5, consequences: [] });
}

function removeSystemAction(draft: StudioDraft, index: number) {
  if (!draft.systems) return;
  const removed = draft.systems.action_definitions.splice(index, 1)[0];
  draft.systems.affordances = draft.systems.affordances.filter((item) => item.action_id !== removed.action_id);
  draft.systems.activity_recipes.forEach((item) => { item.action_ids = item.action_ids.filter((id) => id !== removed.action_id); });
}

function addSystemAffordance(draft: StudioDraft) {
  const systems = draft.systems;
  const action = systems?.action_definitions[0];
  if (!systems || !action) return;
  if (draft.manifest.schema_version === "content-pack-v5") { systems.affordances.push(modularAffordance(draft)); return; }
  const number = systems.affordances.length + 1;
  systems.affordances.push({ affordance_id: `affordance_${number}`, action_id: action.action_id, location_ids: draft.locations.locations[0] ? [draft.locations.locations[0].location_id] : [], object_ids: [], enabled: true });
}

function addActivityRecipe(draft: StudioDraft) {
  const systems = draft.systems;
  const action = systems?.action_definitions[0];
  const location = draft.locations.locations[0];
  if (!systems || !action || !location) return;
  if (draft.manifest.schema_version === "content-pack-v5") { systems.activity_recipes.push(modularRecipe(draft)); return; }
  const number = systems.activity_recipes.length + 1;
  systems.activity_recipes.push({ recipe_id: `activity_${number}`, label: { en: "New group activity", "zh-CN": "新集体活动" }, location_ids: [location.location_id], action_ids: [action.action_id], min_participants: 2, max_participants: 4, duration_minutes: 30 });
}

function addSceneHotspot(draft: StudioDraft, locationId: string) {
  const layout = draft.map.scene_layouts.find((item) => item.location_id === locationId);
  const point = draft.locations.locations.find((item) => item.location_id === locationId)?.interaction_points[0];
  if (!layout || !point) return;
  layout.hotspots ??= [];
  const number = layout.hotspots.length + 1;
  layout.hotspots.push({
    hotspot_id: `hotspot_${number}`,
    shape: "circle",
    target_object_id: point.object_id,
    x: layout.width / 2,
    y: layout.height / 2,
    radius: 40,
    label: { en: `Explore ${point.name.en}`, "zh-CN": `探索${point.name["zh-CN"]}` },
    log_code: "hotspot_select",
  });
}

function setHotspotShape(draft: StudioDraft, locationId: string, index: number, shape: "circle" | "rectangle") {
  const hotspot = draft.map.scene_layouts.find((item) => item.location_id === locationId)?.hotspots?.[index];
  if (!hotspot) return;
  hotspot.shape = shape;
  if (shape === "circle") {
    hotspot.radius = hotspot.radius ?? 40;
    delete hotspot.width;
    delete hotspot.height;
  } else {
    hotspot.width = hotspot.width ?? 80;
    hotspot.height = hotspot.height ?? 60;
    delete hotspot.radius;
  }
}

function addLocation(draft: StudioDraft, connectToId: string) {
  const number = nextNumber(draft.locations.locations.map((item) => item.location_id), "studio_place_");
  const id = `studio_place_${number}`;
  const source = draft.map.location_nodes.find((item) => item.location_id === connectToId) ?? draft.map.location_nodes[0];
  const x = Math.min(draft.map.width - 40, (source?.x ?? 100) + 90);
  const y = Math.min(draft.map.height - 40, (source?.y ?? 100) + 70);
  const target = draft.locations.locations.find((item) => item.location_id === connectToId) ?? draft.locations.locations[0];
  if (target) target.connected_location_ids.push(id);
  draft.locations.locations.push({ location_id: id, name: { en: `Untitled location ${number}`, "zh-CN": `未命名地点 ${number}` }, description: { en: "Describe this new location.", "zh-CN": "请描述这个新地点。" }, scene_type: "community", version: draft.manifest.world_version, connected_location_ids: target ? [target.location_id] : [], opening_hours: { always_open: true }, interaction_points: [], allowed_actions: ["move", "observe", "approach", "wait", "end_conversation"], event_pool_ids: [] });
  if (!target) {
    draft.manifest.start_location_id = id;
    draft.manifest.authoring_only = false;
    if (draft.map.land_polygon.length < 3) draft.map.land_polygon = [[80, 80], [draft.map.width - 80, 80], [draft.map.width / 2, draft.map.height - 80]];
    ensureBaseVisualSlots(draft);
  }
  draft.map.location_nodes.push({ location_id: id, x, y, click_radius: 28, icon_key: "square", label_offset: [0, -38] });
  if (target && source) draft.map.paths.push({ path_id: `${target.location_id}_to_${id}`, from_location_id: target.location_id, to_location_id: id, points: [[source.x, source.y], [Math.round((source.x + x) / 2), Math.round((source.y + y) / 2)], [x, y]] });
  draft.map.scene_layouts.push({ location_id: id, width: 800, height: 450, participant_spawn: [100, 360], resident_slots: [[220, 300], [360, 260], [500, 300]], interaction_point_positions: {}, ...(["content-pack-v4", "content-pack-v5"].includes(draft.manifest.schema_version) ? { hotspots: [] } : {}) });
  addVisualSlot(draft, `locations.${id}.map_thumbnail`, "location_map_thumbnail", id, `Studio Place ${number}`, "工作室地点", "forest_green");
  addVisualSlot(draft, `locations.${id}.scene_image`, "location_scene_image", id, `Studio Place ${number}`, "工作室地点", "sunset_rose");
}

function deleteLocation(draft: StudioDraft, id: string) {
  draft.locations.locations = draft.locations.locations.filter((item) => item.location_id !== id);
  draft.locations.locations.forEach((item) => { item.connected_location_ids = item.connected_location_ids.filter((target) => target !== id); });
  draft.map.location_nodes = draft.map.location_nodes.filter((item) => item.location_id !== id);
  draft.map.scene_layouts = draft.map.scene_layouts.filter((item) => item.location_id !== id);
  draft.map.paths = draft.map.paths.filter((item) => item.from_location_id !== id && item.to_location_id !== id);
  if (draft.visuals) draft.visuals.visual_slots = draft.visuals.visual_slots.filter((item) => item.target_id !== id);
  if (!draft.locations.locations.length) {
    draft.manifest.start_location_id = "";
    draft.manifest.authoring_only = true;
    draft.map.land_polygon = [];
  } else if (draft.manifest.start_location_id === id) {
    draft.manifest.start_location_id = draft.locations.locations[0].location_id;
  }
}

function removePath(draft: StudioDraft, index: number) {
  const [path] = draft.map.paths.splice(index, 1);
  const source = draft.locations.locations.find((item) => item.location_id === path.from_location_id);
  const target = draft.locations.locations.find((item) => item.location_id === path.to_location_id);
  if (source) source.connected_location_ids = source.connected_location_ids.filter((id) => id !== path.to_location_id);
  if (target) target.connected_location_ids = target.connected_location_ids.filter((id) => id !== path.from_location_id);
}

function addMapConnection(draft: StudioDraft, sourceId: string, targetId: string) {
  if (!sourceId || !targetId || sourceId === targetId) return;
  const sourceLocation = draft.locations.locations.find((item) => item.location_id === sourceId);
  const targetLocation = draft.locations.locations.find((item) => item.location_id === targetId);
  const sourceNode = draft.map.location_nodes.find((item) => item.location_id === sourceId);
  const targetNode = draft.map.location_nodes.find((item) => item.location_id === targetId);
  if (!sourceLocation || !targetLocation || !sourceNode || !targetNode || sourceLocation.connected_location_ids.includes(targetId)) return;
  sourceLocation.connected_location_ids.push(targetId);
  targetLocation.connected_location_ids.push(sourceId);
  let pathId = `${sourceId}_to_${targetId}`;
  let suffix = 2;
  while (draft.map.paths.some((path) => path.path_id === pathId)) pathId = `${sourceId}_to_${targetId}_${suffix++}`;
  draft.map.paths.push({
    path_id: pathId,
    from_location_id: sourceId,
    to_location_id: targetId,
    points: [[sourceNode.x, sourceNode.y], [Math.round((sourceNode.x + targetNode.x) / 2), Math.round((sourceNode.y + targetNode.y) / 2)], [targetNode.x, targetNode.y]],
  });
}

function renameLocation(draft: StudioDraft, oldId: string, nextId: string) {
  if (!nextId || draft.locations.locations.some((item) => item.location_id === nextId)) return;
  const location = draft.locations.locations.find((item) => item.location_id === oldId);
  if (!location) return;
  location.location_id = nextId;
  if (draft.manifest.start_location_id === oldId) draft.manifest.start_location_id = nextId;
  for (const item of draft.locations.locations) item.connected_location_ids = item.connected_location_ids.map((id) => id === oldId ? nextId : id);
  for (const resident of draft.residents.residents) {
    if (resident.home_location_id === oldId) resident.home_location_id = nextId;
    resident.schedule.forEach((block) => { if (block.location_id === oldId) block.location_id = nextId; });
    if (resident.autonomy) resident.autonomy.preferred_location_ids = resident.autonomy.preferred_location_ids.map((id) => id === oldId ? nextId : id);
  }
  for (const event of draft.events.events) {
    event.location_ids = event.location_ids.map((id) => id === oldId ? nextId : id);
    for (const condition of event.trigger.conditions?.items ?? []) if (condition.type === "location" && condition.value === oldId) condition.value = nextId;
    for (const stage of event.stages ?? []) for (const choice of stage.actions) for (const effect of choice.effects ?? []) {
      if (effect.type === "move_participant" && effect.location_id === oldId) effect.location_id = nextId;
      if (effect.type === "goal_update" && effect.goal.target_location_id === oldId) effect.goal.target_location_id = nextId;
    }
  }
  draft.map.location_nodes.forEach((item) => { if (item.location_id === oldId) item.location_id = nextId; });
  draft.map.scene_layouts.forEach((item) => { if (item.location_id === oldId) item.location_id = nextId; });
  draft.map.paths.forEach((path) => { if (path.from_location_id === oldId) path.from_location_id = nextId; if (path.to_location_id === oldId) path.to_location_id = nextId; });
  for (const slot of draft.visuals?.visual_slots ?? []) {
    if (slot.target_id === oldId) slot.target_id = nextId;
    if (slot.slot_id.startsWith(`locations.${oldId}.`)) slot.slot_id = slot.slot_id.replace(`locations.${oldId}.`, `locations.${nextId}.`);
  }
}

function renameInteractionPoint(draft: StudioDraft, locationId: string, oldId: string, nextId: string) {
  const location = draft.locations.locations.find((item) => item.location_id === locationId);
  const point = location?.interaction_points.find((item) => item.object_id === oldId);
  if (!point || !nextId || location!.interaction_points.some((item) => item.object_id === nextId)) return;
  point.object_id = nextId;
  const layout = draft.map.scene_layouts.find((item) => item.location_id === locationId);
  if (layout?.interaction_point_positions[oldId]) {
    layout.interaction_point_positions[nextId] = layout.interaction_point_positions[oldId];
    delete layout.interaction_point_positions[oldId];
  }
  for (const hotspot of layout?.hotspots ?? []) if (hotspot.target_object_id === oldId) hotspot.target_object_id = nextId;
  for (const event of draft.events.events) {
    for (const condition of event.trigger.conditions?.items ?? []) if (condition.type === "object_choice" && condition.value === oldId) condition.value = nextId;
    for (const stage of event.stages ?? []) for (const choice of stage.actions) if (choice.target_id === oldId) choice.target_id = nextId;
  }
}

function renameResident(draft: StudioDraft, oldId: number, nextId: number) {
  if (!Number.isInteger(nextId) || nextId < 1 || draft.residents.residents.some((item) => item.agent_id === nextId)) return;
  const resident = draft.residents.residents.find((item) => item.agent_id === oldId);
  if (!resident) return;
  resident.agent_id = nextId;
  for (const event of draft.events.events) {
    for (const condition of event.trigger.conditions?.items ?? []) if (condition.type === "resident_present" && condition.value === oldId) condition.value = nextId;
    for (const action of event.actions) {
      if (action.memory_owner_agent_id === oldId) action.memory_owner_agent_id = nextId;
      if (action.relationship_effect?.target_agent_id === oldId) action.relationship_effect.target_agent_id = nextId;
    }
    for (const stage of event.stages ?? []) for (const choice of stage.actions) {
      if (choice.target_agent_id === oldId) choice.target_agent_id = nextId;
      if (choice.npc_response?.npc_id === oldId) choice.npc_response.npc_id = nextId;
      for (const effect of choice.effects ?? []) {
        if (effect.type === "relationship_delta" && effect.target_agent_id === oldId) effect.target_agent_id = nextId;
        if (effect.type === "add_memory" && effect.owner_agent_id === oldId) effect.owner_agent_id = nextId;
      }
    }
    for (const publication of event.social_publications ?? []) {
      publication.eligible_author_ids = publication.eligible_author_ids.map((id) => id === oldId ? nextId : id);
      publication.witness_agent_ids = publication.witness_agent_ids.map((id) => id === oldId ? nextId : id);
      for (const template of publication.templates) if (template.author_agent_id === oldId) template.author_agent_id = nextId;
      for (const [factId, factValue] of Object.entries(publication.facts)) {
        if (typeof factValue === "number" && factValue === oldId && factId.endsWith("agent_id")) publication.facts[factId] = nextId;
        if (Array.isArray(factValue) && factId.endsWith("agent_ids")) publication.facts[factId] = factValue.map((id) => id === oldId ? nextId : id);
      }
    }
  }
  const oldTarget = `resident:${oldId}`;
  const nextTarget = `resident:${nextId}`;
  for (const slot of draft.visuals?.visual_slots ?? []) {
    if (slot.target_id === oldTarget) slot.target_id = nextTarget;
    if (slot.slot_id.startsWith(`actors.${oldTarget}.`)) slot.slot_id = slot.slot_id.replace(`actors.${oldTarget}.`, `actors.${nextTarget}.`);
  }
}

function renameEvent(draft: StudioDraft, oldId: string, nextId: string) {
  if (!nextId || draft.events.events.some((item) => item.event_id === nextId)) return;
  const event = draft.events.events.find((item) => item.event_id === oldId);
  if (!event) return;
  event.event_id = nextId;
  for (const location of draft.locations.locations) for (const point of location.interaction_points) if (point.interaction_event_id === oldId) point.interaction_event_id = nextId;
  for (const item of draft.events.events) {
    for (const action of item.actions) if (action.follow_up_event_id === oldId) action.follow_up_event_id = nextId;
    for (const condition of item.trigger.conditions?.items ?? []) if (condition.type === "event_status" && String(condition.value).startsWith(`${oldId}.`)) condition.value = `${nextId}.${String(condition.value).slice(oldId.length + 1)}`;
    for (const stage of item.stages ?? []) for (const choice of stage.actions) for (const effect of choice.effects ?? []) if ((effect.type === "start_event" || effect.type === "schedule_event") && effect.event_id === oldId) effect.event_id = nextId;
  }
}

function toggleString<T extends string>(values: T[], value: T, enabled: boolean) {
  const index = values.indexOf(value);
  if (enabled && index < 0) values.push(value);
  if (!enabled && index >= 0) values.splice(index, 1);
}

function addInteractionPoint(draft: StudioDraft, locationId: string) {
  const location = draft.locations.locations.find((item) => item.location_id === locationId);
  const layout = draft.map.scene_layouts.find((item) => item.location_id === locationId);
  if (!location || !layout) return;
  const objectId = `${locationId}_object_${location.interaction_points.length + 1}`;
  location.interaction_points.push({ object_id: objectId, type: "notice", name: { en: "New object", "zh-CN": "新互动点" }, description: { en: "A draft interaction point.", "zh-CN": "一个草稿互动点。" }, renderer_key: "notice" });
  layout.interaction_point_positions[objectId] = [300 + location.interaction_points.length * 40, 120];
}

function deleteInteractionPoint(draft: StudioDraft, locationId: string, objectId: string) {
  const location = draft.locations.locations.find((item) => item.location_id === locationId);
  const layout = draft.map.scene_layouts.find((item) => item.location_id === locationId);
  if (location) location.interaction_points = location.interaction_points.filter((item) => item.object_id !== objectId);
  if (layout) {
    delete layout.interaction_point_positions[objectId];
    layout.hotspots = (layout.hotspots ?? []).filter((item) => item.target_object_id !== objectId);
  }
}

function addResident(draft: StudioDraft) {
  const source = draft.residents.residents[0];
  const firstLocation = draft.locations.locations[0];
  if (!firstLocation) return;
  const nextAgentId = Math.max(0, ...draft.residents.residents.map((item) => item.agent_id)) + 1;
  const resident: StudioResident = source ? clone(source) : {
    agent_id: nextAgentId,
    name: `Untitled resident ${nextAgentId}`,
    adult_age_range: "25-34",
    role: { en: "Island resident", "zh-CN": "岛屿居民" },
    public_summary: { en: "Describe this resident.", "zh-CN": "请描述这位居民。" },
    home_location_id: firstLocation.location_id,
    background: { en: "Add a background.", "zh-CN": "请添加背景。" },
    personality: { en: "Add personality traits.", "zh-CN": "请添加性格特征。" },
    values: [{ en: "Add a value.", "zh-CN": "请添加价值观。" }],
    preferences: [{ en: "Add a preference.", "zh-CN": "请添加偏好。" }],
    communication_style: { en: "Natural and respectful.", "zh-CN": "自然且尊重。" },
    goals: [{ en: "Add a goal.", "zh-CN": "请添加目标。" }],
    knowledge_boundaries: [{ en: "Knows only authored public world facts.", "zh-CN": "只了解已创作的公开世界事实。" }],
    avoid_patterns: [{ en: "Does not infer private or clinical information.", "zh-CN": "不推断私人或临床信息。" }],
    safety_rules: [{ en: "Identifies as an AI island character when asked.", "zh-CN": "被问及时说明自己是 AI 岛屿角色。" }],
    avatar_key: "resident_default",
    marker_color_key: "resident_teal",
    profile_version: `draft-resident-${nextAgentId}-v1`,
    prompt_version: `draft-resident-${nextAgentId}-prompt-v1`,
    autonomy: { enabled: false, allowed_intents: ["idle"], preferred_location_ids: [firstLocation.location_id], free_time_state_ids: draft.manifest.schema_version === "content-pack-v5" ? [`resident_${nextAgentId}_daily`] : [], action_cooldown_minutes: 15, idle_weight: 1, inspect_weight: 0, socialize_weight: 0, greet_weight: 0, travel_weight: 0 },
    schedule: [{ state_id: `resident_${nextAgentId}_daily`, start_minute: draft.manifest.calendar.day_start_minute, end_minute: draft.manifest.calendar.day_end_minute, location_id: firstLocation.location_id, activity: { en: "Following a draft routine", "zh-CN": "按草稿日程活动" }, goal: { en: "Follow the authored schedule", "zh-CN": "遵循已创作的日程" } }],
  };
  resident.agent_id = nextAgentId;
  resident.name = `Studio Agent ${resident.agent_id}`;
  resident.avatar_key = "resident_default";
  resident.marker_color_key = "resident_teal";
  resident.profile_version = `studio-agent-${resident.agent_id}-v1`;
  const renamedStates = new Map<string, string>();
  resident.schedule.forEach((block, index) => {
    const nextStateId = `studio_agent_${resident.agent_id}_${index + 1}`;
    renamedStates.set(block.state_id, nextStateId);
    block.state_id = nextStateId;
  });
  if (resident.autonomy) {
    resident.autonomy.free_time_state_ids = resident.autonomy.free_time_state_ids
      .map((stateId) => renamedStates.get(stateId))
      .filter((stateId): stateId is string => Boolean(stateId));
  }
  draft.residents.residents.push(resident);
  const actorId = `resident:${resident.agent_id}`;
  addVisualSlot(draft, `actors.${actorId}.map_thumbnail`, "actor_map_thumbnail", actorId, resident.name, resident.name, "harbor_blue");
  addVisualSlot(draft, `actors.${actorId}.dialogue_portrait`, "actor_dialogue_portrait", actorId, resident.name, resident.name, "harbor_blue");
}

function ensureBaseVisualSlots(draft: StudioDraft) {
  if (!draft.visuals) return;
  const existing = new Set(draft.visuals.visual_slots.map((slot) => slot.slot_id));
  if (!existing.has("map.image")) addVisualSlot(draft, "map.image", "map_image", draft.map.map_id, "Island map", "岛屿地图", "ocean_teal");
  if (!existing.has("actors.participant.map_thumbnail")) addVisualSlot(draft, "actors.participant.map_thumbnail", "actor_map_thumbnail", "participant", "Participant", "参与者", "neutral_stone");
  if (!existing.has("actors.participant.dialogue_portrait")) addVisualSlot(draft, "actors.participant.dialogue_portrait", "actor_dialogue_portrait", "participant", "Participant", "参与者", "neutral_stone");
}

function deleteResident(draft: StudioDraft, agentId: number) {
  draft.residents.residents = draft.residents.residents.filter((item) => item.agent_id !== agentId);
  const actorId = `resident:${agentId}`;
  if (draft.visuals) draft.visuals.visual_slots = draft.visuals.visual_slots.filter((item) => item.target_id !== actorId);
}

function addVisualSlot(
  draft: StudioDraft,
  slotId: string,
  slotType: StudioVisualSlot["slot_type"],
  targetId: string,
  titleEn: string,
  titleZh: string,
  palette: string,
) {
  if (!draft.visuals) return;
  draft.visuals.visual_slots.push({
    slot_id: slotId,
    slot_type: slotType,
    target_id: targetId,
    asset_key: null,
    fallback_palette_key: palette,
    fallback_title: { en: titleEn, "zh-CN": titleZh },
    fallback_description: {
      en: `Placeholder for ${titleEn}`,
      "zh-CN": `${titleZh}的占位图`,
    },
  });
}

function addScheduleBlock(draft: StudioDraft, agentId: number) {
  const resident = draft.residents.residents.find((item) => item.agent_id === agentId);
  if (!resident) return;
  resident.schedule.push({ state_id: `agent_${agentId}_draft_${resident.schedule.length + 1}`, start_minute: draft.manifest.calendar.day_start_minute, end_minute: draft.manifest.calendar.day_end_minute, location_id: resident.home_location_id, activity: { en: "draft activity", "zh-CN": "草稿活动" }, goal: { en: "draft goal", "zh-CN": "草稿目标" }, days: [draft.manifest.calendar.total_days] });
}

function addEvent(draft: StudioDraft) {
  const location = draft.locations.locations[0];
  if (!location) return;
  const number = nextNumber(draft.events.events.map((item) => item.event_id), "studio_event_");
  const id = `studio_event_${number}`;
  const pool = `${id}_pool`;
  location.event_pool_ids.push(pool);
  if (!location.allowed_actions.includes("event_action")) location.allowed_actions.push("event_action");
  const event: StudioEvent = { event_id: id, event_type: `studio_ambient_${number}`, version: draft.manifest.event_pack_version, title: { en: `Untitled event ${number}`, "zh-CN": `未命名事件 ${number}` }, stimulus: { en: "Describe what happens.", "zh-CN": "请描述发生的事情。" }, location_ids: [location.location_id], event_pool_ids: [pool], trigger: { type: "on_location_enter", time_window: { start_minute: draft.manifest.calendar.day_start_minute, end_minute: draft.manifest.calendar.day_end_minute }, ...(supportsTypedFlows(draft.manifest.schema_version) ? { conditions: { mode: "all" as const, items: [] } } : {}) }, weight: 1, cooldown_minutes: 60, max_occurrences: 1, prerequisites: { min_day: 1, max_day: draft.manifest.calendar.total_days }, exclusion_flags: { active_scenario: true, active_event: true }, actions: [{ action_id: "continue", label: { en: "Continue", "zh-CN": "继续" }, requires_text: false, outcome_key: "complete" }] };
  draft.events.events.push(event);
  if (supportsTypedFlows(draft.manifest.schema_version)) convertToBehavioralEvent(draft, id);
}

function createInteractionFlow(draft: StudioDraft, locationId: string, objectId: string) {
  const location = draft.locations.locations.find((item) => item.location_id === locationId);
  const point = location?.interaction_points.find((item) => item.object_id === objectId);
  if (!location || !point) return;
  const base = `object_${objectId}_interaction`;
  let eventId = base;
  let suffix = 2;
  while (draft.events.events.some((item) => item.event_id === eventId)) eventId = `${base}_${suffix++}`;
  point.interaction_event_id = eventId;
  draft.events.events.push({
    event_id: eventId,
    event_type: eventId,
    version: draft.manifest.event_pack_version,
    title: clone(point.name),
    stimulus: clone(point.description),
    location_ids: [locationId],
    event_pool_ids: [],
    trigger: { type: "on_object_interact", conditions: { mode: "all", items: [] } },
    weight: 1,
    cooldown_minutes: 0,
    max_occurrences: 999,
    prerequisites: { min_day: 1, max_day: draft.manifest.calendar.total_days },
    exclusion_flags: { active_scenario: true, active_event: true },
    actions: [],
    renderer_key: "behavioral_event",
    initial_stage_id: "opening",
    stages: [{
      stage_id: "opening",
      title: clone(point.name),
      stimulus: clone(point.description),
      actions: [{
        action_id: "finish",
        label: { en: "Finish interacting", "zh-CN": "结束互动" },
        requires_text: false,
        action_type: "object_choice",
        terminal: true,
        outcome_code: "completed",
        action_minutes: 0,
        effects: [
          { type: "advance_time", minutes: 0 },
          { type: "complete_flow", outcome_code: "completed" },
        ],
      }],
    }],
    logging_config: { raw_schema_version: "content-flow-v1", store_diagnostic_labels: false },
    llm_context: {},
  });
}

function addEventAction(draft: StudioDraft, eventId: string) {
  const event = draft.events.events.find((item) => item.event_id === eventId);
  if (!event) return;
  event.actions.push({ action_id: `action_${event.actions.length + 1}`, label: { en: "New action", "zh-CN": "新选项" }, requires_text: false, outcome_key: "complete" });
}

function convertToBehavioralEvent(draft: StudioDraft, eventId: string) {
  const event = draft.events.events.find((item) => item.event_id === eventId);
  if (!event || event.stages?.length) return;
  const stageId = "opening";
  event.renderer_key = "behavioral_event";
  event.initial_stage_id = stageId;
  event.stages = [{
    stage_id: stageId,
    title: clone(event.title),
    stimulus: clone(event.stimulus),
    actions: event.actions.map((action) => ({
      action_id: action.action_id,
      label: clone(action.label),
      requires_text: action.requires_text,
      action_type: "complete_event",
      terminal: true,
      outcome_code: action.outcome_key === "leave" ? "left" : "completed",
      action_minutes: supportsTypedFlows(draft.manifest.schema_version) ? 0 : 5,
      ...(supportsTypedFlows(draft.manifest.schema_version) ? { effects: [{ type: "advance_time", minutes: 0 }, { type: "complete_flow", outcome_code: action.outcome_key === "leave" ? "left" : "completed" }] as StudioFlowEffect[] } : {}),
    })),
  }];
  event.actions = [];
  event.logging_config = {
    raw_schema_version: "behavioral-action-v1",
    store_diagnostic_labels: false,
  };
  event.llm_context = {
    knowledge_boundary: ["Do not infer mental health", "Keep ordinary role-play natural"],
  };
}

function addBehavioralStage(draft: StudioDraft, eventId: string) {
  const event = draft.events.events.find((item) => item.event_id === eventId);
  if (!event?.stages) return;
  let stageNumber = event.stages.length + 1;
  while (event.stages.some((stage) => stage.stage_id === `stage_${stageNumber}`)) stageNumber += 1;
  const stageId = `stage_${stageNumber}`;
  event.stages.push({
    stage_id: stageId,
    title: { en: "New stage", "zh-CN": "新阶段" },
    stimulus: { en: "Describe what is happening here.", "zh-CN": "描述这里正在发生什么。" },
    actions: [{
      action_id: "continue",
      label: { en: "Continue", "zh-CN": "继续" },
      requires_text: false,
      action_type: "complete_event",
      terminal: true,
      outcome_code: "completed",
      action_minutes: 5,
      ...(supportsTypedFlows(draft.manifest.schema_version) ? { effects: [{ type: "advance_time", minutes: 5 }, { type: "complete_flow", outcome_code: "completed" }] as StudioFlowEffect[] } : {}),
    }],
  });
}

function addBehavioralStageAction(draft: StudioDraft, eventId: string, stageIndex: number) {
  const stage = draft.events.events.find((item) => item.event_id === eventId)?.stages?.[stageIndex];
  if (!stage) return;
  stage.actions.push({
    action_id: `action_${stage.actions.length + 1}`,
    label: { en: "New action", "zh-CN": "新行动" },
    requires_text: false,
    action_type: "complete_event",
    terminal: true,
    outcome_code: "completed",
    action_minutes: 5,
    ...(supportsTypedFlows(draft.manifest.schema_version) ? { effects: [{ type: "advance_time", minutes: 5 }, { type: "complete_flow", outcome_code: "completed" }] as StudioFlowEffect[] } : {}),
  });
}

function conditionOperators(type: StudioTriggerCondition["type"]): StudioTriggerCondition["operator"][] {
  if (type === "world_day") return ["equals", "at_least", "at_most"];
  if (type === "world_time") return ["at_least", "at_most"];
  return ["equals"];
}

function defaultConditionValue(type: StudioTriggerCondition["type"], draft: StudioDraft): string | number {
  if (type === "world_day") return 1;
  if (type === "world_time") return draft.manifest.calendar.day_start_minute;
  if (type === "location") return draft.locations.locations[0]?.location_id ?? "";
  if (type === "resident_present") return draft.residents.residents[0]?.agent_id ?? 1;
  if (type === "action_type") return "move";
  if (type === "goal_status") return "goal_id.active";
  if (type === "event_status") return `${draft.events.events[0]?.event_id ?? "event_id"}.completed`;
  return "value";
}

type StudioFlowNode = NonNullable<StudioEvent["stages"]>[number];
type StudioFlowChoice = StudioFlowNode["actions"][number];

function flowTargets(node: StudioFlowNode): string[] {
  return Array.from(new Set(node.actions.flatMap((choice) =>
    (choice.effects ?? [])
      .filter((effect): effect is Extract<StudioFlowEffect, { type: "goto_node" }> => effect.type === "goto_node")
      .map((effect) => effect.node_id),
  )));
}

function flowProblems(event: StudioEvent): string[] {
  const nodes = event.stages ?? [];
  const ids = nodes.map((node) => node.stage_id);
  const idSet = new Set(ids);
  const problems: string[] = [];
  if (!nodes.length) return ["Add at least one node."];
  if (idSet.size !== ids.length) problems.push("Node IDs must be unique.");
  if (!event.initial_stage_id || !idSet.has(event.initial_stage_id)) problems.push("Choose an existing initial node.");
  for (const node of nodes) {
    if (!node.actions.length) problems.push(`${node.stage_id}: add at least one choice.`);
    for (const choice of node.actions) {
      const effects = choice.effects ?? [];
      const controls = effects.filter((effect) => ["goto_node", "complete_flow", "start_event"].includes(effect.type));
      if (controls.length !== 1) problems.push(`${node.stage_id}/${choice.action_id}: choose exactly one branch result.`);
      for (const target of flowTargets({ ...node, actions: [choice] })) {
        if (!idSet.has(target)) problems.push(`${node.stage_id}/${choice.action_id}: target ${target} does not exist.`);
      }
    }
  }
  const initial = event.initial_stage_id;
  if (initial && idSet.has(initial)) {
    const reachable = new Set<string>();
    const pending = [initial];
    while (pending.length) {
      const current = pending.pop()!;
      if (reachable.has(current)) continue;
      reachable.add(current);
      const node = nodes.find((item) => item.stage_id === current);
      if (node) pending.push(...flowTargets(node).filter((target) => idSet.has(target)));
    }
    const missing = ids.filter((id) => !reachable.has(id));
    if (missing.length) problems.push(`Unreachable nodes: ${missing.join(", ")}.`);
  }
  const canExit = new Set(nodes.filter((node) => node.actions.some((choice) =>
    (choice.effects ?? []).some((effect) => effect.type === "complete_flow" || effect.type === "start_event"),
  )).map((node) => node.stage_id));
  let changed = true;
  while (changed) {
    changed = false;
    for (const node of nodes) {
      if (!canExit.has(node.stage_id) && flowTargets(node).some((target) => canExit.has(target))) {
        canExit.add(node.stage_id);
        changed = true;
      }
    }
  }
  const trapped = ids.filter((id) => !canExit.has(id));
  if (trapped.length) problems.push(`No exit path from: ${trapped.join(", ")}.`);
  return Array.from(new Set(problems));
}

function isFlowNodeReferenced(event: StudioEvent, nodeId: string): boolean {
  return event.initial_stage_id === nodeId || (event.stages ?? []).some((node) =>
    node.stage_id !== nodeId && flowTargets(node).includes(nodeId),
  );
}

function renameFlowNode(event: StudioEvent, oldId: string, nextId: string) {
  const node = event.stages?.find((item) => item.stage_id === oldId);
  if (!node) return;
  node.stage_id = nextId;
  if (event.initial_stage_id === oldId) event.initial_stage_id = nextId;
  for (const stage of event.stages ?? []) {
    for (const choice of stage.actions) {
      for (const effect of choice.effects ?? []) {
        if (effect.type === "goto_node" && effect.node_id === oldId) effect.node_id = nextId;
      }
      if (choice.next_stage_id === oldId) choice.next_stage_id = nextId;
    }
  }
}

function duplicateFlowNode(draft: StudioDraft, eventIndex: number, nodeIndex: number) {
  const event = draft.events.events[eventIndex];
  const source = event.stages?.[nodeIndex];
  if (!source || !event.stages) return;
  const suffix = nextNumber(event.stages.map((node) => node.stage_id), `${source.stage_id}_copy_`);
  const copy = clone(source);
  copy.stage_id = `${source.stage_id}_copy_${suffix}`;
  copy.title = { en: `${source.title.en} copy`, "zh-CN": `${source.title["zh-CN"]} copy` };
  event.stages.splice(nodeIndex + 1, 0, copy);
}

function duplicateFlowChoice(draft: StudioDraft, eventIndex: number, nodeIndex: number, choiceIndex: number) {
  const actions = draft.events.events[eventIndex].stages?.[nodeIndex].actions;
  if (!actions) return;
  const source = actions[choiceIndex];
  const number = nextNumber(actions.map((choice) => choice.action_id), `${source.action_id}_copy_`);
  const copy = clone(source);
  copy.action_id = `${source.action_id}_copy_${number}`;
  actions.splice(choiceIndex + 1, 0, copy);
}

function defaultFlowEffect(type: StudioFlowEffect["type"], draft: StudioDraft, eventIndex: number): StudioFlowEffect {
  const currentEvent = draft.events.events[eventIndex];
  const anotherEvent = draft.events.events.find((_, index) => index !== eventIndex)?.event_id ?? "event_id";
  const resident = draft.residents.residents[0]?.agent_id ?? 1;
  const location = draft.locations.locations[0]?.location_id ?? "location_id";
  const node = currentEvent.stages?.[0]?.stage_id ?? "node_id";
  if (type === "advance_time") return { type, minutes: 5 };
  if (type === "goto_node") return { type, node_id: node };
  if (type === "complete_flow") return { type, outcome_code: "completed" };
  if (type === "start_event") return { type, event_id: anotherEvent };
  if (type === "schedule_event") return { type, event_id: anotherEvent, delay_minutes: 30 };
  if (type === "set_flag") return { type, flag_id: "new_flag", value: true };
  if (type === "goal_update") return { type, goal: { goal_id: "new_goal", status: "active" } };
  if (type === "relationship_delta") return { type, target_agent_id: resident, warmth_delta: 1 };
  if (type === "add_memory") return { type, owner_agent_id: resident, text: { en: "A new memory", "zh-CN": "A new memory" }, tags: [] };
  if (type === "move_participant") return { type, location_id: location };
  return { type: "show_message", text: { en: "New message", "zh-CN": "New message" } };
}

function replaceFlowEffect(draft: StudioDraft, eventIndex: number, nodeIndex: number, choiceIndex: number, effectIndex: number, type: StudioFlowEffect["type"]) {
  const choice = draft.events.events[eventIndex].stages![nodeIndex].actions[choiceIndex];
  const replacement = defaultFlowEffect(type, draft, eventIndex);
  if (["goto_node", "complete_flow", "start_event"].includes(type)) {
    choice.effects = (choice.effects ?? []).filter((effect, index) =>
      index === effectIndex || !["goto_node", "complete_flow", "start_event"].includes(effect.type),
    );
    effectIndex = Math.min(effectIndex, choice.effects.length - 1);
  }
  choice.effects ??= [];
  choice.effects[effectIndex] = replacement;
  syncFlowChoice(choice);
}

function syncFlowChoice(choice: StudioFlowChoice) {
  const effects = choice.effects ?? [];
  const time = effects.find((effect): effect is Extract<StudioFlowEffect, { type: "advance_time" }> => effect.type === "advance_time");
  const control = effects.find((effect) => ["goto_node", "complete_flow", "start_event"].includes(effect.type));
  choice.action_minutes = time?.minutes ?? 0;
  if (control?.type === "goto_node") {
    choice.terminal = false;
    choice.next_stage_id = control.node_id;
    choice.outcome_code = "continued";
  } else {
    choice.terminal = true;
    delete choice.next_stage_id;
    choice.outcome_code = control?.type === "complete_flow" ? control.outcome_code : "started_event";
  }
}

function withNewVersions(source: StudioDraft): StudioDraft {
  const draft = clone(source);
  const suffix = `studio-${Date.now().toString(36)}`;
  draft.manifest.content_pack_version = `${suffix}-content-v1`;
  draft.manifest.world_version = `${suffix}-world-v1`;
  draft.manifest.event_pack_version = `${suffix}-events-v1`;
  draft.map.version = `${suffix}-map-v1`;
  if (draft.visuals) draft.visuals.visual_version = `${suffix}-visuals-v1`;
  draft.locations.locations.forEach((item) => { item.version = draft.manifest.world_version; });
  draft.events.events.forEach((item) => { item.version = draft.manifest.event_pack_version; });
  return draft;
}

async function importStudioZip(file: File) {
  if (file.size > 26_000_000) throw new Error("ZIP exceeds the 26 MB Studio import limit.");
  const entries = await readZipEntries(await file.arrayBuffer());
  const manifestBytes = entries.get("manifest.json");
  if (!manifestBytes) throw new Error("ZIP is missing manifest.json.");
  const manifest = parseZipJson(manifestBytes, "manifest.json") as StudioDraft["manifest"];
  const requiredNames = new Set(["manifest.json", ...Object.values(manifest.files)]);
  const document = (key: keyof StudioManifestFiles) => {
    const name = manifest.files[key];
    const bytes = name ? entries.get(name) : undefined;
    if (!name || !bytes) throw new Error(`ZIP is missing ${name ?? key}.`);
    return parseZipJson(bytes, name);
  };
  const draft: StudioDraft = {
    manifest,
    map: document("map") as StudioDraft["map"],
    locations: document("locations") as StudioDraft["locations"],
    residents: document("residents") as StudioDraft["residents"],
    events: document("events") as StudioDraft["events"],
  };
  if (["content-pack-v2", "content-pack-v3", "content-pack-v4", "content-pack-v5"].includes(manifest.schema_version)) {
    draft.visuals = document("visuals") as NonNullable<StudioDraft["visuals"]>;
  }
  if (["content-pack-v4", "content-pack-v5"].includes(manifest.schema_version)) {
    draft.systems = document("systems") as NonNullable<StudioDraft["systems"]>;
  }
  const importedFiles: Record<string, File> = {};
  for (const asset of draft.visuals?.visual_assets ?? []) {
    requiredNames.add(asset.file_name);
    const bytes = entries.get(asset.file_name);
    if (!bytes) throw new Error(`ZIP is missing visual asset ${asset.file_name}.`);
    const assetBuffer = bytes.buffer.slice(
      bytes.byteOffset,
      bytes.byteOffset + bytes.byteLength,
    ) as ArrayBuffer;
    const imported = new File([assetBuffer], asset.file_name.split("/").at(-1) ?? "asset", { type: asset.mime_type });
    if (await sha256Hex(imported) !== asset.sha256) throw new Error(`Hash mismatch for ${asset.file_name}.`);
    const bitmap = await createImageBitmap(imported).catch(() => null);
    if (!bitmap) throw new Error(`Could not decode ${asset.file_name}.`);
    const dimensionsMatch = bitmap.width === asset.width && bitmap.height === asset.height;
    bitmap.close();
    if (!dimensionsMatch) throw new Error(`Dimension mismatch for ${asset.file_name}.`);
    importedFiles[asset.asset_key] = imported;
  }
  const extras = Array.from(entries.keys()).filter((name) => !requiredNames.has(name));
  if (extras.length) throw new Error(`ZIP contains undeclared entries: ${extras.join(", ")}.`);
  const assetFiles = Object.fromEntries(Object.entries(importedFiles).map(([key, blob]) => [
    key,
    { blob, previewUrl: URL.createObjectURL(blob) },
  ]));
  return { draft, assetFiles };
}

type StudioManifestFiles = {
  map: string;
  locations: string;
  residents: string;
  events: string;
  visuals: string;
  systems: string;
};

function parseZipJson(bytes: Uint8Array, name: string) {
  if (bytes.byteLength > 1_000_000) throw new Error(`${name} exceeds the JSON size limit.`);
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown;
  } catch {
    throw new Error(`${name} is not valid UTF-8 JSON.`);
  }
}

async function readZipEntries(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer);
  const view = new DataView(buffer);
  const minimum = Math.max(0, bytes.length - 65_557);
  let eocd = -1;
  for (let offset = bytes.length - 22; offset >= minimum; offset -= 1) {
    if (view.getUint32(offset, true) === 0x06054b50) { eocd = offset; break; }
  }
  if (eocd < 0) throw new Error("ZIP end record was not found.");
  const entryCount = view.getUint16(eocd + 10, true);
  const centralSize = view.getUint32(eocd + 12, true);
  const centralOffset = view.getUint32(eocd + 16, true);
  if (entryCount > 65 || centralOffset + centralSize > eocd) throw new Error("ZIP directory is invalid or too large.");
  const result = new Map<string, Uint8Array>();
  let offset = centralOffset;
  let totalSize = 0;
  for (let index = 0; index < entryCount; index += 1) {
    if (offset + 46 > bytes.length || view.getUint32(offset, true) !== 0x02014b50) throw new Error("ZIP central directory is malformed.");
    const flags = view.getUint16(offset + 8, true);
    const method = view.getUint16(offset + 10, true);
    const compressedSize = view.getUint32(offset + 20, true);
    const uncompressedSize = view.getUint32(offset + 24, true);
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const localOffset = view.getUint32(offset + 42, true);
    if (flags & 1 || ![0, 8].includes(method) || compressedSize === 0xffffffff || uncompressedSize === 0xffffffff) throw new Error("Encrypted, ZIP64, or unsupported ZIP entries are not allowed.");
    const name = new TextDecoder("utf-8", { fatal: true }).decode(bytes.slice(offset + 46, offset + 46 + nameLength));
    if (!name || name.startsWith("/") || name.includes("\\") || name.split("/").some((part) => !part || part === "." || part === "..")) throw new Error("ZIP contains an unsafe entry path.");
    if (result.has(name)) throw new Error(`ZIP contains duplicate entry ${name}.`);
    if (localOffset + 30 > bytes.length || view.getUint32(localOffset, true) !== 0x04034b50) throw new Error("ZIP local header is malformed.");
    const localNameLength = view.getUint16(localOffset + 26, true);
    const localExtraLength = view.getUint16(localOffset + 28, true);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    if (dataStart + compressedSize > bytes.length) throw new Error("ZIP entry data is truncated.");
    const compressed = bytes.slice(dataStart, dataStart + compressedSize);
    let uncompressed: Uint8Array;
    if (method === 0) uncompressed = compressed;
    else {
      const compressedBuffer = compressed.buffer.slice(
        compressed.byteOffset,
        compressed.byteOffset + compressed.byteLength,
      ) as ArrayBuffer;
      const stream = new Blob([compressedBuffer]).stream().pipeThrough(new DecompressionStream("deflate-raw" as CompressionFormat));
      uncompressed = new Uint8Array(await new Response(stream).arrayBuffer());
    }
    if (uncompressed.byteLength !== uncompressedSize) throw new Error(`ZIP size mismatch for ${name}.`);
    totalSize += uncompressed.byteLength;
    if (totalSize > 26_000_000) throw new Error("Uncompressed ZIP content exceeds 26 MB.");
    result.set(name, uncompressed);
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return result;
}

function localAssetBlobs(files: Record<string, LocalAssetFile>) {
  return Object.fromEntries(Object.entries(files).map(([key, item]) => [key, item.blob]));
}

async function sha256Hex(blob: Blob) {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function paletteClass(key: string) {
  return ({
    ocean_teal: "from-cyan-800 to-teal-500",
    sand_warm: "from-amber-700 to-orange-300",
    forest_green: "from-emerald-900 to-lime-500",
    harbor_blue: "from-blue-900 to-sky-400",
    sunset_rose: "from-rose-800 to-orange-300",
    neutral_stone: "from-stone-800 to-stone-400",
  } as Record<string, string>)[key] ?? "from-stone-800 to-stone-400";
}

function studioWorldVisuals(
  draft: StudioDraft,
  assetFiles: Record<string, LocalAssetFile>,
): WorldVisuals | null {
  if (!draft.visuals) return null;
  return {
    visual_version: draft.visuals.visual_version,
    slots: Object.fromEntries(draft.visuals.visual_slots.map((slot) => {
      const asset = draft.visuals!.visual_assets.find((item) => item.asset_key === slot.asset_key);
      const url = asset ? assetFiles[asset.asset_key]?.previewUrl ?? draft.asset_urls?.[asset.asset_key] : undefined;
      return [slot.slot_id, {
        ...slot,
        fallback_title: slot.fallback_title.en,
        fallback_description: slot.fallback_description.en,
        asset: asset && url ? { ...asset, url } : null,
      }];
    })),
  };
}

function worldLocations(draft: StudioDraft): WorldLocation[] { return draft.locations.locations.map(worldLocation); }
function worldLocation(item: StudioLocation): WorldLocation { return { location_id: item.location_id, name: item.name.en, name_zh_cn: item.name["zh-CN"], description: item.description.en, description_zh_cn: item.description["zh-CN"], scene_type: item.scene_type, connected_location_ids: item.connected_location_ids, interaction_points: worldInteractionPoints(item), allowed_actions: item.allowed_actions as WorldLocation["allowed_actions"] }; }
function worldInteractionPoints(item: StudioLocation): WorldInteractionPoint[] { return item.interaction_points.map((point) => ({ object_id: point.object_id, type: point.type, name: point.name, description: point.description, renderer_key: point.renderer_key })); }
function worldEvent(item: StudioEvent): WorldEvent {
  const stage = item.stages?.find((candidate) => candidate.stage_id === item.initial_stage_id) ?? item.stages?.[0];
  return {
    event_instance_id: item.event_id,
    event_type: item.event_type,
    version: item.version,
    renderer_key: item.renderer_key,
    title: stage?.title.en ?? item.title.en,
    title_zh_cn: stage?.title["zh-CN"] ?? item.title["zh-CN"],
    stimulus_text: stage?.stimulus.en ?? item.stimulus.en,
    stimulus_text_zh_cn: stage?.stimulus["zh-CN"] ?? item.stimulus["zh-CN"],
    actions: stage
      ? stage.actions.map((action) => ({
          action_id: action.action_id,
          label: action.label.en,
          label_zh_cn: action.label["zh-CN"],
          requires_text: action.requires_text,
          kind: action.action_type,
          target_object_id: action.target_id,
          metadata: action.metadata,
        }))
      : item.actions.map((action) => ({ action_id: action.action_id, label: action.label.en, label_zh_cn: action.label["zh-CN"], requires_text: action.requires_text })),
    metadata: stage ? { behavioral_event: true, stage_id: stage.stage_id } : undefined,
  };
}
function nextNumber(values: string[], prefix: string) { let number = 1; while (values.includes(`${prefix}${number}`)) number += 1; return number; }
function csv(value: string) { return value.split(",").map((item) => item.trim()).filter(Boolean); }
function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T; }
function errorMessage(error: unknown) { return error instanceof Error ? error.message : "Unexpected Content Studio error"; }
