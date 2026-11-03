#!/usr/bin/env python3
"""Tests for the analysis.

    $PY analysis/test_analysis.py           all of them (the audio tests need numpy)
    $PY analysis/test_analysis.py moves     only tests whose name contains "moves"
"""
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import rekordbox_log as rl  # noqa: E402
from moves import find_moves, Timeline, window_lines, parse_time, stamp  # noqa: E402

HEADER = {'type': 'session', 'v': 1, 'wall': '2026-11-04T21:00:00.000+05:30', 'offset_ms': 0}


def c(t, ctl, v):
    return {'t': round(t, 3), 'type': 'ctl', 'src': 'DDJ-FLX4', 'ctl': ctl, 'v': v}


def fade(ctl, t0, t1, a, b, step=0.05):
    n = max(1, int(round((t1 - t0) / step)))
    return [c(t0 + i * (t1 - t0) / n, ctl, round(a + (b - a) * i / n, 3)) for i in range(n + 1)]


def press(t, ctl):
    return [c(t, ctl, 1), c(t, ctl, 0)]


def base(*extra):
    """Deck 1 playing from 0. Deck 2 loaded at 5 with its fader down, playing from 10."""
    ev = press(0, 'deck1.play') + press(5, 'deck2.load') + fade('deck2.fader', 5, 5.2, 1, 0) + press(10, 'deck2.play')
    for x in extra:
        ev += x
    return sorted(ev, key=lambda e: e['t'])


def styles(ctls, start, swap=None, end=None, drops=(), A=1, B=2):
    from techniques import Window, label_transition
    tl, mv = Timeline(ctls), find_moves(ctls)
    lab = label_transition(Window(tl, mv, A, B, start, swap if swap is not None else start, end, None, drops))
    return lab['styles'], lab


def bring_in(t0=20, t1=21):
    return fade('deck2.fader', t0, t1, 0, 1)


def take_out(t0=40, t1=41):
    return fade('deck1.fader', t0, t1, 1, 0)


def test_moves():
    ev = fade('mixer.crossfader', 0, 0.3, 0.5, 1.0) + fade('mixer.crossfader', 0.35, 0.6, 1.0, 0.0)
    ev += [c(1 + i * 0.05, 'deck1.jog', -5) for i in range(8)] + press(2, 'deck1.play') + [c(3, 'deck1.eq.low', 0.2)]
    mv = find_moves(sorted(ev, key=lambda e: e['t']))
    xf = [m for m in mv if m['ctl'] == 'mixer.crossfader']
    assert [(m['from'], m['to']) for m in xf] == [(0.5, 1.0), (1.0, 0.0)], xf  # one move per direction
    (jog,) = [m for m in mv if m['ctl'] == 'deck1.jog']
    assert jog['steps'] == -40 and jog['n'] == 8, jog
    assert [m for m in mv if m['ctl'] == 'deck1.play'] == [{'start': 2, 'end': 2, 'ctl': 'deck1.play', 'n': 1}]
    (eq,) = [m for m in mv if m['ctl'] == 'deck1.eq.low']
    assert eq['from'] == eq['to'] == 0.2  # a first move starts at its own first value
    gap = find_moves(fade('deck1.fader', 0, 1, 1, 0.5) + fade('deck1.fader', 2, 3, 0.5, 0))
    assert [(m['from'], m['to']) for m in gap] == [(1, 0.5), (0.5, 0)], gap  # a pause starts a new move
    assert window_lines(mv, 0.9, 1.5) == ['0:01.0-0:01.3  deck1.jog  -40 steps  (8)']
    assert parse_time('1:02:03') == 3723 and parse_time('14:02') == 842 and parse_time('9.5') == 9.5
    assert stamp(3723) == '1:02:03' and stamp(62.34, True) == '1:02.3'


def test_timeline():
    tl = Timeline(base(bring_in(), fade('mixer.crossfader', 30, 30.2, 0.5, 1.0)))
    assert tl.level(2, 9) == 0 and tl.level(2, 15) == 0 and tl.level(2, 22) == 1.0
    assert tl.value('deck1.eq.low', 1) == 0.5 and tl.value('deck1.fader', 1) == 1.0  # untouched: usual spot
    assert tl.level(1, 31) == 0.0 and tl.level(2, 31) == 1.0  # crossfader hard to deck 2


if __name__ == '__main__':
    only = sys.argv[1] if len(sys.argv) > 1 else ''
    if not only:
        rl.selftest()
    for name, fn in list(globals().items()):
        if name.startswith('test_') and only in name:
            out = fn()
            print(f'{name} ok' + (f' ({out} lines)' if out else ''))
