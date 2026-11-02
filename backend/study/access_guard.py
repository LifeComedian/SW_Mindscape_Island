"""Request authorization for the study deployment."""
from __future__ import annotations

from collections import deque
import os
import re
import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from database import SessionLocal
from study.access import invitation_required, production_access
from study.models import StudySession
from study.service import StudyWorkflowError, authenticate_study_session

def _world_owner(public_id, token):
    # Keep database pool waits off the event loop.
    with SessionLocal() as db:
        owner=authenticate_study_session(db, public_id=public_id, recovery_token=token)
        return owner.world_session_id, owner.state


class StudyAccessGuard(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.attempts = deque()
        self.lock = threading.Lock()

    async def dispatch(self, request, call_next):
        path = request.url.path
        if os.getenv('REVIEW_MODE') == 'true' and path == '/study/sessions/bootstrap':
            return JSONResponse({'code': 'review_entry_required'}, 404)
        if path == "/study/sessions/bootstrap" and invitation_required():
            # Bounded global gate works behind the BFF without trusting forwarded IPs.
            with self.lock:
                now = time.monotonic()
                while self.attempts and self.attempts[0] <= now - 60:
                    self.attempts.popleft()
                if len(self.attempts) >= 30:
                    return JSONResponse({"code": "admission_rate_limited"}, 429, headers={"Retry-After": "60"})
                self.attempts.append(now)
        if not production_access():
            return await call_next(request)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = os.getenv("STUDY_PUBLIC_ORIGIN", "").rstrip("/")
            # Cookie-authenticated writes require the configured public origin.
            if (origin and (not expected or origin != expected)) or (
                request.cookies and (not origin or origin != expected)
            ):
                return JSONResponse({"code": "origin_rejected"}, 403)
        if path in {"/", "/health","/v5/player-male.png","/v5/player-female.png"} or path.startswith(("/world-assets/", "/holiday-art/", "/holiday-art-v6/", "/next-art/")):
            return await call_next(request)
        # This endpoint is the static location catalogue, with no session data.
        if path == "/locations" and request.method in {"GET", "HEAD"}:
            return await call_next(request)
        if path.startswith("/study/"):
            if path.startswith("/study/test-fixtures"):
                return JSONResponse({"code": "not_found"}, 404)
            return await call_next(request)
        match = re.fullmatch(r"/sessions/(\d+)/(world(?:/.*)?|island/pulse|feed|notifications/\d+/read|posts|agent-reply)", path)
        requested_session_id = int(match.group(1)) if match else None
        # Authorize the session from the request body for interaction writes.
        if path == "/interactions" and request.method == "POST":
            try:
                payload = await request.json()
            except (ValueError, UnicodeDecodeError):
                return JSONResponse({"code": "invalid_interaction"}, 400)
            candidate = payload.get("session_id") if isinstance(payload, dict) else None
            if type(candidate) is not int or candidate <= 0:
                return JSONResponse({"code": "invalid_interaction"}, 400)
            requested_session_id = candidate
        administrative_world_route = bool(re.search(r"/world/emergence(?:/evaluations|/events/\d+/transitions)?$", path))
        if requested_session_id is None or "/development/" in path or administrative_world_route:
            return JSONResponse({"code": "not_found"}, 404)
        review = os.getenv('REVIEW_MODE') == 'true'
        token = request.cookies.get("mindscape_review_session_token" if review else "mindscape_study_recovery", "")
        public_id = request.cookies.get("mindscape_review_session_id" if review else "mindscape_study_id", "")
        if not token or not public_id:
            return JSONResponse({"code": "study_session_required"}, 401)
        try:
            world_session_id, state = await run_in_threadpool(_world_owner, public_id, token)
            if world_session_id != requested_session_id:
                return JSONResponse({"code": "study_session_required"}, 404)
            if request.method == "POST" and state not in {"island_active", "island_departure_pending"}:
                return JSONResponse({"code": "island_not_active"}, 409)
        except StudyWorkflowError:
            return JSONResponse({"code": "study_session_required"}, 401)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response
