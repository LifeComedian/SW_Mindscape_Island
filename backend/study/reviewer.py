"""Isolated reviewer accounts, repeat visits, and recovery."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, inspect, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from database import Base, SessionLocal, engine
from study.models import StudySession, StudyConsentRecord, StudyParticipantProfile, StudyQuestionnaireResponse
from study.service import hash_recovery_token, utc_now

NOTICE_VERSION = 'review-notice-20261102-v1'
NOTICE = ('本入口用于项目评审，不计入正式研究。系统会保存本次游戏操作、对话、作品和问卷回答，'
          '用于继续进度及生成报告。居民对话和报告生成会通过配置的Qwen服务处理部分游戏内容。'
          '请勿输入真实联系方式或其他敏感个人信息。本入口不收集报名联系方式，也不涉及报酬。'
          '观察报告供体验与讨论，不是诊断或经过验证的人格测量。个人恢复码可访问你的体验记录，请自行保管。')
NOTICE_HASH = hashlib.sha256(NOTICE.encode()).hexdigest()
_lock = threading.RLock()
_attempts: deque[float] = deque()


class ReviewAccount(Base):
    __tablename__ = 'review_accounts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(80), unique=True)
    creation_key: Mapped[str] = mapped_column(String(120), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class ReviewVisit(Base):
    __tablename__ = 'review_visits'
    __table_args__ = (UniqueConstraint('account_id', 'request_key'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey('review_accounts.id'), index=True)
    study_session_id: Mapped[int] = mapped_column(ForeignKey('study_sessions.id'), unique=True)
    request_key: Mapped[str] = mapped_column(String(120))
    nickname: Mapped[str] = mapped_column(String(40))
    recovery_hash: Mapped[str] = mapped_column(String(64), unique=True)
    notice_version: Mapped[str] = mapped_column(String(80), default=NOTICE_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


def enabled():
    return os.getenv('REVIEW_MODE') == 'true'


def assert_isolated_database():
    if not enabled():
        return
    if engine.url.get_backend_name() != 'sqlite' or Path(engine.url.database or '').name != 'reviewer.sqlite':
        raise RuntimeError('Reviewer mode requires a dedicated reviewer.sqlite database.')
    if len(os.getenv('REVIEW_SIGNING_SECRET', '')) < 32 or not re.fullmatch(r'[a-f0-9]{64}', os.getenv('REVIEW_ACCESS_CODE_SHA256', '')):
        raise RuntimeError('Reviewer credentials are not configured.')
    tables = inspect(engine).get_table_names()
    if 'study_sessions' in tables and 'review_accounts' not in tables:
        with engine.connect() as connection:
            if connection.execute(text('select count(*) from study_sessions')).scalar():
                raise RuntimeError('Refusing to attach reviewer mode to an existing study database.')


def require_review():
    if not enabled():
        raise HTTPException(404, detail={'code': 'not_found'})


def db_session():
    with SessionLocal() as db:
        yield db


def credential(kind, identifier):
    secret = os.environ['REVIEW_SIGNING_SECRET'].encode()
    return hmac.new(secret, f'{kind}:{identifier}'.encode(), hashlib.sha256).hexdigest()


def account_token(account):
    return credential('account', account.public_id)


def visit_token(session):
    return credential('visit', session.public_id)


def recovery_code(session):
    return 'RV-' + credential('recovery', session.public_id).upper()


def throttle():
    with _lock:
        now = time.monotonic()
        while _attempts and _attempts[0] < now - 60:
            _attempts.popleft()
        if len(_attempts) >= 40:
            raise HTTPException(429, detail={'code': 'review_rate_limit', 'message': '操作较频繁，请稍后重试。'})
        _attempts.append(now)


def authenticate(db, account_id, token):
    row = db.query(ReviewAccount).filter_by(public_id=account_id).one_or_none()
    if row is None or not hmac.compare_digest(row.token_hash, hash_recovery_token(token or '')):
        raise HTTPException(401, detail={'code': 'review_access_required', 'message': '请使用体验口令或个人恢复码进入。'})
    return row


def owner(db=Depends(db_session), account_id: str = Header('', alias='X-Review-Account'),
          token: str = Header('', alias='X-Review-Token')):
    return authenticate(db, account_id, token)


def owned_visit(db, account, session_id):
    row = (db.query(ReviewVisit).join(StudySession, StudySession.id == ReviewVisit.study_session_id)
           .filter(ReviewVisit.account_id == account.id, StudySession.public_id == session_id).one_or_none())
    if row is None:
        raise HTTPException(404, detail={'code': 'review_visit_not_found'})
    return row, db.get(StudySession, row.study_session_id)


def account_payload(account):
    return {'account_id': account.public_id, 'account_token': account_token(account)}


def visit_payload(db, account, visit):
    from study.api import STEP_PATHS
    from study.contracts import StudyWorkflowState
    session = db.get(StudySession, visit.study_session_id)
    session.recovery_token_expires_at = utc_now() + timedelta(days=30)
    account.last_seen_at = utc_now()
    db.commit()
    path = STEP_PATHS[StudyWorkflowState(session.state)]
    if session.state in REPORT_STATES:
        path = '/review/reports'
    return {**account_payload(account), 'study_session_id': session.public_id, 'recovery_token': visit_token(session),
            'recovery_code': recovery_code(session), 'nickname': visit.nickname,
            'current_step_path': path, 'state': session.state}


REPORT_STATES = {'questionnaire_completed', 'pre_result_feedback', 'results_ready', 'result_one_active',
                 'result_one_rated', 'result_two_active', 'result_two_rated', 'comparative_feedback', 'debrief', 'completed'}
router = APIRouter(prefix='/study/review', dependencies=[Depends(require_review)])


class AccessRequest(BaseModel):
    code: str = Field(min_length=1, max_length=150)
    request_key: str = Field(pattern=r'^[A-Za-z0-9_-]{24,100}$')


class StartRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=20)
    accepted: bool
    request_key: str = Field(pattern=r'^[A-Za-z0-9_-]{24,100}$')


class VisitRequest(BaseModel):
    session_id: str = Field(min_length=10, max_length=80)


class RecoveryRequest(BaseModel):
    code: str = Field(min_length=1, max_length=150)


@router.get('/notice')
def notice():
    return {'version': NOTICE_VERSION, 'text': NOTICE}


@router.post('/access')
def access(request: AccessRequest, db: Session = Depends(db_session)):
    throttle()
    supplied = hashlib.sha256(request.code.strip().encode()).hexdigest()
    if not hmac.compare_digest(supplied, os.environ['REVIEW_ACCESS_CODE_SHA256']):
        raise HTTPException(403, detail={'code': 'invalid_review_code', 'message': '体验口令不正确，请核对后重试。'})
    with _lock:
        account = db.query(ReviewAccount).filter_by(creation_key=request.request_key).one_or_none()
        if account is None:
            account = ReviewAccount(public_id='review_' + uuid.uuid4().hex, creation_key=request.request_key)
            account.token_hash = hash_recovery_token(account_token(account))
            db.add(account)
            db.commit()
        return account_payload(account)


@router.get('/visits')
def visits(account=Depends(owner), db: Session = Depends(db_session)):
    from models import WorldState
    rows = db.query(ReviewVisit).filter_by(account_id=account.id).order_by(ReviewVisit.id.desc()).all()
    result=[]
    for row in rows:
        session = db.get(StudySession, row.study_session_id)
        world = db.query(WorldState).filter_by(session_id=session.world_session_id).one_or_none()
        result.append({'session_id': session.public_id, 'nickname': row.nickname, 'state': session.state,
                       'created_at': row.created_at.isoformat()+'Z', 'day': world.current_day if world else 1,
                       'reports_ready': session.state in REPORT_STATES})
        if session.recovery_token_expires_at < utc_now() + timedelta(days=14):
            session.recovery_token_expires_at = utc_now() + timedelta(days=30)
    if account.last_seen_at < utc_now()-timedelta(hours=12):
        account.last_seen_at=utc_now()
    db.commit()
    return {'visits':result}


@router.post('/start')
def start(request: StartRequest, account=Depends(owner), db: Session = Depends(db_session)):
    from study.participant_service import validate_nickname
    from study.protocol_v2 import VERSION, progress
    from study.contracts import STUDY_CONTRACT_VERSION
    from study.world_bridge_service import bind_fixture_world
    if not request.accepted:
        raise HTTPException(422, detail={'code':'review_notice_required','message':'请先阅读并同意体验说明。'})
    try:
        nickname=validate_nickname(request.nickname.strip())
    except Exception:
        raise HTTPException(422,detail={'code':'invalid_nickname','message':'请使用不含联系方式的简短昵称。'}) from None
    with _lock:
        previous=db.query(ReviewVisit).filter_by(account_id=account.id,request_key=request.request_key).one_or_none()
        if previous is not None:
            if previous.nickname!=nickname:
                raise HTTPException(409,detail={'code':'request_conflict'})
            session=db.get(StudySession,previous.study_session_id)
            if session.world_session_id is None:
                bind_fixture_world(db,study_session=session,expected_revision=session.revision,
                                   idempotency_key='review-bind:'+session.public_id)
            return visit_payload(db,account,previous)
        if db.query(ReviewVisit).filter_by(account_id=account.id).count() >= 100:
            raise HTTPException(429,detail={'code':'visit_limit','message':'已达到本账户的体验次数上限，请联系项目作者。'})
        session=StudySession(public_id='study_'+uuid.uuid4().hex,state='onboarding',revision=0,language='zh-CN',
            study_contract_version=STUDY_CONTRACT_VERSION,workflow_version=VERSION,
            creation_idempotency_key='review:'+account.public_id+':'+request.request_key,
            recovery_token_expires_at=utc_now()+timedelta(days=30),compensation_stage='review_not_applicable')
        session.recovery_token_hash=hash_recovery_token(visit_token(session))
        db.add(session);db.flush()
        db.add(StudyConsentRecord(study_session_id=session.id,consent_version=NOTICE_VERSION,
                                 document_sha256=NOTICE_HASH,language='zh-CN'))
        db.add(StudyParticipantProfile(study_session_id=session.id,research_id='RV'+uuid.uuid4().hex,
            game_nickname=nickname,gaming_frequency_code='skipped',social_game_experience_code='skipped',
            ai_text_frequency_code='skipped',baseline_version='review-not-collected'))
        progress(db,session).baseline_started_at=utc_now()
        row=ReviewVisit(account_id=account.id,study_session_id=session.id,request_key=request.request_key,
                       nickname=nickname,recovery_hash=hash_recovery_token(recovery_code(session)))
        db.add(row);db.commit()
        bind_fixture_world(db,study_session=session,expected_revision=session.revision,
                           idempotency_key='review-bind:'+session.public_id)
        return visit_payload(db,account,row)


@router.post('/resume')
def resume(request: VisitRequest, account=Depends(owner), db: Session = Depends(db_session)):
    row,session=owned_visit(db,account,request.session_id)
    if session.world_session_id is None:
        from study.world_bridge_service import bind_fixture_world
        with _lock:
            bind_fixture_world(db,study_session=session,expected_revision=session.revision,
                               idempotency_key='review-bind:'+session.public_id)
    return visit_payload(db,account,row)


@router.post('/recover')
def recover(request: RecoveryRequest, db: Session = Depends(db_session)):
    throttle()
    code=request.code.strip().upper()
    row=db.query(ReviewVisit).filter_by(recovery_hash=hash_recovery_token(code)).one_or_none()
    if row is None:
        raise HTTPException(403,detail={'code':'invalid_recovery_code','message':'个人恢复码不正确，请完整复制后重试。'})
    session=db.get(StudySession,row.study_session_id)
    if session.world_session_id is None:
        from study.world_bridge_service import bind_fixture_world
        with _lock:
            bind_fixture_world(db,study_session=session,expected_revision=session.revision,
                               idempotency_key='review-bind:'+session.public_id)
    return visit_payload(db,db.get(ReviewAccount,row.account_id),row)


@router.post('/reports')
def reports(request: VisitRequest, account=Depends(owner), db: Session = Depends(db_session)):
    from study.models import StudyAvailableResults, StudyGameEstimate, StudyQuestionnaireScore, StudyAssessmentJob
    from study.protocol_v2 import digest
    from study.results_service import _game_report_payload, _questionnaire_report_payload
    from study.available_results import prepare, report
    row,session=owned_visit(db,account,request.session_id)
    if session.state == 'questionnaire_completed':
        session=prepare(db,session)
    result=[]
    availability=db.query(StudyAvailableResults).filter_by(study_session_id=session.id).one_or_none()
    game=db.query(StudyGameEstimate).filter_by(study_session_id=session.id,analysis_version=1).one_or_none()
    score=db.query(StudyQuestionnaireScore).filter_by(study_session_id=session.id).one_or_none()
    if game is not None:
        job=db.get(StudyAssessmentJob,game.assessment_job_id)
        if digest({'result':json.loads(game.result_json),'report_text':game.report_text,'package':job.package_sha256})!=game.output_sha256:
            raise HTTPException(409,detail={'code':'report_hash_mismatch'})
        result.append(report(db,session,'game_estimate') if availability else _game_report_payload(game))
    if score is not None:
        if availability is None:
            raise HTTPException(409,detail={'code':'report_preparing'})
        result.append(report(db,session,'questionnaire'))
    response=db.query(StudyQuestionnaireResponse).filter_by(study_session_id=session.id).one_or_none()
    return {'nickname':row.nickname,'state':session.state,'reports':result,
            'questionnaire_submitted':response is not None,'recovery_code':recovery_code(session)}
