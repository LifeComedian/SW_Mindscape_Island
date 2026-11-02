"""Local-only operator CLI. Run with an explicit DATABASE_URL; no HTTP admin surface."""
from __future__ import annotations
import argparse
from datetime import timedelta
import json
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    issue = commands.add_parser("issue")
    issue.add_argument("--batch", required=True)
    issue.add_argument("--count", type=int, default=1)
    issue.add_argument("--days", type=int, default=14)
    recover = commands.add_parser("recover")
    recover.add_argument("--session", required=True)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("--id", type=int, required=True)
    commands.add_parser("lookup-receipt")
    case = commands.add_parser("open-compensation")
    case.add_argument("--session", required=True)
    payment = commands.add_parser("update-compensation")
    payment.add_argument("--case", type=int, required=True)
    payment.add_argument("--operation", required=True, choices=["approve_manual", "claim", "record_paid", "release_claim", "correct_paid_record"])
    payment.add_argument("--revision", type=int, required=True)
    payment.add_argument("--key", required=True)
    payment.add_argument("--reason", required=True)
    payment.add_argument("--amount-fen", type=int)
    args = parser.parse_args()
    if not os.getenv("DATABASE_URL"):
        parser.error("Set DATABASE_URL explicitly to the intended synthetic or approved production database.")
    from database import SessionLocal
    from study.access import issue_invitation, revoke_invitation
    from study.models import StudySession
    with SessionLocal() as db:
        if args.command == "lookup-receipt":
            from getpass import getpass
            from study.compensation_admin import lookup_receipt
            print(json.dumps(lookup_receipt(db, getpass("Completion code (hidden): "))))
        elif args.command == "open-compensation":
            from study.compensation_admin import open_case
            print(json.dumps(open_case(db, public_id=args.session)))
        elif args.command == "update-compensation":
            from study.compensation_admin import update_case
            print(json.dumps(update_case(db, case_id=args.case, operation=args.operation, expected_revision=args.revision,
                operator=args.operator, idempotency_key=args.key, reason_code=args.reason, amount_fen=args.amount_fen)))
        elif args.command == "revoke":
            revoke_invitation(db, args.id, operator=args.operator)
            print(json.dumps({"revoked": args.id}))
        elif args.command == "recover":
            session = db.query(StudySession).filter_by(public_id=args.session).one()
            row, code = issue_invitation(db, batch="operator-recovery", operator=args.operator,
                ttl=timedelta(hours=24), recovery_session=session)
            print(json.dumps({"id": row.id, "recovery_code": code, "expires_at": str(row.expires_at)}))
        else:
            if not 1 <= args.count <= 100:
                parser.error("Batch size must be 1..100.")
            for _ in range(args.count):
                row, code = issue_invitation(db, batch=args.batch, operator=args.operator, ttl=timedelta(days=args.days))
                print(json.dumps({"id": row.id, "invitation_code": code, "expires_at": str(row.expires_at)}))


if __name__ == "__main__":
    main()
