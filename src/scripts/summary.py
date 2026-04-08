#!/usr/bin/env python3
import argparse
import logging
import queue
import sys
import threading
import time
from typing import NamedTuple

import redfish

from idrac.idracaccessor import IdracAccessor, ilogger
from idrac.issuedb import IssueDB, DEFAULT_DB
from scripts import get_password, IdracSelector

"""Command line driver"""

THREAD_TIMEOUT = 60

results: queue.Queue = queue.Queue()


class ServerResult(NamedTuple):
    name: str
    summary: object
    alerts: list
    alert_error: str | None


def get_summary(name):
    try:
        with IdracAccessor() as accessor:
            idrac = accessor.connect(name, get_password)
            s = idrac.summary
            alerts = []
            alert_error = None
            if s.health != 'OK' or s.power != 'On':
                try:
                    faults = idrac.active_faults()
                    sel = idrac.recent_alerts()
                    # Faults first; append SEL entries not already covered by a fault
                    fault_messages = {f.get('Message', '') for f in faults}
                    combined = faults + [e for e in sel if e.get('Message', '') not in fault_messages]
                    # Drop OK-severity entries — they don't explain non-OK health
                    alerts = [a for a in combined if a.get('Severity', 'OK') != 'OK']
                    # Fault log unavailable or cleared; walk subsystem health directly
                    if not alerts:
                        alerts = idrac.component_health_issues()
                except Exception as e:
                    alert_error = str(e)
            results.put(ServerResult(name, s, alerts, alert_error))
    except Exception as e:
        print(f"{name} {e}", file=sys.stderr)


def _collect(threads: set) -> tuple[list[ServerResult], list[str]]:
    """Wait up to THREAD_TIMEOUT seconds for all threads; return results and names of timed-out threads"""
    deadline = time.monotonic() + THREAD_TIMEOUT
    for t in threads:
        remaining = deadline - time.monotonic()
        t.join(timeout=max(remaining, 0))

    timed_out = sorted(t.name for t in threads if t.is_alive())

    items = []
    try:
        while True:
            items.append(results.get_nowait())
    except queue.Empty:
        pass
    return sorted(items, key=lambda r: r.name), timed_out


def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    selector = IdracSelector(parser)
    parser.add_argument('--all', action='store_true', dest='show_all',
                        help="Show all servers, not just those with new issues")
    parser.add_argument('--db', default=str(DEFAULT_DB), help="SQLite database path for issue tracking")

    idracs = selector.idracs  # also configures log levels
    args = parser.parse_args()

    threads = set()
    with IssueDB(args.db) as db:
        for idrac_name in idracs:
            if db.recently_sampled(idrac_name):
                ilogger.debug(f"{idrac_name} sampled within last hour, skipping")
                continue
            t = threading.Thread(target=get_summary, args=(idrac_name,), name=idrac_name)
            threads.add(t)
            t.start()

        all_results, timed_out = _collect(threads)

        for name in timed_out:
            print(f"{name} timed out after {THREAD_TIMEOUT}s", file=sys.stderr)

        for res in all_results:
            db.record_sampled(res.name)

            new_issues = db.new_issues(res.name, res.alerts) if res.alerts else []
            has_health_issue = res.summary.health != 'OK' or res.summary.power != 'On'

            if not args.show_all:
                if not res.alert_error and not new_issues and not (has_health_issue and not res.alerts):
                    continue

            print(res.summary)
            if res.alert_error:
                print(f"  (could not read logs: {res.alert_error})")
            for entry in new_issues:
                severity = entry.get('Severity', '')
                message = entry.get('Message', entry.get('Name', ''))
                created = entry.get('Created', '')
                print(f"  [{severity}] {created} {message}")

            if new_issues:
                try:
                    ans = input(f"Acknowledge {len(new_issues)} issue(s) for {res.name}? [y/N] ").strip().lower()
                    if ans == 'y':
                        db.acknowledge_all(res.name, new_issues)
                        print("  Acknowledged.")
                except EOFError:
                    pass  # non-interactive mode


if __name__ == "__main__":
    main()
