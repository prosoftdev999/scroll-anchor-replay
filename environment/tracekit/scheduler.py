#!/usr/bin/env python3
"""Recover the virtualizer scheduler profile from healthy calibration traces."""
import csv
from itertools import permutations
from pathlib import Path

LANES = ('ln-a7', 'ln-c2', 'ln-f9', 'ln-k4')
RANK_VALUES = (0, 2, 4, 6)


def _read_csv(data: Path, name: str):
    with (data / name).open(newline='') as f:
        return list(csv.DictReader(f))


def _lane_ranks(policy):
    return {lane: RANK_VALUES[::-1][i] for i, lane in enumerate(policy['lane_order'])}


def simulate(updates, slices, policy):
    """Replay cooperative work and return cumulative state after each scheduler slice."""
    ranks = _lane_ranks(policy)
    state = {
        u['update_token']: {
            'remaining': int(u['cost_units']),
            'started': False,
            'completed': False,
            'committed': False,
        }
        for u in updates
    }
    by_token = {u['update_token']: u for u in updates}
    groups = {}
    for u in updates:
        if u['group_token']:
            groups.setdefault(u['group_token'], []).append(u['update_token'])

    result = {}
    for sl in slices:
        now = float(sl['ui_ms'])
        for _ in range(int(sl['budget_units'])):
            best = None
            for idx, u in enumerate(updates):
                s = state[u['update_token']]
                if s['completed'] or float(u['enqueue_ms']) > now + 1e-9:
                    continue
                dep = u['after_token']
                if dep and not state[dep]['completed']:
                    continue

                age = min(
                    policy['age_cap'],
                    int(max(0.0, now - float(u['enqueue_ms'])) // policy['age_quantum']),
                )
                group_term = 0
                if u['group_token']:
                    peers = groups[u['group_token']]
                    if any(
                        t != u['update_token']
                        and not state[t]['completed']
                        and float(by_token[t]['enqueue_ms']) <= now + 1e-9
                        for t in peers
                    ):
                        group_term = policy['group_bonus']

                score = (
                    ranks[u['lane_token']]
                    + policy['age_weight'] * age
                    + group_term
                    - policy['resume_penalty'] * int(s['started'] and s['remaining'] > 0)
                )
                if policy['tie_break'] == 'oldest':
                    tie = (-float(u['enqueue_ms']), -idx)
                else:
                    tie = (-s['remaining'], -float(u['enqueue_ms']), -idx)
                candidate = (score, tie, idx, u)
                if best is None or (candidate[0], candidate[1]) > (best[0], best[1]):
                    best = candidate

            if best is None:
                break
            u = best[3]
            s = state[u['update_token']]
            s['started'] = True
            s['remaining'] -= 1
            if s['remaining'] == 0:
                s['completed'] = True

        for u in updates:
            if not u['group_token'] and state[u['update_token']]['completed']:
                state[u['update_token']]['committed'] = True

        for _, members in groups.items():
            if policy['commit_mode'] == 'atomic':
                if all(state[token]['completed'] for token in members):
                    for token in members:
                        state[token]['committed'] = True
            else:
                ordered = [u['update_token'] for u in updates if u['group_token'] and u['update_token'] in members]
                for token in ordered:
                    if state[token]['completed']:
                        state[token]['committed'] = True
                    else:
                        break

        committed = [u for u in updates if state[u['update_token']]['committed']]
        result[sl['slice_id']] = {
            'committed_count': len(committed),
            'height_sum_css': round(sum(float(u['height_delta_css']) for u in committed), 4),
            'scroll_adjust_css': round(sum(float(u['scroll_adjust_css']) for u in committed), 4),
            'pending_units': sum(s['remaining'] for s in state.values() if not s['completed']),
            'held_count': sum(
                1 for u in updates
                if state[u['update_token']]['completed'] and not state[u['update_token']]['committed']
            ),
            'committed_tokens': tuple(u['update_token'] for u in committed),
        }
    return result
