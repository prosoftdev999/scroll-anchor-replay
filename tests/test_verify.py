import json
import math
import os
from pathlib import Path

ARTIFACT = Path(os.environ.get('TASK_OUTPUT', '/app/output/recovered.json'))
ORACLE = Path(os.environ.get('TASK_ORACLE', '/tests/oracle.json'))
TOL = 0.02
NUMERIC_FIELDS = ('scroll_top_css', 'visual_scroll_css', 'marker_offset_css', 'pending_input_css', 'effective_scroll_css')


def load_json(path):
    with path.open() as f:
        return json.load(f)


def test_schema_and_checkpoint_set():
    got = load_json(ARTIFACT)
    ref = load_json(ORACLE)
    assert isinstance(got, dict)
    assert set(got) == {'schema_version', 'checkpoints'}
    assert got['schema_version'] == 3
    assert isinstance(got['checkpoints'], list)
    assert len(got['checkpoints']) == len(ref['checkpoints'])
    assert [r.get('checkpoint_id') for r in got['checkpoints']] == [r['checkpoint_id'] for r in ref['checkpoints']]
    expected_keys = {
        'checkpoint_id', 'scroll_top_css', 'paint_frame', 'tree_revision',
        'visual_scroll_css', 'marker_item', 'marker_offset_css', 'render_commit',
        'pending_input_css', 'effective_scroll_css'
    }
    for row in got['checkpoints']:
        assert set(row) == expected_keys
        assert isinstance(row['paint_frame'], str) and row['paint_frame']
        assert isinstance(row['tree_revision'], int) and not isinstance(row['tree_revision'], bool)
        assert isinstance(row['marker_item'], str) and row['marker_item']
        assert isinstance(row['render_commit'], str) and row['render_commit']
        for key in NUMERIC_FIELDS:
            assert isinstance(row[key], (int, float)) and not isinstance(row[key], bool)
            assert math.isfinite(float(row[key]))


def test_reconstructed_state():
    got = load_json(ARTIFACT)
    ref = load_json(ORACLE)
    for actual, expected in zip(got['checkpoints'], ref['checkpoints']):
        assert actual['paint_frame'] == expected['paint_frame']
        assert actual['tree_revision'] == expected['tree_revision']
        assert actual['marker_item'] == expected['marker_item']
        assert actual['render_commit'] == expected['render_commit']
        for key in NUMERIC_FIELDS:
            assert abs(float(actual[key]) - float(expected[key])) <= TOL
