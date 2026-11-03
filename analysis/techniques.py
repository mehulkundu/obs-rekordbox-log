"""Transition styles and set moments, recognised from moves and deck levels.

Each rule takes a Window and returns None or a match: {style, moment, confidence, evidence}.
Thresholds are starting points from the spec (docs/superpowers/specs/2026-11-04-analysis-v2-design.md);
test_analysis.py pins each one with a case that just meets it and one that just misses.
"""
from moves import stamp

AUDIBLE = 0.1
OVERLAP = 0.3
LOOP_CTLS = ('loop.in', 'loop.half')


class Window:
    """One transition: A (outgoing) and B (incoming) decks, its times, moves and levels."""

    def __init__(self, tl, moves, A, B, start, swap, end, next_start=None, drops=()):
        self.tl, self.A, self.B = tl, A, B
        self.start, self.swap, self.end = start, swap, end
        anchor = start if start is not None else swap
        self.t0 = anchor - 10
        if end is not None:
            self.t1 = end + 5
        else:
            stops = [t for t in ((swap + 20) if swap is not None else None, next_start) if t is not None]
            self.t1 = min(stops) if stops else anchor + 30
        self.moves = [m for m in moves if self.t0 <= m['start'] <= self.t1]
        self.times = tl.samples(self.t0, self.t1)
        self.la = [tl.level(A, t) for t in self.times]
        self.lb = [tl.level(B, t) for t in self.times]
        self.drops = list(drops)

    def deck_moves(self, d, suffix):
        return [m for m in self.moves if m['ctl'] == f'deck{d}.{suffix}']

    def presses(self, d, test):
        return [m['start'] for m in self.moves if m['ctl'].startswith(f'deck{d}.') and test(m['ctl'][6:])]

    def overlap(self):
        return round(sum(0.1 for a, b in zip(self.la, self.lb) if a > OVERLAP and b > OVERLAP), 1)

    def overlap_span(self):
        both = [t for t, a, b in zip(self.times, self.la, self.lb) if a > OVERLAP and b > OVERLAP]
        return (both[0], both[-1]) if both else (None, None)

    def a_out_after(self, t, within):
        """First time in (t, t + within] when A's level is below AUDIBLE, or None."""
        return next((x for x, a in zip(self.times, self.la) if t < x <= t + within and a < AUDIBLE), None)


def match(style, moment, evidence, confidence='medium'):
    return {'style': style, 'moment': round(moment, 3), 'confidence': confidence, 'evidence': evidence}


def is_loop(c):
    return c in LOOP_CTLS or c.startswith('pad.beatloop.')


def is_rolling(c):
    return c == 'loop.half' or c.startswith('pad.beatloop.')


def runs(times, count, within):
    """Runs of at least `count` times inside `within` seconds: [(first, last, n)], not overlapping."""
    out, i = [], 0
    times = sorted(times)
    while i + count - 1 < len(times):
        if times[i + count - 1] - times[i] <= within:
            j = i + count - 1
            while j + 1 < len(times) and times[j + 1] - times[i] <= within:
                j += 1
            out.append((times[i], times[j], j - i + 1))
            i = j + 1
        else:
            i += 1
    return out


# --- transitions, in priority order -------------------------------------------------------------

def wordplay(w):
    if w.start is None:
        return None
    before = [t for t in w.presses(w.A, is_loop) if w.start - 8 <= t <= w.start]
    cues = {}
    for m in w.moves:
        if m['ctl'].startswith(f'deck{w.A}.pad.hotcue.') and w.start - 8 <= m['start'] <= w.start:
            cues.setdefault(m['ctl'], []).append(m['start'])
    groups = [before] + list(cues.values())
    best = max(groups, key=len)
    if len(best) >= 3 and w.start - max(best) <= 1:
        return match('wordplay', w.start, f'deck{w.A} {len(best)} loop/cue presses in the 8 s before deck{w.B} '
                     f'came in, the last {w.start - max(best):.1f} s before')
    return None


def loop_roll(w):
    for first, last, n in runs(w.presses(w.A, is_rolling), 3, 8):
        out = w.a_out_after(last, 4)
        if out is not None:
            return match('loop roll', last, f'deck{w.A} {n} loop presses in {last - first:.1f} s, '
                         f'then out {out - last:.1f} s later')
    return None


def spinback(w):
    jogs = [m for m in w.deck_moves(w.A, 'jog') if m['steps'] < 0]
    for i, m in enumerate(jogs):
        burst = [x for x in jogs[i:] if x['start'] - m['start'] <= 1]
        steps = sum(x['steps'] for x in burst)
        if steps <= -40:
            end = burst[-1]['end']
            if w.a_out_after(end, 1) is not None:
                return match('spinback', m['start'], f'deck{w.A} jog {steps} steps in under 1 s, then out')
    return None


def double_drop(w):
    """Both decks full with both lows up for 4 s, with an audio drop in that stretch. Without the
    audio this is just a blend with the EQs left alone."""
    if not w.drops:
        return None
    run = None
    for t, a, b in zip(w.times, w.la, w.lb):
        full = (a >= 0.8 and b >= 0.8 and w.tl.value(f'deck{w.A}.eq.low', t) >= 0.4
                and w.tl.value(f'deck{w.B}.eq.low', t) >= 0.4)
        if full:
            run = run if run is not None else t
            drop = next((d for d in w.drops if run <= d <= t), None)
            if t - run >= 4 and drop is not None:
                return match('double drop', drop, f'both decks full with both lows up, an audio drop at {stamp(drop)}')
        else:
            run = None
    return None


def drop_swap(w):
    k = 3  # 0.3 s in samples
    falls = [i for i in range(k, len(w.times)) if w.la[i - k] - w.la[i] >= 0.7]
    rises = [i for i in range(k, len(w.times)) if w.lb[i] - w.lb[i - k] >= 0.7]
    for i in falls:
        j = next((j for j in rises if abs(j - i) <= k), None)
        if j is None:
            continue
        cut = w.times[min(i, j)]
        before = sum(0.1 for t, a, b in zip(w.times, w.la, w.lb) if t < cut and a > OVERLAP and b > OVERLAP)
        if before < 2:
            drop = any(abs(d - cut) <= 1 for d in w.drops)
            return match('drop swap', cut, f'deck{w.A} level {w.la[i - k]:.2f}->{w.la[i]:.2f} and deck{w.B} '
                         f'{w.lb[j - k]:.2f}->{w.lb[j]:.2f} within 0.3 s' + (', on an audio drop' if drop else ''),
                         'high' if drop else 'medium')
    return None


def echo_out(w):
    out = w.end
    if out is None:
        return None
    for m in w.moves:
        if m['ctl'] == 'fx.beat.on' and out - 8 <= m['start'] <= out and w.tl.fx_is_on(m['start']) \
                and w.tl.value('fx.beat.channel', m['start']) == w.A:
            return match('echo out', out, f'beat FX on for deck{w.A} {out - m["start"]:.1f} s before it went out')
    return None


def find_scratch(moves, d, t0=None, t1=None):
    jogs = [m['start'] for m in moves if m['ctl'] == f'deck{d}.jog' and (t0 is None or t0 <= m['start'] <= t1)]
    chops = [m['start'] for m in moves if m['ctl'] in (f'deck{d}.fader', 'mixer.crossfader')]
    out = []
    for first, last, n in runs(jogs, 10, 5):
        c = sum(1 for t in chops if first <= t <= first + 5)
        if c >= 4:
            out.append((first, n, c))
    return out


def scratch(w):
    for d in (w.A, w.B):
        for first, n, c in find_scratch(w.moves, d):
            return match('scratch', first, f'deck{d} {n} jog moves and {c} fader/crossfader moves within 5 s')
    return None


def filter_out(w):
    """A's filter goes 0.3 or more off centre while A fades: its level 4 s after is 0.2 lower."""
    for m in w.deck_moves(w.A, 'cfx'):
        if abs(m['to'] - 0.5) >= 0.3 and w.tl.level(w.A, m['end'] + 4) <= w.tl.level(w.A, m['start']) - 0.2:
            return match('filter out', m['end'], f"deck{w.A} filter {m['from']:.2f}->{m['to']:.2f} while it faded out")
    return None


def filter_in(w):
    """B's filter comes back to centre from 0.3 or more off while B rises: 0.2 louder than 4 s before."""
    for m in w.deck_moves(w.B, 'cfx'):
        if abs(m['from'] - 0.5) >= 0.3 and abs(m['to'] - 0.5) <= 0.05 and \
                w.tl.level(w.B, m['end']) >= w.tl.level(w.B, m['start'] - 4) + 0.2:
            return match('filter in', m['end'], f"deck{w.B} filter {m['from']:.2f}->{m['to']:.2f} as it came in")
    return None


SWAP_WITHIN = 4  # seconds between B's knob going up and A's going down: about 2 bars at 128 BPM


def band_swaps(w, band):
    """Times when B's band comes up from cut while A's goes down, within SWAP_WITHIN of each other."""
    ups = [m for m in w.deck_moves(w.B, f'eq.{band}') if m['from'] <= 0.2 and m['to'] > 0.4]
    downs = [m for m in w.deck_moves(w.A, f'eq.{band}') if m['from'] > 0.2 and m['to'] < 0.2]
    out = []
    for u in ups:
        d = next((d for d in downs if abs(d['end'] - u['end']) <= SWAP_WITHIN), None)
        if d:
            out.append((max(u['end'], d['end']), u, d))
    return out


def three_band(w):
    found = {band: band_swaps(w, band) for band in ('low', 'mid', 'hi')}
    if not all(found.values()):
        return None
    times = sorted(found[b][-1][0] for b in found)
    if all(b - a >= 2 for a, b in zip(times, times[1:])):
        low = found['low'][-1][0]
        return match('three-band swap', low, 'lows, mids and highs swapped one at a time: ' +
                     ', '.join(f'{b} {stamp(found[b][-1][0])}' for b in ('low', 'mid', 'hi')))
    return None


def bass_swap(w):
    swaps = band_swaps(w, 'low')
    if not swaps:
        return None
    t, u, d = swaps[-1]
    more = f', {len(swaps)} swaps in all' if len(swaps) > 1 else ''
    return match('bass swap', t, f"deck{w.B} low {u['from']:.2f}->{u['to']:.2f} while deck{w.A} low "
                 f"{d['from']:.2f}->{d['to']:.2f} within {abs(u['end'] - d['end']):.1f} s{more}")


def tempo_ramp(w):
    a, b = w.overlap_span()
    if a is None:
        return None
    for d in (w.A, w.B):  # moves, not values: an untouched slider's real position is unknown
        ramp = [m for m in w.deck_moves(d, 'tempo') if a <= m['start'] <= b]
        if ramp and abs(ramp[-1]['to'] - ramp[0]['from']) >= 0.05:
            return match('tempo ramp', (ramp[0]['start'] + ramp[-1]['end']) / 2,
                         f"deck{d} tempo {ramp[0]['from']:.2f}->{ramp[-1]['to']:.2f} during the overlap")
    return None


def crossfader_cut(w):
    big = [m['start'] for m in w.moves if m['ctl'] == 'mixer.crossfader' and abs(m['to'] - m['from']) > 0.5]
    for first, last, n in runs(big, 4, 3):
        return match('crossfader cut', first, f'{n} crossfader moves of more than half its travel within 3 s')
    return None


def long_blend(w):
    o = w.overlap()
    if o >= 16 and w.swap is not None:
        return match('long blend', w.swap, f'both decks up for {o:.0f} s')
    return None


def quick_mix(w):
    o = w.overlap()
    if o < 4 and w.swap is not None:
        return match('quick mix', w.swap, f'both decks up for {o:.1f} s')
    return None


# Tricks first, then how the decks were mixed, then how the old track left, then blends.
TRANSITIONS = [wordplay, loop_roll, spinback, double_drop, drop_swap, scratch, three_band, bass_swap,
               echo_out, filter_out, filter_in, tempo_ramp, crossfader_cut, long_blend, quick_mix]
BLENDS = ('long blend', 'quick mix')


def label_transition(w):
    found = [m for m in (rule(w) for rule in TRANSITIONS) if m]
    if not found:
        moment = w.swap if w.swap is not None else w.start
        return {'style': 'unusual', 'styles': [], 'moment': moment, 'confidence': 'low',
                'evidence': 'no known pattern: see the moves'}
    top = found[0]
    return {**top, 'styles': [m['style'] for m in found], 'matches': found}


def shown_styles(styles):
    """How a transition reads in the sheet: every style, without the blend kinds when others matched."""
    main = [s for s in styles if s not in BLENDS]
    return ' + '.join(main or styles) or 'unusual'


# --- moments across the set ------------------------------------------------------------------

COVERED = {'loop roll': ('loop roll', 'wordplay'), 'scratch': ('scratch',), 'filter sweep': ('filter out', 'filter in'),
           'beat fx': ('echo out',)}


def find_moments(moves, tl, transitions, end):
    found = []
    for d in (1, 2):
        rolls = [m['start'] for m in moves if m['ctl'].startswith(f'deck{d}.') and is_rolling(m['ctl'][6:])]
        for first, last, n in runs(rolls, 3, 8):
            found.append(match('loop roll', last, f'deck{d} {n} loop presses in {last - first:.1f} s') | {'deck': d})
        for first, n, c in find_scratch(moves, d):
            found.append(match('scratch', first, f'deck{d} {n} jog moves and {c} fader/crossfader moves within 5 s') | {'deck': d})
        cues = [m['start'] for m in moves if m['ctl'].startswith(f'deck{d}.pad.hotcue.')]
        for first, last, n in runs(cues, 6, 8):
            found.append(match('hot cue juggling', first, f'deck{d} {n} hot cue presses in {last - first:.1f} s') | {'deck': d})
        hits = [m['start'] for m in moves if m['ctl'].startswith(f'deck{d}.pad.sampler.')]
        for group in groups(hits, 8):
            found.append(match('sampler hit', group[0], f'deck{d} {len(group)} sampler pad presses') | {'deck': d})
        sweeps = [m['start'] for m in moves if m['ctl'] == f'deck{d}.cfx' and abs(m['to'] - 0.5) >= 0.3]
        for group in groups(sweeps, 8):
            found.append(match('filter sweep', group[0], f'deck{d} {len(group)} filter sweeps in '
                               f'{group[-1] - group[0]:.0f} s') | {'deck': d})
    for m in moves:
        if m['ctl'] == 'fx.beat.on' and tl.fx_is_on(m['start']):
            off = next((x['start'] for x in moves if x['ctl'] == 'fx.beat.on' and x['start'] > m['start']), end)
            ch = tl.value('fx.beat.channel', m['start'])
            found.append(match('beat fx', m['start'], f'beat FX on for {off - m["start"]:.1f} s'
                               + (f' on deck{int(ch)}' if ch in (1, 2) else '')))
    # 3 or more drop swaps in a row, each track on for under 60 s
    row = []
    for tr in transitions + [None]:
        quick = tr is not None and tr.get('style') == 'drop swap' and (not row or tr['moment'] - row[-1]['moment'] < 60)
        if quick:
            row.append(tr)
            continue
        if len(row) >= 3:
            found.append(match('drop mixing', row[0]['moment'], f'{len(row)} drop swaps in a row, '
                               f'{stamp(row[0]["moment"])}-{stamp(row[-1]["moment"])}'))
        row = [tr] if tr is not None and tr.get('style') == 'drop swap' else []
    # skip a moment a transition already describes: the same kind of match within 5 s
    keep = []
    for m in found:
        near = [x for t in transitions for x in t.get('matches', []) if abs(x['moment'] - m['moment']) <= 5]
        if any(x['style'] in COVERED.get(m['style'], ()) for x in near):
            continue
        keep.append(m)
    return sorted(keep, key=lambda m: m['moment'])


def groups(times, gap):
    """Split sorted times wherever two are `gap` seconds or more apart."""
    out = []
    for t in sorted(times):
        if out and t - out[-1][-1] < gap:
            out[-1].append(t)
        else:
            out.append([t])
    return out
