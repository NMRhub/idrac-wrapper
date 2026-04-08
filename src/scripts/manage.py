#!/usr/bin/env python3
import argparse
import sys

from idrac.issuedb import IssueDB, DEFAULT_DB


def main():
    parser = argparse.ArgumentParser(
        description="Manage the iDRAC issue tracking database",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--db', default=str(DEFAULT_DB), help="SQLite database path")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--delete', action='append',metavar='IDRAC', help="Remove all records for an iDRAC")
    group.add_argument('--list', action='store_true', help="List all iDRACs tracked in the database")
    group.add_argument('--active', action='store_true', help="List all unacknowledged issues")

    args = parser.parse_args()

    with IssueDB(args.db) as db:
        if args.delete:
            for idr in args.delete:
                issues, sampled = db.delete(idr)
                if issues == 0 and sampled == 0:
                    print(f"{idr}: not found in database", file=sys.stderr)
                print(f"{idr}: removed {issues} issue(s) and {sampled} sampled record(s)")
        elif args.list:
            rows = db.conn.execute(
                "SELECT s.idrac, s.last_sampled, "
                "COUNT(i.id) AS total, "
                "SUM(CASE WHEN i.acknowledged=0 THEN 1 ELSE 0 END) AS unacked "
                "FROM sampled s "
                "LEFT JOIN issues i ON s.idrac = i.idrac "
                "GROUP BY s.idrac "
                "ORDER BY s.idrac"
            ).fetchall()
            if not rows:
                print("No iDRACs in database.")
            else:
                print(f"{'iDRAC':<40} {'last sampled':<30} {'issues':>6} {'unacked':>7}")
                print("-" * 87)
                for idrac, last_sampled, total, unacked in rows:
                    print(f"{idrac:<40} {last_sampled:<30} {total or 0:>6} {unacked or 0:>7}")

        elif args.active:
            rows = db.conn.execute(
                "SELECT idrac, severity, created, message, first_seen "
                "FROM issues "
                "WHERE acknowledged=0 "
                "ORDER BY idrac, first_seen"
            ).fetchall()
            if not rows:
                print("No active issues.")
            else:
                print(f"{'iDRAC':<40} {'sev':<10} {'created':<32} message")
                print("-" * 120)
                for idrac, severity, created, message, first_seen in rows:
                    print(f"{idrac:<40} {severity or '':<10} {created or '':<32} {message or ''}")


if __name__ == "__main__":
    main()
