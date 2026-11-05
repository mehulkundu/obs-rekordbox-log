#!/usr/bin/env python3
"""Tests for the analysis.

    python3 analysis/test_analysis.py           all of them (the audio tests need numpy)
    python3 analysis/test_analysis.py moves     only tests whose name contains "moves"
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


# --- moves ---------------------------------------------------------------------------------------

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


# --- transition rules: each one just meets and just misses -----------------------------------------

def test_bass_swap():
    swap = fade('deck2.eq.low', 9, 9.3, 0.5, 0.0) + fade('deck2.eq.low', 30, 31, 0, 0.5)
    s, lab = styles(base(bring_in(), swap, fade('deck1.eq.low', 30, 31, 0.5, 0.0), take_out()), 20, 30, 41)
    assert 'bass swap' in s and lab['style'] == 'bass swap' and abs(lab['moment'] - 31) < 0.01, lab
    s, _ = styles(base(bring_in(), swap, fade('deck1.eq.low', 34.5, 35.5, 0.5, 0.0), take_out()), 20, 30, 41)
    assert 'bass swap' not in s, s  # A's lows went 4.5 s after B's


def test_three_band():
    def bands(gap):
        ev = []
        for i, band in enumerate(('low', 'mid', 'hi')):
            t = 30 + i * gap
            ev += fade(f'deck2.eq.{band}', 9, 9.3, 0.5, 0.0) + fade(f'deck2.eq.{band}', t, t + 0.5, 0, 0.5)
            ev += fade(f'deck1.eq.{band}', t, t + 0.5, 0.5, 0.0)
        return ev
    s, lab = styles(base(bring_in(), bands(3), take_out()), 20, 30, 41)
    assert s[0] == 'three-band swap' and 'bass swap' in s, s
    s, _ = styles(base(bring_in(), bands(1), take_out()), 20, 30, 41)
    assert 'three-band swap' not in s and 'bass swap' in s, s


def test_drop_swap():
    cut = fade('deck1.fader', 30, 30.1, 1, 0) + fade('deck2.fader', 30, 30.1, 0, 1)
    s, lab = styles(base(cut), 30.05, 30.05, 30.1, drops=[30.3])
    assert lab['style'] == 'drop swap' and lab['confidence'] == 'high', lab
    s, lab = styles(base(cut), 30.05, 30.05, 30.1)
    assert lab['style'] == 'drop swap' and lab['confidence'] == 'medium', lab
    slow = fade('deck1.fader', 30, 30.1, 1, 0) + fade('deck2.fader', 30, 31, 0, 1)
    s, _ = styles(base(slow), 30.2, 30.5, 30.1)
    assert 'drop swap' not in s, s


def test_double_drop():
    s, lab = styles(base(bring_in()), 20, 22, None, drops=[24])
    assert 'double drop' in s and lab['moment'] == 24, lab
    s, _ = styles(base(bring_in()), 20, 22, None)
    assert 'double drop' not in s, s  # without audio it's a blend with the EQs left alone


def test_echo_out():
    fx = [c(25, 'fx.beat.channel', 1)] + press(33, 'fx.beat.on')
    s, lab = styles(base(bring_in(), fx, take_out(35, 36)), 20, 30, 36)
    assert 'echo out' in s, s
    fx2 = [c(25, 'fx.beat.channel', 2)] + press(33, 'fx.beat.on')
    s, _ = styles(base(bring_in(), fx2, take_out(35, 36)), 20, 30, 36)
    assert 'echo out' not in s, s  # the effect was on deck 2
    fx3 = [c(25, 'fx.beat.channel', 1)] + press(27, 'fx.beat.on')
    s, _ = styles(base(bring_in(), fx3, take_out(35, 36)), 20, 30, 36)
    assert 'echo out' not in s, s  # 9 s before


def test_filters():
    s, _ = styles(base(bring_in(), fade('deck1.cfx', 34, 36, 0.5, 0.9), take_out(35, 37)), 20, 30, 37)
    assert 'filter out' in s, s
    s, _ = styles(base(bring_in(), fade('deck1.cfx', 34, 36, 0.5, 0.75), take_out(35, 37)), 20, 30, 37)
    assert 'filter out' not in s, s
    s, _ = styles(base(fade('deck2.cfx', 9, 9.2, 0.5, 0.1), bring_in(), fade('deck2.cfx', 21, 24, 0.1, 0.5),
                       take_out()), 20, 30, 41)
    assert 'filter in' in s, s
    s, _ = styles(base(fade('deck2.cfx', 9, 9.2, 0.5, 0.1), bring_in(), fade('deck2.cfx', 21, 24, 0.1, 0.4),
                       take_out()), 20, 30, 41)
    assert 'filter in' not in s, s  # it never came back to centre


def test_wordplay_and_loop_roll():
    loops = press(25, 'deck1.loop.half') + press(26, 'deck1.loop.half') + press(27, 'deck1.loop.half')
    s, lab = styles(base(loops, bring_in(27.5, 27.6), take_out(29, 29.2)), 27.5, 27.6, 29.2)
    assert lab['style'] == 'wordplay', s
    s, _ = styles(base(loops, bring_in(29, 29.1), take_out(30, 30.2)), 29, 29.1, 30.2)
    assert 'wordplay' not in s and s[0] == 'loop roll', s  # B came in 2 s after the last loop
    s, _ = styles(base(bring_in(), loops, take_out(32, 32.2)), 20, 30, 32.2)
    assert 'loop roll' not in s, s  # out 5 s after the last loop


def test_spinback():
    spin = [c(30 + i * 0.08, 'deck1.jog', -10) for i in range(6)]
    s, lab = styles(base(bring_in(), spin, take_out(30.6, 30.8)), 20, 30, 30.8)
    assert lab['style'] == 'spinback', s
    s, _ = styles(base(bring_in(), spin[:3], take_out(30.6, 30.8)), 20, 30, 30.8)
    assert 'spinback' not in s, s  # -30 steps


def test_scratch():
    jogs = [c(30 + i * 0.2, 'deck2.jog', 4 if i % 2 else -4) for i in range(12)]
    chops = []
    for i in range(4):
        chops += fade('mixer.crossfader', 30.1 + i * 0.6, 30.3 + i * 0.6, 0.5 if i % 2 == 0 else 1.0, 1.0 if i % 2 == 0 else 0.5)
    s, _ = styles(base(bring_in(), jogs, chops, take_out()), 20, 30, 41)
    assert 'scratch' in s, s
    s, _ = styles(base(bring_in(), jogs, chops[:len(chops) * 3 // 4 - 1], take_out()), 20, 30, 41)
    assert 'scratch' not in s, s


def test_tempo_crossfader_blends():
    s, _ = styles(base(bring_in(), fade('deck2.tempo', 25, 30, 0.50, 0.56), take_out()), 20, 30, 41)
    assert 'tempo ramp' in s, s
    s, _ = styles(base(bring_in(), fade('deck2.tempo', 25, 30, 0.50, 0.53), take_out()), 20, 30, 41)
    assert 'tempo ramp' not in s, s
    cuts = []
    for i, (a, b) in enumerate([(0.0, 1.0), (1.0, 0.0), (0.0, 1.0), (1.0, 0.0)]):
        cuts += fade('mixer.crossfader', 30 + i * 0.6, 30.1 + i * 0.6, a, b)
    s, _ = styles(base(bring_in(), cuts, take_out()), 20, 30, 41)
    assert 'crossfader cut' in s, s
    s, _ = styles(base(bring_in(), cuts[:-3], take_out()), 20, 30, 41)
    assert 'crossfader cut' not in s, s
    s, lab = styles(base(bring_in(), take_out(37, 38)), 20, 30, 38)
    assert s == ['long blend'], s  # 17 s overlap
    s, lab = styles(base(bring_in(), take_out(34, 35)), 20, 30, 35)
    assert s == [] and lab['style'] == 'unusual', s  # 14 s: no pattern
    s, _ = styles(base(bring_in(20, 20.5), take_out(22, 22.5)), 20, 20.5, 22.5)
    assert 'quick mix' in s, s


# --- moments -------------------------------------------------------------------------------------

def test_moments():
    from techniques import find_moments
    ev = []
    for i in range(6):
        ev += press(100 + i, 'deck1.pad.hotcue.1')
    ev += press(200, 'deck2.pad.sampler.1') + press(203, 'deck2.pad.sampler.2') + press(220, 'deck2.pad.sampler.1')
    ev += fade('deck1.cfx', 300, 301, 0.5, 0.9) + fade('deck1.cfx', 302, 303, 0.9, 0.5) + fade('deck1.cfx', 304, 305, 0.5, 0.1)
    ev += [c(399, 'fx.beat.channel', 2)] + press(400, 'fx.beat.on') + press(404, 'fx.beat.on')
    ctls = base(ev)
    mv, tl = find_moves(ctls), Timeline(ctls)
    found = [(m['style'], m['moment']) for m in find_moments(mv, tl, [], 500)]
    assert ('hot cue juggling', 100) in found, found
    assert [x for x in found if x[0] == 'sampler hit'] == [('sampler hit', 200), ('sampler hit', 220)], found
    assert [x for x in found if x[0] == 'filter sweep'] == [('filter sweep', 300)], found  # one group
    (fx,) = [m for m in find_moments(mv, tl, [], 500) if m['style'] == 'beat fx']
    assert fx['moment'] == 400 and 'deck2' in fx['evidence'] and '4.0 s' in fx['evidence'], fx
    five = base(*[press(100 + i, 'deck1.pad.hotcue.1') for i in range(5)])
    assert not [m for m in find_moments(find_moves(five), Timeline(five), [], 500) if m['style'] == 'hot cue juggling']
    rows = [{'style': 'drop swap', 'moment': t, 'matches': [], 't0': t - 10, 't1': t + 5} for t in (100, 140, 180)]
    assert ('drop mixing', 100) in [(m['style'], m['moment']) for m in find_moments([], Timeline([]), rows, 500)]


# --- audio ---------------------------------------------------------------------------------------

def kicks(x, sr, a, b, bpm=128, amp=0.8):
    import numpy as np
    seg = np.arange(int(0.15 * sr)) / sr
    pulse = amp * np.sin(2 * np.pi * 60 * seg) * np.exp(-seg * 25)
    for t in np.arange(a, b, 60 / bpm):
        i = int(t * sr)
        x[i:i + pulse.size] += pulse[:len(x) - i]


def test_audio():
    try:
        import numpy as np
    except ImportError:
        print('  (audio tests skipped: numpy not installed)')
        return
    from audio import analyse_audio, SR
    rng = np.random.default_rng(1)
    x = np.convolve(0.03 * rng.standard_normal(90 * SR), [1, -1], mode='same')  # hats: not silent
    kicks(x, SR, 30, 90)
    a, why = analyse_audio(x.astype(np.float32))
    assert why is None and a['drops'] == [30.0] and a['breakdowns'] == [] and a['silence'] == [], a['drops']
    y = np.convolve(0.03 * rng.standard_normal(170 * SR), [1, -1], mode='same')
    kicks(y, SR, 20, 60), kicks(y, SR, 85, 117), kicks(y, SR, 120, 140), kicks(y, SR, 142, 170)
    y[140 * SR:142 * SR] = 0
    b, _ = analyse_audio(y.astype(np.float32))
    assert [round(d) for d in b['drops']] == [20, 85], b['drops']  # the 3 s gap at 117 is not a new drop
    assert len(b['breakdowns']) == 1 and abs(b['breakdowns'][0][0] - 60.5) < 1, b['breakdowns']
    assert b['silence'] == [(140.2, 142.0)], b['silence']
    a, why = analyse_audio(np.zeros(SR * 5, np.float32))
    assert a is None and 'silent' in why


def test_audio_levels():
    """From a real set: tracks mixed at very different bass levels, 15 s breaks before drops, a loud
    burst, and the music starting out of silence (which is not a drop)."""
    try:
        import numpy as np
    except ImportError:
        print('  (audio tests skipped: numpy not installed)')
        return
    from audio import analyse_audio, SR
    rng = np.random.default_rng(2)
    z = np.convolve(0.03 * rng.standard_normal(200 * SR), [1, -1], mode='same')
    z[:10 * SR] = 0                       # silence, then the set starts at 10 s
    kicks(z, SR, 10, 60, amp=0.2)         # a quiet track
    kicks(z, SR, 75, 100, amp=0.2)        # its drop after 15 s with no bass
    kicks(z, SR, 115, 140, amp=1.0)       # a loud track comes in after a break
    kicks(z, SR, 155, 200, amp=1.0)       # and drops after 15 s
    z[185 * SR:188 * SR] *= 4             # a loud burst
    a, _ = analyse_audio(z.astype(np.float32))
    assert [round(d) for d in a['drops']] == [75, 115, 155], a['drops']


def test_names_before_record():
    """From a real set: deck 1's track was played before Record and restarted without reloading, so
    its only history row is from before the recording. Deck 2's track never played 60 s in a row."""
    ev = press(6.7, 'deck1.play') + press(67.9, 'deck2.play') + [{'t': 150, 'type': 'end'}]
    hist = [{'title': 'Pre', 'artist': 'P', 'bpm': None, 'key': None, 'path': '/p', 't': -95.6}]
    r = rl.analyse(HEADER, sorted(ev, key=lambda e: e['t']), hist)
    got = [(t['deck'], t['start'], t.get('title'), t.get('before_record')) for t in r['tracklist']]
    assert got == [(1, 6.7, 'Pre', True), (2, 67.9, None, None)], got  # no phantom track at -95.6 s


def test_stutter_is_not_a_stop():
    """A pause resumed within 2 s is a stutter, not a deck stopping by mistake."""
    from sheet import stopped_while_audible
    ev = base(bring_in(), press(31.5, 'deck2.play'), press(32.0, 'deck2.play'), press(50, 'deck1.play'))
    assert stopped_while_audible(find_moves(ev), Timeline(ev)) == [(50, 1)]


# --- real recordings and the size budget -----------------------------------------------------------

def run_fixture(name):
    ev = [json.loads(line) for line in gzip.open(HERE / 'fixtures' / f'{name}.jsonl.gz', 'rt') if line.strip()]
    result = rl.analyse(ev[0], ev[1:], [])
    moves, moments, clips, md = rl.build(result, f'{name}.rekordbox.jsonl', audio_reason='not in this test')
    return result, moments, clips, md


def test_fixtures():
    for name, low, high in (('flx4-bassswap', 70, 75), ('flx4-cues', 105, 112)):
        result, moments, clips, md = run_fixture(name)
        (t,) = result['transitions']
        assert t['style'] == 'bass swap' and low <= t['moment'] <= high, (name, t['styles'], t['moment'])
        lines = md.count('\n')
        assert lines <= 30 + 300 * result['end'] / 3600, (name, lines)
    result, moments, clips, md = run_fixture('flx4-bassswap')
    assert 'filter out' in result['transitions'][0]['styles']
    assert '## Now playing' in md and '- [ ] C01' in md and 'bass swap' in md


def test_budget():
    """A 1-hour, 25-track set with something going on in every track stays under 300 lines."""
    ev, history = [], []
    for k in range(25):
        t = k * 144.0
        d, o = (1, 2) if k % 2 == 0 else (2, 1)
        ev += press(t, f'deck{d}.load') + fade(f'deck{d}.fader', t, t + 0.2, 1, 0) + press(t + 1, f'deck{d}.play')
        if k:
            ev += fade(f'deck{d}.eq.low', t + 0.5, t + 0.8, 0.5, 0) + fade(f'deck{d}.fader', t + 10, t + 14, 0, 1)
            ev += fade(f'deck{d}.eq.low', t + 30, t + 31, 0, 0.5) + fade(f'deck{o}.eq.low', t + 30, t + 31, 0.5, 0)
            ev += fade(f'deck{o}.cfx', t + 36, t + 39, 0.5, 0.95) + fade(f'deck{o}.fader', t + 37, t + 40, 1, 0)
        else:
            ev += fade('deck1.fader', t + 2, t + 3, 0, 1)
        ev += press(t + 80, f'deck{d}.pad.sampler.1') + fade(f'deck{d}.cfx', t + 100, t + 102, 0.5, 0.1) \
            + fade(f'deck{d}.cfx', t + 103, t + 105, 0.1, 0.5)
        history.append({'title': f'Song {k + 1}', 'artist': 'Artist', 'bpm': 124.0, 'key': '8A', 'path': f'/{k}',
                        't': t + 61})
    ev = sorted(ev, key=lambda e: e['t']) + [{'t': 3600.0, 'type': 'end'}]
    result = rl.analyse(HEADER, ev, history)
    moves, moments, clips, md = rl.build(result, 'set.rekordbox.jsonl', audio_reason='not in this test')
    assert len(result['tracklist']) == 25 and len(result['transitions']) == 24
    assert all('bass swap' in t['styles'] for t in result['transitions']), [t['styles'] for t in result['transitions']]
    lines = md.count('\n')
    assert lines <= 300, lines
    return lines


def test_unusual_cap():
    """Many unusual transitions keep the Unusual section to 40 lines, plus one command for the rest."""
    ev = []
    for k in range(12):  # each deck comes in and the other goes out, 14 s of overlap: no known pattern
        t, (d, o) = k * 60.0, ((1, 2) if k % 2 == 0 else (2, 1))
        ev += press(t, f'deck{d}.load') + fade(f'deck{d}.fader', t, t + 0.2, 1, 0) + press(t + 1, f'deck{d}.play')
        ev += fade(f'deck{d}.fader', t + 10, t + 11, 0, 1) + [c(t + 12 + i * 0.5, f'deck{d}.trim', 0.5 + i / 100) for i in range(8)]
        if k:
            ev += fade(f'deck{o}.fader', t + 24, t + 25, 1, 0)
    result = rl.analyse(HEADER, sorted(ev, key=lambda e: e['t']), [])
    moves, moments, clips, md = rl.build(result, 'odd.rekordbox.jsonl', audio_reason='not in this test')
    assert sum(t['style'] == 'unusual' for t in result['transitions']) >= 5
    section = md.split('## Unusual')[1].split('\n## ')[0].strip().splitlines()[1:]
    assert len(section) <= 41 and 'more: rekordbox_log.py window' in section[-1], section


if __name__ == '__main__':
    only = sys.argv[1] if len(sys.argv) > 1 else ''
    if not only:
        rl.selftest()
    for name, fn in list(globals().items()):
        if name.startswith('test_') and only in name:
            out = fn()
            print(f'{name} ok' + (f' ({out} lines)' if out else ''))
