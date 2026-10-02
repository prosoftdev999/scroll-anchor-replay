import csv
from pathlib import Path


def _rows(data: Path, name: str):
    with (data / name).open(newline='') as f:
        return list(csv.DictReader(f))


def _broker_fit(data: Path, session: str):
    rows = [r for r in _rows(data, 'broker_clock_sync.csv') if r['session'] == session]
    xs = [float(r['comp_us']) for r in rows]
    ys = [float(r['broker_us']) for r in rows]
    n = len(xs)
    sx = sum(xs); sy = sum(ys)
    sxx = sum(x*x for x in xs); sxy = sum(x*y for x,y in zip(xs,ys))
    den = n*sxx - sx*sx
    if n < 2 or den == 0:
        raise RuntimeError('broker clock is not identifiable')
    a = (n*sxy - sx*sy) / den
    b = (sy - a*sx) / n
    return a, b


def recover_geometry_overlays(data: Path, paint_frames):
    lifetimes = _rows(data, 'geometry_handoff_lifetimes.csv')
    refs = _rows(data, 'frame_geometry_refs.csv')
    offers = _rows(data, 'geometry_offers.csv')
    events = _rows(data, 'geometry_browser_events.csv')
    commit_rows = _rows(data, 'geometry_commits.csv')
    aliases = _rows(data, 'geometry_alias_lifetimes.csv')

    frame_map = {(r['session'], r['frame_id']): r for r in paint_frames}
    offers_by_key = {}
    for r in offers:
        offers_by_key.setdefault((r['session'], r['handoff_token'], int(r['generation'])), {})[int(r['offer_seq'])] = r
    events_by_key = {}
    for r in events:
        events_by_key.setdefault((r['session'], r['handoff_token'], int(r['generation'])), []).append(r)
    for rows in events_by_key.values():
        rows.sort(key=lambda r: (float(r['broker_us']), int(r['event_seq'])))

    meta = {}
    deltas = {}
    for r in commit_rows:
        cid = r['commit_id']; cseq = int(r['commit_seq'])
        cur = (r['parent_commit_id'], cseq)
        if cid in meta and meta[cid] != cur:
            raise RuntimeError(f'inconsistent geometry commit metadata for {cid}')
        meta[cid] = cur
        if r['item_alias']:
            deltas.setdefault(cid, []).append((int(r['delta_seq']), r['item_alias'], float(r['height_delta_css']), float(r['origin_delta_css'])))
        elif float(r['origin_delta_css']) != 0:
            deltas.setdefault(cid, []).append((int(r['delta_seq']), '', 0.0, float(r['origin_delta_css'])))

    def item_for(alias, commit_seq):
        matches = [r for r in aliases if r['alias_token'] == alias and int(r['first_commit_seq']) <= commit_seq <= int(r['last_commit_seq'])]
        if len(matches) != 1:
            raise RuntimeError(f'geometry alias {alias} has {len(matches)} identities at commit {commit_seq}')
        return matches[0]['item_id']

    def lineage(head):
        out=[]; seen=set(); cur=head
        while cur:
            if cur in seen or cur not in meta:
                raise RuntimeError('invalid geometry commit lineage')
            seen.add(cur); out.append(cur); cur=meta[cur][0]
        out.reverse()
        return out

    fits = {}
    result = {}
    for ref in refs:
        key=(ref['session'], ref['frame_id'])
        if key not in frame_map:
            raise RuntimeError(f'geometry ref names unknown frame {key}')
        fr=frame_map[key]; comp=float(fr['comp_us']); sid=ref['session']; token=ref['handoff_token']
        lm=[r for r in lifetimes if r['session']==sid and r['handoff_token']==token and float(r['start_comp_us']) <= comp <= float(r['end_comp_us'])]
        if len(lm)!=1:
            raise RuntimeError(f'geometry handoff {token} has {len(lm)} generations at frame time')
        generation=int(lm[0]['generation']); k=(sid,token,generation)
        if sid not in fits: fits[sid]=_broker_fit(data,sid)
        a,b=fits[sid]; broker_cutoff=a*comp+b

        accepted=set()
        for e in events_by_key.get(k,[]):
            if float(e['broker_us']) > broker_cutoff:
                break
            seq=int(e['offer_seq'])
            if e['action']=='accept':
                accepted.add(seq)
            elif e['action']=='revoke':
                accepted.discard(seq)
            else:
                raise RuntimeError(f"unknown geometry browser action {e['action']}")

        heads=[]
        for seq in accepted:
            offer=offers_by_key.get(k,{}).get(seq)
            if not offer:
                continue
            if float(offer['offered_comp_us']) <= comp and float(offer['install_barrier_comp_us']) <= comp:
                heads.append(offer['head_commit'])
        if not heads:
            raise RuntimeError(f'no installed geometry branch for {key}')

        # Multiple browser-accepted speculative branches expose only their
        # deepest common committed prefix until one of them is revoked.
        ancestor_sets=[set(lineage(head)) for head in heads]
        common=set.intersection(*ancestor_sets)
        if not common:
            raise RuntimeError('accepted geometry branches have no common root')
        best_seq=max(meta[cid][1] for cid in common)
        deepest=[cid for cid in common if meta[cid][1]==best_seq]
        if len(deepest)!=1:
            raise RuntimeError('geometry common prefix is not unique')
        head=deepest[0]

        height_deltas={}; origin=0.0
        for cid in lineage(head):
            _,cseq=meta[cid]
            for _,alias,hd,od in sorted(deltas.get(cid, [])):
                if alias:
                    item=item_for(alias,cseq)
                    height_deltas[item]=height_deltas.get(item,0.0)+hd
                origin += od
        result[key]={'head_commit':head,'height_deltas':height_deltas,'origin_adjust_css':origin}
    return result
