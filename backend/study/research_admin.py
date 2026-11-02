"""Server-local research exports and erasure operations."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from sqlalchemy import create_engine, event, select, delete, or_, update
from sqlalchemy.orm import Session
from database import Base
import models  # noqa: F401
from services.player_record_service import WorldPlayerRecord  # noqa: F401
from study import models as study_models
from study.access import StudyInvitation  # noqa: F401
from study.service import StudyWorkflowError, utc_now

def subject(public_id):
    return hashlib.sha256(public_id.encode()).hexdigest()

def storage_root(value=None):
    value=value or os.getenv('STUDY_RESEARCH_STORAGE_ROOT')
    if not value: raise ValueError('Set STUDY_RESEARCH_STORAGE_ROOT to a restricted operator directory.')
    path=Path(value).absolute()
    if path==Path(path.anchor) or any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in [path,*path.parents]): raise ValueError('Unsafe research storage root.')
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    return path.resolve()

def contained(root,relative):
    path=root/relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts: raise ValueError('Unsafe managed path.')
    for part in [path,*path.parents]:
        if part==root:break
        if part.is_symlink() or getattr(part,'is_junction',lambda:False)(): raise ValueError('Managed paths cannot be links.')
    if not path.resolve().is_relative_to(root):raise ValueError('Managed path escapes root.')
    return path

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_name(path.name+'.writing-'+secrets.token_hex(5))
    with temporary.open('x',encoding='utf8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.chmod(temporary,0o600)
    temporary.replace(path)

def register_artifact(root,path,public_ids):
    root=storage_root(root);path=Path(path).resolve()
    relative=path.relative_to(root).as_posix()
    if Path(relative).parts[0] not in ('participants','analysis') or not path.is_file():
        raise ValueError('Register only existing files inside participants/ or analysis/.')
    contained(root,relative)
    hashes=sorted(set(subject(x) for x in public_ids))
    if not hashes or any((root/'deletions'/f'{h}.json').exists() for h in hashes):
        raise ValueError('Missing subjects or revoked data in artifact.')
    key=hashlib.sha256(relative.encode()).hexdigest()
    write_json(root/'artifacts'/f'{key}.json',{'relative_path':relative,'subjects':hashes,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})

def export_feedback(db,public_id,root,operator):
    root=storage_root(root);hashed=subject(public_id)
    if (root/'deletions'/f'{hashed}.json').exists():raise StudyWorkflowError('Subject was revoked.',410,'research_data_deleted')
    session=db.query(study_models.StudySession).filter_by(public_id=public_id).one_or_none()
    if session is None:raise StudyWorkflowError('Session unavailable.',404,'study_not_found')
    feedback=db.query(study_models.StudyComparativeFeedback).filter_by(study_session_id=session.id).one_or_none()
    if feedback is None:raise StudyWorkflowError('No frozen feedback.',409,'feedback_not_frozen')
    path=contained(root,f'participants/{hashed}/feedback-{secrets.token_hex(6)}.json')
    # Raw text is restricted, not anonymous; never printed or sent to a model.
    payload={'schema':'restricted-open-feedback-v1','study_session_id':public_id,'instrument_version':feedback.instrument_version,
       'submitted_at':feedback.submitted_at.isoformat(),'open_feedback':json.loads(feedback.open_feedback_json),
       'usage':'Local authorized coding only; de-identify quotations; register derivative analysis files.'}
    write_json(path,payload)
    try:register_artifact(root,path,[public_id])
    except Exception:
        path.unlink(missing_ok=True);raise
    audit={'operation':'feedback_export','operator':operator,'subject_sha256':hashed,'at':utc_now().isoformat(),
           'artifact':path.relative_to(root).as_posix(),'record_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    write_json(root/'audit'/f'{secrets.token_hex(12)}.json',audit)
    return {'file':str(path),'record_sha256':audit['record_sha256'],'raw_text_printed':False}

def resolve_subject(db,research_id,email,root,operator):
    from study.participant_service import normalize_email,email_digest
    contact=db.query(study_models.StudyContactRecord).filter_by(research_id=research_id.strip().upper()).one_or_none()
    expected=email_digest(normalize_email(email))
    if contact is None or not hmac.compare_digest(contact.email_sha256,expected):
        raise StudyWorkflowError('Research ID and email do not match.',404,'subject_not_found')
    session=db.get(study_models.StudySession,contact.study_session_id)
    write_json(storage_root(root)/'audit'/f'{secrets.token_hex(12)}.json',{
        'operation':'resolve_subject','operator':operator,'subject_sha256':subject(session.public_id),'at':utc_now().isoformat()})
    return {'study_session_id':session.public_id,'state':session.state}

def row_closure(db,session):
    """Follow declared foreign keys; fail if ownership would cross a session."""
    tables=Base.metadata.tables
    selected={'study_sessions':{(session.id,)}}
    if session.world_session_id is not None:selected['sessions']={(session.world_session_id,)}
    excluded={'study_compensation_cases','study_compensation_audits'}
    changed=True
    while changed:
        changed=False
        for table in tables.values():
            if table.name in excluded:continue
            predicates=[]
            for fk in table.foreign_keys:
                parent=fk.column.table
                if parent.name not in selected:continue
                pk=list(parent.primary_key.columns)
                if len(pk)!=1 or fk.column.name!=pk[0].name:raise ValueError('Unsupported FK in erasure graph.')
                values=[row[0] for row in selected[parent.name]]
                if values:predicates.append(fk.parent.in_(values))
            if not predicates:continue
            rows=db.execute(select(table).where(or_(*predicates))).mappings().all()
            for row in rows:
                if 'study_session_id' in row and row['study_session_id'] not in (None,session.id):raise ValueError('Cross-study ownership; erasure stopped.')
                if table.name not in ('study_sessions',) and 'session_id' in row and row['session_id'] not in (None,session.world_session_id):raise ValueError('Cross-world ownership; erasure stopped.')
                key=tuple(row[col.name] for col in table.primary_key.columns)
                if key not in selected.setdefault(table.name,set()):selected[table.name].add(key);changed=True
    return selected

def erase_database(db,public_id):
    session=db.query(study_models.StudySession).filter_by(public_id=public_id).one_or_none()
    if session is None:return {'rows':0,'administrative_case_retained':False}
    selected=row_closure(db,session)
    case=db.query(study_models.StudyCompensationCase).filter_by(study_session_id=session.id).one_or_none()
    case_id=case.id if case else None
    session_id=session.id
    # Detach the world pointer before deleting world records. Retained payment
    # audits use a non-recoverable administrative stub, never the research ID.
    db.execute(update(study_models.StudySession).where(study_models.StudySession.id==session_id).values(world_session_id=None))
    count=0
    for table in reversed(Base.metadata.sorted_tables):
        if table.name=='study_sessions' or table.name not in selected:continue
        pk=list(table.primary_key.columns)
        if len(pk)!=1:raise ValueError('Unsupported composite erasure key.')
        keys=[r[0] for r in selected[table.name]]
        if keys: count+=db.execute(delete(table).where(pk[0].in_(keys))).rowcount
    if case_id is None:
        db.execute(delete(study_models.StudySession).where(study_models.StudySession.id==session_id));count+=1
    else:
        db.execute(update(study_models.StudySession).where(study_models.StudySession.id==session_id).values(
            public_id='erased_admin_'+secrets.token_hex(20),creation_idempotency_key='erased_'+secrets.token_hex(20),
            recovery_token_hash=secrets.token_hex(32),recovery_token_expires_at=utc_now(),
            workflow_version='deleted-admin-stub',state='withdrawn',terminal_reason_code='research_data_deleted',
            completed_at=None,compensation_stage='restricted_payment_record',world_session_id=None))
    db.commit();db.expire_all()
    return {'rows':count,'administrative_case_retained':case_id is not None,'administrative_case_id':case_id}

def scrub_sqlite(path,hashes):
    engine=create_engine('sqlite:///'+Path(path).as_posix())
    @event.listens_for(engine,'connect')
    def configure(conn,_):
        conn.execute('PRAGMA foreign_keys=ON');conn.execute('PRAGMA secure_delete=ON')
    try:
        # Old managed backups may predate additive research tables.
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            ids=[value for (value,) in db.query(study_models.StudySession.public_id).all() if subject(value) in hashes]
            results=[erase_database(db,value) for value in ids]
        with engine.connect() as c:
            c.exec_driver_sql('PRAGMA wal_checkpoint(TRUNCATE)')
            c.exec_driver_sql('VACUUM')
            if c.exec_driver_sql('PRAGMA foreign_key_check').all():raise ValueError('Foreign-key verification failed.')
        return sum(x['rows'] for x in results)
    finally:engine.dispose()

def erase(db,public_id,root,operator,request_id):
    from study.maintenance_lock import maintenance_lock
    root=storage_root(root)
    with maintenance_lock(root):
        return _erase_locked(db,public_id,root,operator,request_id)

def _erase_locked(db,public_id,root,operator,request_id):
    root=storage_root(root);hashed=subject(public_id)
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',request_id):raise ValueError('Use a non-identifying request ID.')
    ledger=root/'deletions'/f'{hashed}.json'
    info=json.loads(ledger.read_text(encoding='utf8')) if ledger.exists() else {
        'subject_sha256':hashed,'request_id':request_id,'operator':operator,'requested_at':utc_now().isoformat()}
    info['status']='pending';write_json(ledger,info)  # durable revocation before writes
    db.connection().exec_driver_sql('PRAGMA secure_delete=ON')
    outcome=erase_database(db,public_id)
    removed=[]
    for manifest in (root/'artifacts').glob('*.json'):
        entry=json.loads(manifest.read_text(encoding='utf8'))
        if hashed not in entry['subjects']:continue
        file=contained(root,entry['relative_path'])
        if Path(entry['relative_path']).parts[0] not in ('participants','analysis'):raise ValueError('Invalid artifact scope.')
        file.unlink(missing_ok=True);removed.append(entry['relative_path']);manifest.unlink()
    backup_rows=0
    for file in (root/'backups').glob('*.sqlite'):
        contained(root,file.relative_to(root).as_posix())
        backup_rows+=scrub_sqlite(file,{hashed})
    info.update(status='managed_copies_erased',completed_at=utc_now().isoformat(),database=outcome,
       removed_artifacts=len(removed),backup_rows_removed=backup_rows,
       external_copies_status='operator_reconciliation_required')
    write_json(ledger,info)
    return info

def reconcile_restored_database(db,root):
    root=storage_root(root)
    hashes={p.stem for p in (root/'deletions').glob('*.json')}
    ids=[value for (value,) in db.query(study_models.StudySession.public_id).all() if subject(value) in hashes]
    return [erase_database(db,value) for value in ids]

def revoked(public_id):
    value=os.getenv('STUDY_RESEARCH_STORAGE_ROOT')
    if not value:return False
    return (storage_root(value)/'deletions'/f'{subject(public_id)}.json').exists()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--operator',required=True)
    sub=p.add_subparsers(dest='operation',required=True)
    for name in ('feedback','delete'):
        cmd=sub.add_parser(name);cmd.add_argument('--session',required=True)
        if name=='delete':cmd.add_argument('--request-id',required=True)
    sub.add_parser('reconcile-restored')
    sub.add_parser('resolve-subject')
    cmd=sub.add_parser('register-analysis');cmd.add_argument('--file',type=Path,required=True);cmd.add_argument('--sessions',nargs='+',required=True)
    args=p.parse_args()
    if not os.getenv('DATABASE_URL'):p.error('Set DATABASE_URL explicitly; never use the default demo database.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',args.operator):p.error('Use a short operator account label.')
    root=storage_root()
    from database import SessionLocal
    with SessionLocal() as db:
        if args.operation=='feedback':result=export_feedback(db,args.session,root,args.operator)
        elif args.operation=='delete':result=erase(db,args.session,root,args.operator,args.request_id)
        elif args.operation=='register-analysis':
            register_artifact(root,args.file,args.sessions);result={'registered':True}
        elif args.operation=='resolve-subject':
            from getpass import getpass
            result=resolve_subject(db,getpass('Research ID (hidden): '),getpass('Registered email (hidden): '),root,args.operator)
        else:result={'reconciled':reconcile_restored_database(db,root)}
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
