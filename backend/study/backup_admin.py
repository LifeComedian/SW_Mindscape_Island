"""Managed online SQLite backups, sharing the erasure lock. Linux timer entry point."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

from study.maintenance_lock import maintenance_lock
from study.research_admin import storage_root, contained, scrub_sqlite, write_json


def verify(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:
            raise ValueError('Backup integrity check failed')
        if conn.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Backup foreign-key check failed')


def backup(source, root, *, now=None):
    source=Path(source).absolute(); root=storage_root(root)
    if not source.is_file() or source.is_symlink():
        raise ValueError('An existing database is required')
    source=source.resolve()
    now=now or datetime.now(timezone.utc)
    with maintenance_lock(root):
        folder=contained(root,'backups');folder.mkdir(exist_ok=True,mode=0o700)
        if shutil.disk_usage(folder).free < max(512*1024*1024,source.stat().st_size*3):
            raise ValueError('Insufficient backup disk space')
        stamp=now.strftime('%Y%m%dT%H%M%SZ')
        target=contained(root,'backups/auto-quarter-'+stamp+'.sqlite')
        if target.exists():raise ValueError('Backup target already exists')
        temporary=contained(root,'backups/.pending-'+uuid.uuid4().hex)
        try:
            with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=30)) as src:
                with closing(sqlite3.connect(temporary)) as dest:
                    src.backup(dest,pages=256,sleep=0.01)
            os.chmod(temporary,0o600)
            hashes={p.stem for p in (root/'deletions').glob('*.json')}
            if hashes:scrub_sqlite(temporary,hashes)
            # Publish a standalone database, never a file depending on a WAL sidecar.
            with closing(sqlite3.connect(temporary)) as checkpoint:
                checkpoint.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                checkpoint.execute('PRAGMA journal_mode=DELETE')
            verify(temporary)
            with temporary.open('r+b') as handle:os.fsync(handle.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
            for suffix in ('-wal','-shm','-journal'):
                temporary.with_name(temporary.name+suffix).unlink(missing_ok=True)
        daily=contained(root,'backups/auto-daily-'+now.strftime('%Y%m%d')+'.sqlite')
        if not daily.exists():
            # Keep independent files: erasure must scrub each managed copy.
            daily_temp=contained(root,'backups/.pending-'+uuid.uuid4().hex)
            try:
                shutil.copyfile(target,daily_temp);os.chmod(daily_temp,0o600)
                with daily_temp.open('r+b') as handle:os.fsync(handle.fileno())
                daily_temp.replace(daily)
            finally:daily_temp.unlink(missing_ok=True)
        # Only prune filenames owned by this scheduler, never manual backups.
        removed=0
        for prefix,fmt,limit in [('auto-quarter-','%Y%m%dT%H%M%SZ',now-timedelta(hours=24)),('auto-daily-','%Y%m%d',now-timedelta(days=7))]:
            for path in folder.glob(prefix+'*.sqlite'):
                contained(root,path.relative_to(root).as_posix())
                try:created=datetime.strptime(path.stem[len(prefix):],fmt).replace(tzinfo=timezone.utc)
                except ValueError:continue
                if created<limit:path.unlink();removed+=1
        result={'status':'verified','created_at':now.isoformat(),'file':target.relative_to(root).as_posix(),
            'bytes':target.stat().st_size,'sha256_at_creation':hashlib.sha256(target.read_bytes()).hexdigest(),
            'deleted_subjects_reconciled':len(hashes),'pruned':removed,
            'quarter_hour_retention_hours':24,'daily_retention_days':7,
            'off_host_copy':False}
        write_json(root/'backup-status.json',result)
        return result


if __name__=='__main__':
    url=os.environ.get('DATABASE_URL','')
    if not url.startswith('sqlite:////'):raise SystemExit('An absolute Linux SQLite database URL is required')
    print(json.dumps(backup(Path(url.removeprefix('sqlite:///')),storage_root()),ensure_ascii=False))
