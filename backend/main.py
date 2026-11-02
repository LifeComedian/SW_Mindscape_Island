import asyncio
import csv
from email import policy
from email.parser import BytesParser
import io
import json
import os
import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy.orm import Session as DBSession

import schemas
from agents import AgentRequest, AgentService
from agents.safety import check_user_comment_safety
from content.validator import ContentPackValidationError
from content.loader import read_builtin_visual_asset
from content.visual_assets import MAX_TOTAL_IMAGE_BYTES, MAX_VISUAL_ASSETS
from database import Base, SessionLocal, engine, upgrade_database_schema
from feature_extractor import extract_session_features
from models import CommunityActivity, Interaction, Session as UserSession, WorldState
from services.agent_service import (
    get_static_agent,
    get_static_agents,
    get_static_posts,
)
from services.scoring_service import PrototypeScorer
from services.simulation_service import (
    SimulationStateError,
    advance_day,
    build_feed_state,
    create_user_post,
    get_agent_memory,
    get_session_post,
    initialize_simulation,
    list_agent_memories,
    mark_notification_read,
    next_user_post_sequence,
    remember_user_interaction,
    select_user_post_activity_agents,
    week_start_for,
)
from services.world_service import (
    WorldStateError,
    build_island_export,
    build_world_payload,
    create_world_conversation,
    ensure_session_can_finish,
    initialize_world,
    list_locations,
    perform_world_action,
    session_write_lock,
    start_world_conversation,
)
from services.atomic_action_service import (
    AtomicActionServiceError,
    execute_atomic_action,
    list_atomic_action_candidates,
)
from services.plan_service import (
    PlanServiceError,
    create_plan,
    list_plans,
    query_plan_availability,
    transition_plan,
)
from services.phone_plan_service import (
    PhonePlanError,
    create_phone_invitation,
    list_actor_knowledge,
    list_phone_posts,
    propose_phone_plan_variant,
    publish_activity_record,
    consent_phone_plan_variant,
    respond_to_phone_invitation,
    view_phone_post,
)
from services.emergence_director_service import (
    EmergenceDirectorError,
    evaluate_emergence,
    list_emergence_state,
    transition_emergent_event,
)
from services.behavioral_event_analytics import build_behavioral_event_records
from services.stage_service import StageServiceError, list_stage_cards, transition_stage, view_stage_fact, list_visible_stage_facts
from services.decision_gateway_service import DecisionGatewayError, decide_resident, server_decision_provider
from services.world_simulation_service import (
    finalize_world_pulse_interactions,
    process_world_pulse,
    set_world_simulation_mode,
)
from services.resident_social_service import (
    ResidentSocialError,
    process_resident_social_tick,
)
from services.interaction_prompt_service import (
    InteractionPromptError,
    invalidate_pending_interaction_prompts,
    respond_to_interaction_prompt,
)
from services.social_world_service import (
    find_post_by_idempotency_key,
    publish_participant_post,
)
from services.content_studio_service import (
    audit_studio_draft,
    export_studio_draft,
    list_installed_packs,
    read_installed_pack,
    require_content_studio,
    validate_studio_draft,
)
from services.development_world_service import (
    development_world_options,
    require_development_world_selector,
    validate_development_world_selection,
)
from study.api import router as study_router
from study.models import StudySession
from study.access_guard import StudyAccessGuard
from services.player_record_service import WorldPlayerRecord  # Register additive table before create_all.


from study.reviewer import assert_isolated_database, router as review_router
assert_isolated_database()
Base.metadata.create_all(bind=engine)
upgrade_database_schema()
if os.getenv('STUDY_RUNTIME_ENV') == 'production' and os.getenv('STUDY_PROTOCOL_VERSION') == 'experience-workflow-20261021-v1':
    from study.research_admin import storage_root, reconcile_restored_database
    with SessionLocal() as restored_db:
        reconcile_restored_database(restored_db, storage_root())
from services.holiday_usability_migration import retire_rope, retire_volley_match
with SessionLocal() as migration_db:
    retire_rope(migration_db)
    retire_volley_match(migration_db)
    migration_db.commit()

app = FastAPI(title="MindScape Island Research Prototype API")
app.include_router(study_router)
app.include_router(review_router)
app.add_middleware(StudyAccessGuard)
agent_service = AgentService()
prototype_scorer = PrototypeScorer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=list({"http://localhost:3000", "http://127.0.0.1:3000", os.getenv("STUDY_PUBLIC_ORIGIN", "http://127.0.0.1:3000").rstrip("/")}),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


def utc_now() -> datetime:
    return datetime.utcnow()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
def root():
    return {"message": "MindScape Island research prototype backend is running."}


@app.get("/studio-api/packs")
def get_content_studio_packs(request: Request):
    require_content_studio(request)
    return {"packs": list_installed_packs()}


@app.get("/studio-api/packs/{directory_name}")
def get_content_studio_pack(directory_name: str, request: Request):
    require_content_studio(request)
    try:
        return read_installed_pack(directory_name)
    except (ContentPackValidationError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Content pack not found") from exc


@app.post("/studio-api/audit")
async def audit_content_studio_draft(request: Request, seed: int = 7,
                                    response: str = "accept", public_consent: bool = False):
    require_content_studio(request)
    draft = await _parse_content_studio_draft(request)
    return audit_studio_draft(draft.model_dump(), seed=seed, response=response,
                             public_consent=public_consent)


@app.post("/studio-api/validate")
async def validate_content_studio_draft(request: Request):
    require_content_studio(request)
    draft = await _parse_content_studio_draft(request)
    return validate_studio_draft(draft.model_dump())


@app.post("/studio-api/export")
async def export_content_studio_pack(request: Request):
    require_content_studio(request)
    draft = await _parse_content_studio_draft(request)
    archive, filename = export_studio_draft(draft.model_dump())
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/studio-api/v2/validate")
async def validate_content_studio_v2(request: Request):
    require_content_studio(request)
    draft, asset_blobs = await _parse_content_studio_v2_multipart(request)
    return validate_studio_draft(draft, asset_blobs)


@app.post("/studio-api/v2/export")
async def export_content_studio_v2(request: Request):
    require_content_studio(request)
    draft, asset_blobs = await _parse_content_studio_v2_multipart(request)
    archive, filename = export_studio_draft(draft, asset_blobs)
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/world-assets/{world_version}/{asset_key}")
def get_world_visual_asset(world_version: str, asset_key: str):
    try:
        data, mime_type, sha256 = read_builtin_visual_asset(world_version, asset_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Visual asset not found") from exc
    return Response(
        content=data,
        media_type=mime_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"sha256-{sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/development/world-options")
def get_development_world_options(request: Request):
    require_development_world_selector(request)
    return development_world_options()


async def _parse_content_studio_draft(request: Request) -> schemas.ContentStudioDraft:
    try:
        payload = await request.json()
        return schemas.ContentStudioDraft.model_validate(payload)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="A complete five-document Studio draft is required.") from exc


_STUDIO_MULTIPART_MAX_BYTES = MAX_TOTAL_IMAGE_BYTES + 6_000_000
_STUDIO_ASSET_FIELD_RE = re.compile(r"^asset:([A-Za-z0-9][A-Za-z0-9._-]{0,127})$")


async def _parse_content_studio_v2_multipart(
    request: Request,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data;"):
        raise HTTPException(status_code=415, detail="content-pack-v2 requires multipart/form-data.")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _STUDIO_MULTIPART_MAX_BYTES:
                raise HTTPException(status_code=413, detail="Studio upload is too large.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from exc
    body = await request.body()
    if len(body) > _STUDIO_MULTIPART_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Studio upload is too large.")
    try:
        encoded_content_type = content_type.encode("ascii", errors="strict")
    except UnicodeEncodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid Content-Type header.") from exc
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: "
        + encoded_content_type
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + body
    )
    if not message.is_multipart():
        raise HTTPException(status_code=422, detail="Malformed multipart Studio upload.")
    draft: dict[str, Any] | None = None
    asset_blobs: dict[str, bytes] = {}
    parts = list(message.iter_parts())
    if len(parts) > MAX_VISUAL_ASSETS + 1:
        raise HTTPException(status_code=413, detail="Studio upload contains too many parts.")
    for part in parts:
        if part.is_multipart():
            raise HTTPException(status_code=422, detail="Nested multipart uploads are not allowed.")
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True) or b""
        if name == "draft":
            if draft is not None:
                raise HTTPException(status_code=422, detail="Duplicate draft part.")
            if part.get_content_type() != "application/json":
                raise HTTPException(status_code=415, detail="The draft part must be application/json.")
            try:
                parsed = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=422, detail="The draft part is not valid UTF-8 JSON.") from exc
            if not isinstance(parsed, dict):
                raise HTTPException(status_code=422, detail="The draft part must be a JSON object.")
            draft = parsed
            continue
        match = _STUDIO_ASSET_FIELD_RE.fullmatch(name or "")
        if not match:
            raise HTTPException(status_code=422, detail="Unknown multipart field.")
        asset_key = match.group(1)
        if asset_key in asset_blobs:
            raise HTTPException(status_code=422, detail=f"Duplicate asset part: {asset_key}.")
        asset_blobs[asset_key] = payload
    if draft is None:
        raise HTTPException(status_code=422, detail="A draft JSON part is required.")
    return draft, asset_blobs


@app.post("/sessions", response_model=schemas.SessionResponse)
def create_session(
    session: schemas.SessionCreate,
    request: Request,
    db: DBSession = Depends(get_db),
):
    if not session.consent:
        raise HTTPException(status_code=400, detail="Consent is required to start a session.")

    user_alias = session.nickname.strip()
    if not user_alias:
        raise HTTPException(status_code=400, detail="Nickname is required.")

    selected_world_version = validate_development_world_selection(
        request,
        session.world_version,
    )

    started_at = utc_now()
    new_session = UserSession(
        nickname=user_alias,
        user_alias=user_alias,
        consent=session.consent,
        consent_version=session.consent_version,
        status="active",
        started_at=started_at,
        total_days=7,
        virtual_start_date=week_start_for(started_at.date()),
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    initialize_simulation(db, new_session)
    world = initialize_world(
        db,
        new_session,
        world_version=selected_world_version,
    )

    return {
        "session_id": new_session.id,
        "nickname": new_session.nickname,
        "user_alias": new_session.user_alias,
        "status": new_session.status,
        "current_day": new_session.current_day,
        "total_days": new_session.total_days,
        "simulation_seed": new_session.simulation_seed,
        "world_version": world.world_version,
    }


@app.get("/posts")
def get_posts():
    return get_static_posts()


@app.get("/agents")
def get_agents():
    return get_static_agents()


@app.get("/locations")
def get_island_locations():
    return list_locations()


@app.get("/sessions/{session_id}/world")
def get_island_world(
    session_id: int,
    language: schemas.LanguageCode = Query("en"),
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    try:
        return build_world_payload(db, session, language)
    except WorldStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/sessions/{session_id}/behavioral-events")
def get_behavioral_event_timeline(
    session_id: int,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    return {
        "session_id": session_id,
        "records": build_behavioral_event_records(db, session),
    }


@app.get("/sessions/{session_id}/world/narratives")
def get_world_narratives(session_id: int, db: DBSession = Depends(get_db)):
    _get_session_or_404(db, session_id)
    from services.narrative_service import project_narratives
    try:
        return project_narratives(db, session_id=session_id)
    except PlanServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/sessions/{session_id}/island/pulse")
async def create_island_simulation_pulse(
    session_id: int,
    request: schemas.WorldPulseRequest,
    db: DBSession = Depends(get_db),
):
    try:
        result = process_world_pulse(db, session_id=session_id, request=request)
        original_status = (
            result.get("original_status")
            if result.get("status") == "duplicate"
            else result.get("status")
        )
        if original_status == "accepted":
            result = await finalize_world_pulse_interactions(
                db,
                session_id=session_id,
                pulse_id=int(result["pulse"]["pulse_id"]),
                language=request.language,
                agent_service=agent_service,
                response_status=str(result["status"]),
            )
        from services.autonomous_world_service import dispatch_autonomy
        result["autonomy"] = dispatch_autonomy(db, session_id=session_id, language=request.language)
        return result
    except WorldStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ResidentSocialError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/sessions/{session_id}/island/simulation")
def update_island_simulation_mode(
    session_id: int,
    request: schemas.WorldSimulationControlRequest,
    db: DBSession = Depends(get_db),
):
    try:
        return set_world_simulation_mode(db, session_id=session_id, request=request)
    except WorldStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/sessions/{session_id}/world/actions")
async def create_island_world_action(
    session_id: int,
    request: schemas.WorldActionRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        result = perform_world_action(db, session, request)
        if request.action_type != "end_conversation":
            await process_resident_social_tick(
                db,
                session_id=session_id,
                trigger_action_id=int(result["action_id"]),
                language=request.language,
                agent_service=agent_service,
            )
        db.rollback()
        refreshed_session = _get_session_or_404(db, session_id)
        result["world"] = build_world_payload(db, refreshed_session, request.language)
        return result
    except WorldStateError as exc:
        detail = {'message': exc.detail, 'reason_code': exc.reason_code} if exc.reason_code else exc.detail
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    except ResidentSocialError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/sessions/{session_id}/world/atomic-actions")
def get_island_atomic_actions(
    session_id: int,
    include_blocked: bool = Query(False),
    db: DBSession = Depends(get_db),
):
    _get_session_or_404(db, session_id)
    try:
        return list_atomic_action_candidates(
            db,
            session_id=session_id,
            include_blocked=include_blocked,
        )
    except AtomicActionServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.detail, "reason_code": exc.reason_code},
        ) from exc


@app.post("/sessions/{session_id}/world/atomic-actions")
def create_island_atomic_action(
    session_id: int,
    request: schemas.AtomicActionRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        result = execute_atomic_action(
            db,
            session_id=session_id,
            request=request,
        )
        db.rollback()
        refreshed_session = _get_session_or_404(db, session_id)
        result["world"] = build_world_payload(
            db,
            refreshed_session,
            request.language,
        )
        return result
    except AtomicActionServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.detail, "reason_code": exc.reason_code},
        ) from exc


@app.get("/sessions/{session_id}/world/plans")
def get_island_plans(
    session_id: int,
    include_terminal: bool = Query(True),
    db: DBSession = Depends(get_db),
):
    _get_session_or_404(db, session_id)
    try:
        return list_plans(
            db,
            session_id=session_id,
            include_terminal=include_terminal,
        )
    except PlanServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.detail, "reason_code": exc.reason_code},
        ) from exc


@app.post("/sessions/{session_id}/world/plans/availability")
def check_island_plan_availability(
    session_id: int,
    request: schemas.PlanAvailabilityRequest,
    db: DBSession = Depends(get_db),
):
    _get_session_or_404(db, session_id)
    try:
        return query_plan_availability(db, session_id=session_id, request=request)
    except PlanServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.detail, "reason_code": exc.reason_code},
        ) from exc


@app.post("/sessions/{session_id}/world/plans")
def create_island_plan(
    session_id: int,
    request: schemas.WorldPlanCreateRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        return create_plan(db, session_id=session_id, request=request)
    except PlanServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.detail, "reason_code": exc.reason_code},
        ) from exc


@app.post("/sessions/{session_id}/world/plans/{commitment_id}/transitions")
def transition_island_plan(
    session_id: int,
    commitment_id: int,
    request: schemas.WorldPlanTransitionRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        return transition_plan(
            db,
            session_id=session_id,
            commitment_id=commitment_id,
            request=request,
        )
    except PlanServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.detail, "reason_code": exc.reason_code},
        ) from exc


def _raise_phone_plan_http(exc: PhonePlanError | PlanServiceError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"message": exc.detail, "reason_code": exc.reason_code},
    ) from exc


def _raise_emergence_http(exc: EmergenceDirectorError | PhonePlanError | PlanServiceError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"message": exc.detail, "reason_code": exc.reason_code},
    ) from exc


@app.get("/sessions/{session_id}/world/emergence")
def get_world_emergence_state(
    session_id: int,
    db: DBSession = Depends(get_db),
):
    _get_session_or_404(db, session_id)
    try:
        return list_emergence_state(db, session_id=session_id)
    except (EmergenceDirectorError, PhonePlanError, PlanServiceError) as exc:
        _raise_emergence_http(exc)


@app.post("/sessions/{session_id}/world/emergence/evaluations")
def create_world_emergence_evaluation(
    session_id: int,
    request: schemas.EmergenceEvaluationRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        return evaluate_emergence(db, session_id=session_id, request=request)
    except (EmergenceDirectorError, PhonePlanError, PlanServiceError) as exc:
        _raise_emergence_http(exc)


@app.post("/sessions/{session_id}/world/emergence/events/{runtime_id}/transitions")
def update_world_emergent_event(
    session_id: int,
    runtime_id: int,
    request: schemas.EmergentEventTransitionRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        return transition_emergent_event(
            db,
            session_id=session_id,
            runtime_id=runtime_id,
            request=request,
        )
    except (EmergenceDirectorError, PhonePlanError, PlanServiceError) as exc:
        _raise_emergence_http(exc)


@app.post("/sessions/{session_id}/world/development/residents/{agent_id}/decisions")
async def development_resident_decision(session_id: int, agent_id: int, body: schemas.ResidentDecisionRequest,
                                       request: Request, db: DBSession = Depends(get_db)):
    require_development_world_selector(request)
    _ensure_active_session(_get_session_or_404(db, session_id))
    try:
        return await decide_resident(db, session_id=session_id, agent_id=agent_id, decision_type=body.decision_type,
                                     idempotency_key=body.idempotency_key, language=body.language, provider=server_decision_provider(), execution_mode=body.execution_mode)
    except (DecisionGatewayError, PlanServiceError, StageServiceError, AtomicActionServiceError) as exc:
        _raise_emergence_http(exc)


@app.post("/sessions/{session_id}/world/development/residents/{agent_id}/decision-previews/{audit_id}/commit")
async def commit_resident_preview(session_id: int, agent_id: int, audit_id: int, body: schemas.ShadowDecisionCommitRequest,
                                  request: Request, db: DBSession = Depends(get_db)):
    require_development_world_selector(request)
    from services.decision_gateway_service import apply_shadow_decision
    try:
        return await apply_shadow_decision(db, session_id=session_id, agent_id=agent_id, audit_id=audit_id,
            idempotency_key=body.idempotency_key, language=body.language)
    except (DecisionGatewayError, PlanServiceError, StageServiceError, AtomicActionServiceError) as exc:
        _raise_emergence_http(exc)


@app.get("/sessions/{session_id}/world/stages")
def get_world_stages(session_id: int, db: DBSession = Depends(get_db)):
    _get_session_or_404(db, session_id)
    try:
        return list_stage_cards(db, session_id=session_id)
    except (StageServiceError, PlanServiceError) as exc:
        _raise_emergence_http(exc)


@app.get('/sessions/{session_id}/world/activity-experience')
def get_activity_experience(session_id: int, db: DBSession = Depends(get_db)):
    _get_session_or_404(db, session_id)
    from services.activity_experience_service import current
    return current(db, session_id)


@app.get('/sessions/{session_id}/world/object-experience')
def get_object_experience(session_id: int, db: DBSession = Depends(get_db)):
    _ensure_active_session(_get_session_or_404(db, session_id))
    from services.holiday_object_service import read
    return read(db, session_id)


@app.get('/sessions/{session_id}/world/holiday-guides')
def get_holiday_guides(session_id: int, db: DBSession = Depends(get_db)):
    _get_session_or_404(db, session_id)
    from services.holiday_guide_service import guides
    return guides(db, session_id)


@app.post('/sessions/{session_id}/world/holiday-phone-open')
def holiday_phone_open(session_id: int, db: DBSession = Depends(get_db)):
    _ensure_active_session(_get_session_or_404(db, session_id))
    from services.holiday_guide_service import phone_open
    return phone_open(db, session_id)


@app.post('/sessions/{session_id}/world/activity-experience/{runtime_id}')
async def update_activity_experience(session_id: int, runtime_id: int, request: schemas.ActivityExperienceRequest, db: DBSession = Depends(get_db)):
    _ensure_active_session(_get_session_or_404(db, session_id))
    from services.activity_experience_service import step
    try:
        return await step(db, session_id, runtime_id, request.model_dump())
    except (StageServiceError, PlanServiceError, AtomicActionServiceError) as exc:
        _raise_emergence_http(exc)


@app.post("/sessions/{session_id}/world/emergence/events/{runtime_id}/stage-actions")
async def create_stage_action(session_id: int, runtime_id: int, request: schemas.StageTransitionRequest, db: DBSession = Depends(get_db)):
    _ensure_active_session(_get_session_or_404(db, session_id))
    try:
        if request.operation == "discuss":
            from services.activity_discussion_service import discuss
            return await discuss(db, session_id=session_id, runtime_id=runtime_id, request=request)
        result = transition_stage(db, session_id=session_id, runtime_id=runtime_id, request=request)
        _dispatch_focused_residents(db, session_id, request.language)
        return result
    except (StageServiceError, PlanServiceError, AtomicActionServiceError) as exc:
        _raise_emergence_http(exc)


@app.post("/sessions/{session_id}/world/stage-facts/{fact_id}/view")
def acquire_stage_fact(session_id: int, fact_id: int, db: DBSession = Depends(get_db)):
    _ensure_active_session(_get_session_or_404(db, session_id))
    try:
        return view_stage_fact(db, session_id=session_id, fact_id=fact_id)
    except (StageServiceError, PlanServiceError, AtomicActionServiceError) as exc:
        _raise_emergence_http(exc)


@app.get("/sessions/{session_id}/world/stage-facts")
def get_visible_stage_facts(session_id: int, db: DBSession = Depends(get_db)):
    _get_session_or_404(db, session_id)
    try:
        return list_visible_stage_facts(db, session_id=session_id)
    except (StageServiceError, PlanServiceError) as exc:
        _raise_emergence_http(exc)


@app.get("/sessions/{session_id}/world/phone")
def get_world_phone(
    session_id: int,
    db: DBSession = Depends(get_db),
):
    _get_session_or_404(db, session_id)
    try:
        return list_phone_posts(db, session_id=session_id)
    except (PhonePlanError, PlanServiceError) as exc:
        _raise_phone_plan_http(exc)


@app.get("/sessions/{session_id}/world/activity-catalog")
def get_world_activity_catalog(session_id: int, db: DBSession = Depends(get_db)):
    _get_session_or_404(db, session_id)
    from services.player_activity_service import catalog
    try:
        return catalog(db, session_id=session_id)
    except PlanServiceError as exc:
        _raise_phone_plan_http(exc)


@app.get("/sessions/{session_id}/world/player-records")
def get_player_records(session_id: int, db: DBSession = Depends(get_db)):
    _get_session_or_404(db, session_id)
    from services.player_record_service import list_records
    try:
        return list_records(db, session_id=session_id)
    except PlanServiceError as exc:
        _raise_phone_plan_http(exc)


@app.get("/sessions/{session_id}/world/day-review")
def get_day_review(session_id: int, day: int | None = None, language: str = "zh-CN", db: DBSession = Depends(get_db)):
    _get_session_or_404(db, session_id)
    from services.day_review_service import review
    try:
        return review(db, session_id=session_id, day=day, language=language)
    except PlanServiceError as exc:
        _raise_phone_plan_http(exc)


@app.get("/sessions/{session_id}/world/phone/knowledge")
def get_world_phone_knowledge(
    session_id: int,
    db: DBSession = Depends(get_db),
):
    _get_session_or_404(db, session_id)
    try:
        return list_actor_knowledge(db, session_id=session_id)
    except (PhonePlanError, PlanServiceError) as exc:
        _raise_phone_plan_http(exc)


@app.post("/sessions/{session_id}/world/phone/invitations")
async def create_world_phone_invitation(
    session_id: int,
    request: schemas.PhoneInvitationCreateRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    _ensure_world_ui_available(db, session_id)
    try:
        result = create_phone_invitation(db, session_id=session_id, request=request)
        from services.autonomous_world_service import dispatch_autonomy
        dispatch_autonomy(db, session_id=session_id, language=request.language)
        return result
    except (PhonePlanError, PlanServiceError) as exc:
        _raise_phone_plan_http(exc)


@app.post("/sessions/{session_id}/world/phone/posts/{post_id}/view")
def mark_world_phone_post_viewed(
    session_id: int,
    post_id: int,
    request: schemas.PhonePostViewRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        return view_phone_post(
            db,
            session_id=session_id,
            feed_post_id=post_id,
            request=request,
        )
    except (PhonePlanError, PlanServiceError) as exc:
        _raise_phone_plan_http(exc)


@app.post("/sessions/{session_id}/world/phone/invitations/{post_id}/responses")
def respond_world_phone_invitation(
    session_id: int,
    post_id: int,
    request: schemas.PhoneInvitationResponseRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        return respond_to_phone_invitation(
            db,
            session_id=session_id,
            feed_post_id=post_id,
            request=request,
        )
    except (PhonePlanError, PlanServiceError) as exc:
        _raise_phone_plan_http(exc)


@app.post("/sessions/{session_id}/world/phone/plans/{commitment_id}/records")
def create_world_phone_activity_record(
    session_id: int,
    commitment_id: int,
    request: schemas.PhoneActivityRecordRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        return publish_activity_record(
            db,
            session_id=session_id,
            commitment_id=commitment_id,
            request=request,
        )
    except (PhonePlanError, PlanServiceError) as exc:
        _raise_phone_plan_http(exc)


@app.post("/sessions/{session_id}/world/phone/plans/{commitment_id}/variant-proposals")
def propose_world_phone_plan_variant(
    session_id: int,
    commitment_id: int,
    request: schemas.PhoneVariantProposalRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        return propose_phone_plan_variant(
            db,
            session_id=session_id,
            commitment_id=commitment_id,
            request=request,
        )
    except (PhonePlanError, PlanServiceError) as exc:
        _raise_phone_plan_http(exc)


@app.post("/sessions/{session_id}/world/phone/variant-proposals/{proposal_id}/consents")
def consent_world_phone_plan_variant(
    session_id: int,
    proposal_id: int,
    request: schemas.PhoneVariantConsentRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        return consent_phone_plan_variant(
            db,
            session_id=session_id,
            proposal_id=proposal_id,
            request=request,
        )
    except (PhonePlanError, PlanServiceError) as exc:
        _raise_phone_plan_http(exc)


@app.post("/sessions/{session_id}/world/conversations")
async def create_island_conversation(
    session_id: int,
    request: schemas.WorldConversationRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        result = await create_world_conversation(db, session, request, agent_service)
        # Pause resident social activity during participant conversations.
        db.rollback()
        refreshed_session = _get_session_or_404(db, session_id)
        result["world"] = build_world_payload(db, refreshed_session, request.language)
        return result
    except WorldStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ResidentSocialError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/sessions/{session_id}/world/conversations/start")
def start_island_conversation(
    session_id: int,
    request: schemas.WorldConversationStartRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    try:
        return start_world_conversation(db, session, request)
    except WorldStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/sessions/{session_id}/world/interaction-focus")
async def interaction_focus(session_id: int, request: schemas.InteractionFocusRequest, db: DBSession = Depends(get_db)):
    from services.interaction_time_service import change_focus
    try:
        result = change_focus(db, session_id=session_id, request=request)
        _dispatch_focused_residents(db, session_id)
        return result
    except WorldStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _dispatch_focused_residents(db, session_id, language="en"):
    """Focused replies need a wake-up while the foreground clock is paused."""
    from services.interaction_time_service import focus_state
    from models import WorldState, WorldEventStage
    world = db.query(WorldState).filter_by(session_id=session_id).first()
    focus = focus_state(world) if world else None
    if focus:
        stage = db.query(WorldEventStage).filter_by(session_id=session_id, runtime_id=focus["runtime_id"]).first()
        if stage:
            from services.stage_service import _card, _state
            if _state(stage).get("proposal") or _card(stage)["kind"] == "closure":
                from services.autonomous_world_service import dispatch_autonomy
                dispatch_autonomy(db, session_id=session_id, language=language, factory=SessionLocal)


@app.post("/sessions/{session_id}/world/interaction-prompts/{prompt_id}/response")
def respond_to_island_interaction_prompt(
    session_id: int,
    prompt_id: int,
    request: schemas.WorldInteractionPromptResponseRequest,
    db: DBSession = Depends(get_db),
):
    try:
        return respond_to_interaction_prompt(
            db,
            session_id=session_id,
            prompt_id=prompt_id,
            request=request,
        )
    except InteractionPromptError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/sessions/{session_id}/feed")
def get_session_feed(
    session_id: int,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    state = build_feed_state(db, session)
    interactions = (
        db.query(Interaction)
        .filter(Interaction.session_id == session_id)
        .order_by(Interaction.created_at.asc(), Interaction.id.asc())
        .all()
    )
    state["user_interactions"] = [
        _serialize_interaction(item) for item in interactions
    ]
    return state


@app.post("/sessions/{session_id}/advance-day")
def advance_session_day(
    session_id: int,
    request: schemas.AdvanceDayRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    try:
        result = advance_day(db, session, request.expected_day)
    except SimulationStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _create_interaction(
        db=db,
        session_id=session_id,
        event_type="day_advance",
        post_id=0,
        metadata={
            "source": "next_day_button",
            "from_day": request.expected_day,
            "to_day": result["current_day"],
            "resolved_event": result["resolved_event"],
        },
    )
    return result


@app.post("/sessions/{session_id}/notifications/{notification_id}/read")
def read_notification(
    session_id: int,
    notification_id: int,
    db: DBSession = Depends(get_db),
):
    _get_session_or_404(db, session_id)
    notification = mark_notification_read(db, session_id, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return {"notification_id": notification.id, "is_read": notification.is_read}


@app.post("/sessions/{session_id}/posts")
async def publish_user_post(
    session_id: int,
    request: schemas.UserPostCreate,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    _ensure_world_ui_available(db, session_id)
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Post content is required.")
    post_safety = check_user_comment_safety(content, request.language)
    idempotency_key = request.idempotency_key or uuid.uuid4().hex

    existing_post = find_post_by_idempotency_key(
        db,
        session_id=session_id,
        idempotency_key=idempotency_key,
    )
    if existing_post is not None:
        return {
            "status": "existing",
            "post_id": existing_post.feed_post_id,
            "day": existing_post.day,
            "time_minutes": existing_post.world_time_minutes,
            "content": existing_post.content,
            "created_at": _isoformat(existing_post.created_at),
            "interaction_id": None,
            "source_action_id": existing_post.source_id,
            "agent_comments": [],
        }

    post_sequence = next_user_post_sequence(db, session_id)
    commenter_ids, liker_ids = select_user_post_activity_agents(
        session.simulation_seed,
        post_sequence,
    )
    author_alias = session.user_alias or session.nickname
    post_intent = _infer_post_intent(content, request.language)
    reply_relation = (
        "Agent 正在首次评论参与者发布的帖子。"
        if request.language == "zh-CN"
        else "The agent is leaving a first comment on the participant's post."
    )
    agent_requests = [
        AgentRequest(
            session_id=session_id,
            agent_id=agent_id,
            post_id=0,
            post_content=content,
            user_comment=content,
            language=request.language,
            agent_memory=get_agent_memory(db, session_id, agent_id),
            target_context=content,
            reply_target_author=author_alias,
            post_author=author_alias,
            post_intent=post_intent,
            reply_relation=reply_relation,
            interaction_kind="comment_on_user_post",
        )
        for agent_id in commenter_ids
    ]

    from services.holiday_social_identity import bind_request
    agent_requests = [bind_request(db, item) for item in agent_requests]
    # Release the read transaction before waiting on external model calls.
    db.rollback()
    from agents.output_safety import ModelStop
    try:
        generated_comments = await asyncio.gather(
            *(agent_service.generate_reply(item) for item in agent_requests)
        )
    except ModelStop:
        raise
    except Exception:
        raise ModelStop('post_comment_generation_failure') from None

    try:
        user_post, source_action, interaction, was_existing = publish_participant_post(
            db,
            session_id=session_id,
            content=content,
            language=request.language,
            idempotency_key=idempotency_key,
            liker_ids=liker_ids,
            agent_comments=list(zip(commenter_ids, generated_comments, strict=True)),
            safety_flag=post_safety.safety_flag,
        )
    except WorldStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {
        "status": "existing" if was_existing else "published",
        "post_id": user_post.feed_post_id,
        "day": user_post.day,
        "time_minutes": user_post.world_time_minutes,
        "content": user_post.content,
        "created_at": _isoformat(user_post.created_at),
        "interaction_id": interaction.id,
        "source_action_id": source_action.id,
        "agent_comments": [
            {
                "agent_id": agent_id,
                "generation_mode": result.generation_mode,
                "model_provider": result.model_provider,
                "model_name": result.model_name,
            }
            for agent_id, result in zip(
                commenter_ids,
                generated_comments,
                strict=True,
            )
        ],
    }


@app.post("/interactions", response_model=schemas.InteractionResponse)
def save_interaction(
    interaction: schemas.InteractionCreate,
    db: DBSession = Depends(get_db),
):
    event_type = interaction.event_type or interaction.action_type
    if event_type is None:
        raise HTTPException(status_code=400, detail="event_type or action_type is required.")

    session = _get_session_or_404(db, interaction.session_id)
    _ensure_active_session(session)
    post = _validate_post_for_event(
        db,
        session.id,
        event_type,
        interaction.post_id,
        current_day=_social_day(session),
        current_minute=session.world_state.current_time_minutes if session.world_state and session.world_state.world_version.startswith('chaoxi-holiday') else None,
    )
    agent_id = interaction.agent_id or (post["agent_id"] if post else None)

    content = interaction.content.strip() if interaction.content else ""
    if event_type == "comment" and not content:
        raise HTTPException(status_code=400, detail="Comment content is required.")

    existing = _find_existing_interaction(db, session.id, event_type, interaction.post_id)
    if existing is not None:
        return {
            "status": "existing",
            "interaction_id": existing.id,
            "event_type": existing.event_type,
        }

    if event_type == "like" and _is_post_currently_liked(db, session.id, interaction.post_id):
        existing_like = _latest_like_event(db, session.id, interaction.post_id)
        return {
            "status": "existing",
            "interaction_id": existing_like.id,
            "event_type": existing_like.event_type,
        }

    if event_type == "unlike" and not _is_post_currently_liked(db, session.id, interaction.post_id):
        return {"status": "ignored", "interaction_id": 0, "event_type": "unlike"}

    new_interaction = _create_interaction(
        db=db,
        session_id=session.id,
        event_type=event_type,
        post_id=interaction.post_id,
        agent_id=agent_id,
        content=content,
        response_latency_ms=interaction.response_latency_ms,
        safety_flag=(
            check_user_comment_safety(content).safety_flag
            if event_type == "comment"
            else False
        ),
        metadata=interaction.metadata,
        commit=False,
    )
    if not new_interaction.safety_flag:
        remember_user_interaction(
            db,
            session,
            agent_id,
            event_type,
            interaction.post_id,
            content,
        )
    db.commit()
    db.refresh(new_interaction)

    return {
        "status": "saved",
        "interaction_id": new_interaction.id,
        "event_type": new_interaction.event_type,
    }


@app.post(
    "/sessions/{session_id}/agent-reply",
    response_model=schemas.AgentReplyResponse,
)
async def create_agent_reply(
    session_id: int,
    request: schemas.AgentReplyRequest,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _ensure_active_session(session)
    post = get_session_post(db, session_id, request.post_id)
    if post is None:
        raise HTTPException(status_code=400, detail="Post not found.")
    if post.get("day", 1) > _social_day(session):
        raise HTTPException(status_code=400, detail="Post is not available yet.")
    if (session.world_state and session.world_state.world_version.startswith('chaoxi-holiday')
        and post.get('day',1)==_social_day(session)
        and (post.get('world_time_minutes') or 0)>session.world_state.current_time_minutes):
        raise HTTPException(status_code=400, detail="Post is not available yet.")
    agent = get_static_agent(request.agent_id)
    if session.world_state and session.world_state.world_version.startswith('chaoxi-holiday-'):
        from world.registry import get_world_spec
        from content.experience_next import enabled, active
        resident=get_world_spec(session.world_state.world_version).residents.get(request.agent_id)
        if resident and (not enabled() or active(request.agent_id,session.world_state.current_day)):
            agent={'id':request.agent_id,'name':resident.name}
        elif resident:
            raise HTTPException(status_code=409,detail='这位游客现在不在岛上，暂时无法回复。')
    if agent is None:
        raise HTTPException(status_code=400, detail="Agent not found.")

    user_comment = request.user_comment.strip()
    if not user_comment:
        raise HTTPException(status_code=400, detail="Comment content is required.")

    parent_interaction = None
    parent_community_activity = None
    target_context = ""
    reply_target_author = ""
    if request.parent_interaction_id is not None:
        parent_interaction = _get_interaction_or_400(db, request.parent_interaction_id)
        if parent_interaction.session_id != session_id:
            raise HTTPException(status_code=400, detail="Parent interaction belongs to a different session.")
        if parent_interaction.post_id != request.post_id:
            raise HTTPException(status_code=400, detail="Parent interaction belongs to a different post.")
        if parent_interaction.agent_id not in (None, request.agent_id):
            raise HTTPException(status_code=400, detail="Parent interaction belongs to a different agent.")
        target_context = (
            _withheld_safety_context(request.language)
            if parent_interaction.safety_flag
            else (parent_interaction.content or "")
        )
        reply_target_author = (
            agent["name"]
            if parent_interaction.event_type == "agent_reply"
            else (session.user_alias or session.nickname)
        )

    if request.parent_community_activity_id is not None:
        if parent_interaction is not None:
            raise HTTPException(
                status_code=400,
                detail="Choose either a conversation reply or a community comment.",
            )
        parent_community_activity = _get_community_activity_or_400(
            db,
            request.parent_community_activity_id,
        )
        if parent_community_activity.session_id != session_id:
            raise HTTPException(
                status_code=400,
                detail="Community comment belongs to a different session.",
            )
        if parent_community_activity.post_id != request.post_id:
            raise HTTPException(
                status_code=400,
                detail="Community comment belongs to a different post.",
            )
        if parent_community_activity.actor_agent_id != request.agent_id:
            raise HTTPException(
                status_code=400,
                detail="Reply target does not match the community comment author.",
            )
        target_context = (
            _withheld_safety_context(request.language)
            if parent_community_activity.safety_flag
            else _localized_activity_content(
                parent_community_activity,
                request.language,
            )
        )
        target_persona = get_static_agent(parent_community_activity.actor_agent_id)
        reply_target_author = (
            target_persona["name"] if target_persona else f"Agent {request.agent_id}"
        )

    if parent_interaction is None and parent_community_activity is None:
        if post.get("is_user_post") or post["agent_id"] != request.agent_id:
            raise HTTPException(
                status_code=400,
                detail="Agent not found for the original post.",
            )
        reply_target_author = post["agent_name"]

    previous_comment = None
    if request.idempotency_key:
        candidates=db.query(Interaction).filter_by(session_id=session_id,post_id=request.post_id,event_type='comment').all()
        previous_comment=next((row for row in candidates if json.loads(row.metadata_json or '{}').get('request_key')==request.idempotency_key),None)
        if previous_comment:
            if (previous_comment.content!=user_comment or previous_comment.agent_id!=request.agent_id
                or previous_comment.parent_interaction_id!=request.parent_interaction_id
                or previous_comment.parent_community_activity_id!=request.parent_community_activity_id):
                raise HTTPException(409,'这次提交标识已用于另一条评论。')
            existing_reply=db.query(Interaction).filter_by(parent_interaction_id=previous_comment.id,event_type='agent_reply').first()
            if existing_reply:
                return {'comment':_serialize_interaction(previous_comment),'agent_reply':_serialize_interaction(existing_reply),
                    'generation_metadata':json.loads(existing_reply.metadata_json or '{}')|{'generation_mode':existing_reply.generation_mode}}
            previous_meta=json.loads(previous_comment.metadata_json or '{}')
            status=previous_meta.get('reply_status')
            from agents.output_safety import ModelStop
            if status=='blocked':raise ModelStop('previous_exchange_blocked',safety=True)
            pending_at=datetime.fromisoformat(previous_meta['reply_started_at']) if previous_meta.get('reply_started_at') else previous_comment.created_at
            if status=='pending' and (datetime.utcnow()-pending_at).total_seconds()<120:
                raise HTTPException(409,'评论已保存，对方仍在回复，请稍后查看。')

    memory = get_agent_memory(db, session_id, request.agent_id)
    sensitive_post = (
        db.query(Interaction.id)
        .filter(
            Interaction.session_id == session_id,
            Interaction.post_id == request.post_id,
            Interaction.event_type == "user_post",
            Interaction.safety_flag.is_(True),
        )
        .first()
        is not None
    )
    localized_post_content = (
        _withheld_safety_context(request.language)
        if sensitive_post
        else _localized_post_content(post, request.language)
    )
    post_intent = _infer_post_intent(localized_post_content, request.language)
    reply_relation = _infer_reply_relation(
        user_comment=user_comment,
        language=request.language,
        post_intent=post_intent,
        parent_interaction=parent_interaction,
        parent_community_activity=parent_community_activity,
    )
    thread_history = _thread_history(
        db,
        session,
        parent_interaction,
    )
    recent_history = _recent_history(
        db,
        session_id,
        post_id=request.post_id,
        agent_id=request.agent_id,
    )
    safety_check = check_user_comment_safety(user_comment, request.language)
    comment = previous_comment or _create_interaction(
        db=db,
        session_id=session_id,
        event_type="comment",
        post_id=request.post_id,
        agent_id=request.agent_id,
        parent_interaction_id=parent_interaction.id if parent_interaction else None,
        parent_community_activity_id=(
            parent_community_activity.id if parent_community_activity else None
        ),
        content=user_comment,
        response_latency_ms=request.response_latency_ms,
        safety_flag=safety_check.safety_flag,
        metadata={
            "source": "agent_reply_flow",
            "request_key": request.idempotency_key,
            "reply_status": "pending",
            "reply_started_at": datetime.utcnow().isoformat(),
            "thread_parent_interaction_id": request.parent_interaction_id,
            "parent_community_activity_id": request.parent_community_activity_id,
            "language": request.language,
        },
    )
    if previous_comment is not None:
        comment.metadata_json=json.dumps({**json.loads(comment.metadata_json or '{}'),
            'reply_status':'pending','reply_started_at':datetime.utcnow().isoformat()},ensure_ascii=False)
    if not safety_check.safety_flag and previous_comment is None:
        remember_user_interaction(
            db,
            session,
            request.agent_id,
            "comment",
            request.post_id,
            user_comment,
        )
    db.commit()

    try:
        from services.holiday_social_identity import bind_request
        social_request = bind_request(db, AgentRequest(
                session_id=session_id,
                agent_id=request.agent_id,
                post_id=request.post_id,
                post_content=localized_post_content,
                user_comment=user_comment,
                language=request.language,
                recent_history=recent_history,
                agent_memory=memory,
                target_context=target_context,
                reply_target_author=reply_target_author,
                post_author=post["agent_name"],
                post_intent=post_intent,
                reply_relation=reply_relation,
                thread_history=thread_history,
            ))
        db.rollback()
        from content.experience_next import enabled as next_local
        comment_world=db.query(WorldState).filter_by(session_id=session_id).first()
        if next_local() and comment_world and comment_world.world_version=='chaoxi-holiday-v6':
            from services.holiday_v5_service import social_reply
            from world.registry import get_world_spec
            history=[{'speaker':'resident','content':localized_post_content}]
            history += [{'speaker':'player' if h.get('event_type')=='comment' or h.get('role')=='user' else 'resident','content':h.get('content','')} for h in thread_history]
            result=await social_reply(db,comment_world,get_world_spec(comment_world.world_version),request.agent_id,user_comment,history,'phone_comment')
        else:
            db.rollback()
            result = await agent_service.generate_reply(social_request)
    except Exception as exc:
        from agents.output_safety import ModelStop
        db.rollback()
        meta=json.loads(comment.metadata_json or '{}')
        meta['reply_status']='blocked' if isinstance(exc,ModelStop) and exc.safety else 'failed'
        comment.metadata_json=json.dumps(meta,ensure_ascii=False);db.commit()
        if isinstance(exc,ModelStop):
            from agents.output_safety import record_stop
            record_stop(db,session_id,request.idempotency_key or comment.id,exc,'phone_comment',request.agent_id)
            raise exc
        raise ModelStop() from None

    if result.metadata.get('social_decision'):
        from services.holiday_v5_service import ledger
        from services.holiday_social_v6 import enforce_proposal_budget
        comment_world=db.query(WorldState).filter_by(session_id=session_id).one()
        result=enforce_proposal_budget(db,comment_world,request.agent_id,result)
        ledger(db,comment_world,'phone-comment:'+str(comment.id),'phone_comment',{'comment_id':comment.id,'post_id':request.post_id},result.metadata,request.agent_id,user_comment)
    reply = _create_interaction(
        db=db,
        session_id=session_id,
        event_type="agent_reply",
        post_id=request.post_id,
        agent_id=request.agent_id,
        parent_interaction_id=comment.id,
        content=result.reply_content,
        response_latency_ms=result.latency_ms,
        generation_mode=result.generation_mode,
        model_provider=result.model_provider,
        model_name=result.model_name,
        prompt_version=result.prompt_version,
        safety_flag=result.safety_flag,
        metadata=result.metadata,
    )

    return {
        "comment": _serialize_interaction(comment),
        "agent_reply": _serialize_interaction(reply),
        "generation_metadata": {
            "generation_mode": result.generation_mode,
            "model_provider": result.model_provider,
            "model_name": result.model_name,
            "prompt_version": result.prompt_version,
            "safety_flag": result.safety_flag,
            "latency_ms": result.latency_ms,
            **result.metadata,
        },
    }


@app.post("/sessions/{session_id}/finish", response_model=schemas.FinishSessionResponse)
def finish_session(session_id: int, db: DBSession = Depends(get_db)):
    with session_write_lock(session_id):
        # Drop any snapshot established before waiting for the session lock.
        db.rollback()
        session = _get_session_or_404(db, session_id)
        study_owner = (
            db.query(StudySession)
            .filter(StudySession.world_session_id == session_id)
            .one_or_none()
        )
        if study_owner is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "study_departure_required",
                    "message": "Study worlds must use the confirmed study departure flow.",
                },
            )
        if session.status != "completed":
            try:
                ensure_session_can_finish(db, session)
            except WorldStateError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
            session.status = "completed"
            session.ended_at = utc_now()
            world = (
                db.query(WorldState)
                .filter(WorldState.session_id == session_id)
                .first()
            )
            if world is not None:
                invalidate_pending_interaction_prompts(
                    db,
                    world=world,
                    reason_code="session_finished",
                )
            _create_interaction(
                db=db,
                session_id=session_id,
                event_type="finish_session",
                post_id=0,
                metadata={"source": "finish_button"},
                commit=False,
            )
            db.commit()
            db.refresh(session)

    return {
        "session_id": session.id,
        "status": session.status,
        "ended_at": _isoformat(session.ended_at),
    }


@app.get("/sessions/{session_id}/features", response_model=schemas.FeaturesResponse)
def get_session_features(session_id: int, db: DBSession = Depends(get_db)):
    session, interactions = _session_with_interactions(db, session_id)
    features = extract_session_features(session, interactions).to_dict()
    return {"session_id": session_id, **features}


@app.get("/sessions/{session_id}/score", response_model=schemas.ScoreResponse)
def get_session_score(
    session_id: int,
    language: schemas.LanguageCode = Query("en"),
    db: DBSession = Depends(get_db),
):
    return _score_payload(db, session_id, language)


@app.post("/score/{session_id}", response_model=schemas.ScoreResponse)
def score_session(
    session_id: int,
    language: schemas.LanguageCode = Query("en"),
    db: DBSession = Depends(get_db),
):
    return _score_payload(db, session_id, language)


@app.get("/sessions/{session_id}/export")
def export_session(
    session_id: int,
    format: str = Query("json", pattern="^(json|csv)$"),
    scope: str = Query("legacy", pattern="^(legacy|island)$"),
    db: DBSession = Depends(get_db),
):
    if format == "csv" and scope == "island":
        raise HTTPException(
            status_code=422,
            detail="CSV export is only available for scope=legacy; use JSON for island data.",
        )
    session, interactions = _session_with_interactions(db, session_id)
    features = extract_session_features(session, interactions).to_dict()

    if format == "csv":
        return _csv_export_response(session_id, interactions)

    try:
        island_world = build_island_export(db, session)
    except WorldStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    payload = {
        "export_scope": scope,
        "session": _serialize_session(session),
        "interactions": [_serialize_interaction(item) for item in interactions],
        "agent_replies": [
            _serialize_interaction(item)
            for item in interactions
            if item.event_type == "agent_reply"
        ],
        "features": features,
        "simulation": build_feed_state(db, session),
        "agent_memories": list_agent_memories(db, session_id),
        "island_world": island_world,
        "versions": {
            "feature_version": features["feature_version"],
            **island_world["versions"],
        },
    }
    if scope == "legacy":
        score = prototype_scorer.score(features)
        payload["prototype_score"] = score
        payload["versions"]["score_version"] = score["score_version"]
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="session-{session_id}.json"'},
    )


def _get_session_or_404(db: DBSession, session_id: int) -> UserSession:
    session = db.query(UserSession).filter(UserSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


def _get_interaction_or_400(db: DBSession, interaction_id: int) -> Interaction:
    interaction = db.query(Interaction).filter(Interaction.id == interaction_id).first()
    if interaction is None:
        raise HTTPException(status_code=400, detail="Parent interaction not found.")
    return interaction


def _get_community_activity_or_400(
    db: DBSession,
    activity_id: int,
) -> CommunityActivity:
    activity = (
        db.query(CommunityActivity)
        .filter(CommunityActivity.id == activity_id)
        .first()
    )
    if activity is None:
        raise HTTPException(status_code=400, detail="Community comment not found.")
    return activity


def _social_day(session):
    # Legacy feed sessions use their own calendar.
    world = session.world_state
    return world.current_day if world and world.world_version.startswith('chaoxi-holiday') else session.current_day


def _ensure_active_session(session: UserSession) -> None:
    if session.status != "active":
        raise HTTPException(status_code=400, detail=f"Session is {session.status}.")


def _ensure_world_ui_available(db, session_id):
    from models import WorldState
    from services.interaction_time_service import focus_state
    from services.world_service import world_has_ended
    world = db.query(WorldState).filter_by(session_id=session_id).first()
    if world and world.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6') and (world_has_ended(world) or (focus_state(world) or {}).get('full_activity')):
        raise HTTPException(status_code=409, detail='请先结束当前活动；七日结束后不能继续操作小岛。')


def _validate_post_for_event(
    db: DBSession,
    session_id: int,
    event_type: str,
    post_id: int,
    current_day: int | None = None,
    current_minute: int | None = None,
) -> dict | None:
    if event_type in {"finish_session", "day_advance"}:
        return None
    if post_id <= 0:
        raise HTTPException(status_code=400, detail="post_id is required for this event.")
    post = get_session_post(db, session_id, post_id)
    if post is None:
        raise HTTPException(status_code=400, detail="Post not found.")
    if current_day is not None and post.get("day", 1) > current_day:
        raise HTTPException(status_code=400, detail="Post is not available yet.")
    if current_minute is not None and post.get('day',1)==current_day and (post.get('world_time_minutes') or 0)>current_minute:
        raise HTTPException(status_code=400, detail="Post is not available yet.")
    return post


def _find_existing_interaction(
    db: DBSession,
    session_id: int,
    event_type: str,
    post_id: int,
) -> Interaction | None:
    if event_type not in {"post_view", "skip"}:
        return None
    return (
        db.query(Interaction)
        .filter(
            Interaction.session_id == session_id,
            Interaction.event_type == event_type,
            Interaction.post_id == post_id,
        )
        .order_by(Interaction.created_at.desc())
        .first()
    )


def _is_post_currently_liked(db: DBSession, session_id: int, post_id: int) -> bool:
    latest = (
        db.query(Interaction)
        .filter(
            Interaction.session_id == session_id,
            Interaction.post_id == post_id,
            Interaction.event_type.in_(["like", "unlike"]),
        )
        .order_by(Interaction.created_at.desc(), Interaction.id.desc())
        .first()
    )
    return latest is not None and latest.event_type == "like"


def _latest_like_event(db: DBSession, session_id: int, post_id: int) -> Interaction:
    return (
        db.query(Interaction)
        .filter(
            Interaction.session_id == session_id,
            Interaction.post_id == post_id,
            Interaction.event_type == "like",
        )
        .order_by(Interaction.created_at.desc(), Interaction.id.desc())
        .first()
    )


def _create_interaction(
    *,
    db: DBSession,
    session_id: int,
    event_type: str,
    post_id: int = 0,
    agent_id: int | None = None,
    parent_interaction_id: int | None = None,
    parent_community_activity_id: int | None = None,
    content: str = "",
    response_latency_ms: int | None = None,
    generation_mode: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    prompt_version: str | None = None,
    safety_flag: bool = False,
    metadata: dict[str, Any] | None = None,
    commit: bool = True,
) -> Interaction:
    created_at = utc_now()
    world = (
        db.query(WorldState)
        .filter(WorldState.session_id == session_id)
        .first()
    )
    interaction = Interaction(
        session_id=session_id,
        event_type=event_type,
        action_type=event_type,
        post_id=post_id,
        agent_id=agent_id,
        parent_interaction_id=parent_interaction_id,
        parent_community_activity_id=parent_community_activity_id,
        content=content,
        created_at=created_at,
        timestamp=created_at,
        response_latency_ms=response_latency_ms,
        generation_mode=generation_mode,
        model_provider=model_provider,
        model_name=model_name,
        prompt_version=prompt_version,
        safety_flag=safety_flag,
        world_day=world.current_day if world is not None else None,
        world_time_minutes=world.current_time_minutes if world is not None else None,
        metadata_json=json.dumps(metadata or {}),
    )
    db.add(interaction)
    if commit:
        db.commit()
        db.refresh(interaction)
    return interaction


def _infer_post_intent(content: str, language: str) -> str:
    is_question = "?" in content or "？" in content
    if language == "zh-CN":
        return (
            "帖子作者正在向社区提问或征集想法。"
            if is_question
            else "帖子作者正在分享一段经历、观察或近况。"
        )
    return (
        "The post author is asking the community a question or inviting ideas."
        if is_question
        else "The post author is sharing an experience, observation, or update."
    )


def _infer_reply_relation(
    *,
    user_comment: str,
    language: str,
    post_intent: str,
    parent_interaction: Interaction | None,
    parent_community_activity: CommunityActivity | None,
) -> str:
    user_asks_question = "?" in user_comment or "？" in user_comment
    if language == "zh-CN":
        if parent_interaction is not None:
            return (
                "用户正在当前一对一对话线程中追问 Agent。"
                if user_asks_question
                else "用户正在回应 Agent 在当前一对一线程中的上一条回复。"
            )
        if parent_community_activity is not None:
            return (
                "用户正在直接询问这条社区评论的作者。"
                if user_asks_question
                else "用户正在直接回应这条社区评论，而不是向原帖作者求助。"
            )
        if "提问或征集想法" in post_intent:
            return (
                "用户正在反问帖子作者。"
                if user_asks_question
                else "用户正在回答帖子作者提出的问题或提供对方征集的想法。"
            )
        return (
            "用户正在向帖子作者提出一个问题。"
            if user_asks_question
            else "用户正在回应帖子作者分享的内容。"
        )

    if parent_interaction is not None:
        return (
            "The participant is asking the agent a follow-up question in their direct thread."
            if user_asks_question
            else "The participant is responding to the agent's previous reply in their direct thread."
        )
    if parent_community_activity is not None:
        return (
            "The participant is directly asking the author of this community comment a question."
            if user_asks_question
            else "The participant is directly responding to this community comment, not asking the original post author for help."
        )
    if "asking the community" in post_intent:
        return (
            "The participant is asking the post author a question in return."
            if user_asks_question
            else "The participant is answering the post author's question or offering an idea the author requested."
        )
    return (
        "The participant is asking the post author a question."
        if user_asks_question
        else "The participant is reacting to what the post author shared."
    )


def _thread_history(
    db: DBSession,
    session: UserSession,
    parent_interaction: Interaction | None,
) -> list[dict[str, str]]:
    if parent_interaction is None:
        return []

    chain = []
    current = parent_interaction
    seen_ids: set[int] = set()
    while current is not None and current.id not in seen_ids and len(chain) < 12:
        seen_ids.add(current.id)
        chain.append(current)
        if current.parent_interaction_id is None:
            break
        current = (
            db.query(Interaction)
            .filter(
                Interaction.id == current.parent_interaction_id,
                Interaction.session_id == session.id,
            )
            .first()
        )

    history = []
    for interaction in reversed(chain):
        if interaction.safety_flag:
            continue
        agent_profile = (
            get_static_agent(interaction.agent_id)
            if interaction.agent_id is not None
            else None
        )
        speaker = (
            agent_profile["name"]
            if interaction.event_type == "agent_reply" and agent_profile
            else (session.user_alias or session.nickname)
        )
        history.append(
            {
                "speaker": speaker,
                "event_type": interaction.event_type,
                "content": interaction.content or "",
            }
        )
    return history


def _withheld_safety_context(language: str) -> str:
    if language == "zh-CN":
        return "\u4e00\u6761\u5b89\u5168\u654f\u611f\u7684\u65e9\u671f\u6d88\u606f\u5df2\u88ab\u7701\u7565\u3002"
    return "A prior safety-sensitive message was intentionally withheld."


def _recent_history(
    db: DBSession,
    session_id: int,
    *,
    post_id: int,
    agent_id: int,
) -> list[dict[str, Any]]:
    interactions = (
        db.query(Interaction)
        .filter(
            Interaction.session_id == session_id,
            Interaction.post_id == post_id,
            Interaction.agent_id == agent_id,
                Interaction.event_type.in_(["comment", "agent_reply"]),
                Interaction.safety_flag.is_(False),
        )
        .order_by(Interaction.created_at.desc(), Interaction.id.desc())
        .limit(6)
        .all()
    )
    return [
        {
            "event_type": item.event_type,
            "post_id": item.post_id,
            "agent_id": item.agent_id,
            "speaker": (
                get_static_agent(item.agent_id)["name"]
                if item.event_type == "agent_reply"
                and item.agent_id is not None
                and get_static_agent(item.agent_id)
                else "Participant"
            ),
            "content": item.content,
            "safety_flag": item.safety_flag,
        }
        for item in reversed(interactions)
    ]


def _session_with_interactions(
    db: DBSession,
    session_id: int,
) -> tuple[UserSession, list[Interaction]]:
    session = _get_session_or_404(db, session_id)
    interactions = (
        db.query(Interaction)
        .filter(Interaction.session_id == session_id)
        .order_by(Interaction.created_at.asc(), Interaction.id.asc())
        .all()
    )
    return session, interactions


def _score_payload(
    db: DBSession,
    session_id: int,
    language: schemas.LanguageCode = "en",
) -> dict[str, Any]:
    session, interactions = _session_with_interactions(db, session_id)
    features = extract_session_features(session, interactions).to_dict()
    score = prototype_scorer.score(features, language)
    display_features = _localized_feature_warnings(features, language)
    return {
        "session_id": session_id,
        "session_status": session.status,
        **score,
        "text_features": display_features["text_features"],
        "behavior_features": display_features["behavior_features"],
        "data_quality": display_features["data_quality"],
        "risk_score": None,
        "risk_level": None,
        "crisis_detected": any(item.safety_flag for item in interactions),
    }


def _localized_post_content(post: dict[str, Any], language: str) -> str:
    translations = post.get("translations", {})
    localized = translations.get(language, {}) if isinstance(translations, dict) else {}
    content = localized.get("content") if isinstance(localized, dict) else None
    return content if isinstance(content, str) and content else post["content"]


def _localized_activity_content(
    activity: CommunityActivity,
    language: str,
) -> str:
    if language == "zh-CN" and activity.content_zh_cn:
        return activity.content_zh_cn
    return activity.content_en or activity.content_zh_cn


def _localized_feature_warnings(
    features: dict[str, Any],
    language: str,
) -> dict[str, Any]:
    if language != "zh-CN":
        return features

    warning_translations = {
        "No post_view events were recorded.": "没有记录到帖子浏览事件。",
        "No user comments were recorded.": "没有记录到用户评论。",
    }
    data_quality = dict(features["data_quality"])
    data_quality["warnings"] = [
        warning_translations.get(str(warning), str(warning))
        for warning in data_quality.get("warnings", [])
    ]
    return {**features, "data_quality": data_quality}


def _serialize_session(session: UserSession) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "user_alias": session.user_alias or session.nickname,
        "consent_version": session.consent_version,
        "status": session.status,
        "started_at": _isoformat(session.started_at),
        "ended_at": _isoformat(session.ended_at),
        "current_day": session.current_day,
        "total_days": session.total_days,
        "simulation_seed": session.simulation_seed,
        "virtual_start_date": (
            session.virtual_start_date.isoformat()
            if session.virtual_start_date
            else ""
        ),
    }


def _serialize_interaction(interaction: Interaction) -> dict[str, Any]:
    return {
        "interaction_id": interaction.id,
        "session_id": interaction.session_id,
        "event_type": interaction.event_type,
        "post_id": interaction.post_id,
        "agent_id": interaction.agent_id,
        "parent_interaction_id": interaction.parent_interaction_id,
        "parent_community_activity_id": interaction.parent_community_activity_id,
        "content": interaction.content or "",
        "created_at": _isoformat(interaction.created_at),
        "response_latency_ms": interaction.response_latency_ms,
        "generation_mode": interaction.generation_mode,
        "model_provider": interaction.model_provider,
        "model_name": interaction.model_name,
        "prompt_version": interaction.prompt_version,
        "safety_flag": interaction.safety_flag,
        "world_day": interaction.world_day,
        "world_time_minutes": interaction.world_time_minutes,
        "metadata": _json_loads(interaction.metadata_json),
    }


def _json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _isoformat(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat() + "Z"


def _csv_export_response(session_id: int, interactions: list[Interaction]) -> Response:
    output = io.StringIO()
    fieldnames = [
        "interaction_id",
        "session_id",
        "event_type",
        "post_id",
        "agent_id",
        "parent_interaction_id",
        "parent_community_activity_id",
        "content",
        "created_at",
        "response_latency_ms",
        "generation_mode",
        "model_provider",
        "model_name",
        "prompt_version",
        "safety_flag",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for item in interactions:
        row = _serialize_interaction(item)
        writer.writerow({key: row[key] for key in fieldnames})

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="session-{session_id}.csv"'},
    )

from services.holiday_v5_service import router as holiday_v5_router
app.include_router(holiday_v5_router)

from fastapi.staticfiles import StaticFiles
from pathlib import Path
_next_art_dir = Path(__file__).resolve().parent.parent / 'frontend/public/next-art'
from content.experience_next import enabled as next_enabled
if next_enabled() and _next_art_dir.is_dir():
    app.mount('/next-art',StaticFiles(directory=str(_next_art_dir)),name='next-art')
_player_art_dir = Path(__file__).resolve().parent / 'assets' / 'player-v5' 
if _player_art_dir.is_dir():
    app.mount('/v5', StaticFiles(directory=str(_player_art_dir)), name='player-art-v5')
_holiday_art_dir = Path(__file__).resolve().parent / 'assets' / 'holiday-v5' / 'images'
if _holiday_art_dir.is_dir():
    app.mount('/holiday-art', StaticFiles(directory=str(_holiday_art_dir)), name='holiday-art')
_holiday_v6_art_dir=Path(__file__).resolve().parent/'assets'/'holiday-v6'/'images'
if _holiday_v6_art_dir.is_dir():
    app.mount('/holiday-art-v6',StaticFiles(directory=str(_holiday_v6_art_dir)),name='holiday-art-v6')
