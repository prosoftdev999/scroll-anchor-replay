#!/usr/bin/env python3
"""Small trace browser for the supplied capture files."""
import argparse, csv, json
from pathlib import Path

DATA = Path('/app/data')

def rows(name):
    with (DATA/name).open(newline='') as f:
        return list(csv.DictReader(f))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('session', nargs='?', help='session id, for example s-z62')
    args = ap.parse_args()
    sessions = rows('sessions.csv')
    if not args.session:
        for r in sessions:
            print(f"{r['session']:8s} {r['role']:8s} initial_scroll={r['initial_scroll_top_css']}")
        return
    sid = args.session
    if sid not in {r['session'] for r in sessions}:
        raise SystemExit(f'unknown session: {sid}')
    print('UI events')
    for r in rows('ui_events.csv'):
        if r['session'] == sid:
            print(r)
    print('\nCompositor events')
    for r in rows('compositor_events.csv'):
        if r['session'] == sid:
            print(r)
    print('\nControl observations')
    for r in rows('control_checkpoints.csv'):
        if r['session'] == sid:
            print(r)
    print('\nRequested incident checkpoints')
    for r in rows('incident_checkpoints.csv'):
        if r['session'] == sid:
            print(r)

if __name__ == '__main__':
    main()
