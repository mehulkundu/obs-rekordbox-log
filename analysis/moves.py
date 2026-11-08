"""Moves: the controller log collapsed to one line per gesture, and a timeline of control values."""
from bisect import bisect_right

GAP = 0.5  # seconds between events that still count as one move
RELATIVE = ('jog', 'jog.side', 'jog.search', 'browse')  # these send signed steps, not positions
POSITION = ('fader', 'crossfader', 'eq.hi', 'eq.mid', 'eq.low', 'trim', 'cfx', 'tempo', 'level',
            'headphone.mix', 'master', 'fx.beat.channel')  # the FX channel lever: its value is the deck
DEFAULTS = {'fader': 1.0}  # every other position control starts centred (0.5)


def kind(ctl):
    if ctl.endswith(RELATIVE):
        return 'relative'
    if ctl.endswith(POSITION):
        return 'position'
    return 'button'


def find_moves(ctls):
    """One move per gesture: a control moving one way with gaps under GAP, a run of jog steps one
    way, or a button press. ctls must be in time order."""
    moves, last = [], {}
    for e in ctls:
        c, t, v = e['ctl'], round(e['t'], 3), e['v']
        k = kind(c)
        if k == 'button':
            if v == 1:
                moves.append({'start': t, 'end': t, 'ctl': c, 'n': 1})
            continue
        m = last.get(c)
        recent = m is not None and t - m['end'] < GAP
        if k == 'relative':
            if recent and (m['steps'] > 0) == (v > 0):
                m['end'], m['steps'], m['n'] = t, m['steps'] + int(v), m['n'] + 1
            else:
                m = last[c] = {'start': t, 'end': t, 'ctl': c, 'steps': int(v), 'n': 1}
                moves.append(m)
            continue
        v = round(v, 3)
        if recent:
            step = v - m['to']
            if step == 0 or m['_dir'] == 0 or (step > 0) == (m['_dir'] > 0):
                m['end'], m['to'], m['n'] = t, v, m['n'] + 1
                m['_dir'] = m['_dir'] or step
                continue
        frm = m['to'] if m else v
        m = last[c] = {'start': t, 'end': t, 'ctl': c, 'from': frm, 'to': v, 'n': 1, '_dir': v - frm}
        moves.append(m)
    for m in moves:
        m.pop('_dir', None)
    return moves


def xfader_gain(deck, x):
    # Both decks full at the centre, cut at the far end, like Rekordbox's default curve.
    return min(1.0, 2 * (1 - x)) if deck == 1 else min(1.0, 2 * x)


class Timeline:
    """Any control's value, a deck's playing state, and a deck's level at any time t.
    MIDI only reports changes, so untouched controls are at their usual spot: channel faders up,
    crossfader and knobs centred, decks stopped."""

    def __init__(self, ctls):
        self.values = {}  # ctl -> ([t], [v])
        self.playing = {1: ([], []), 2: ([], [])}
        self.fx_on = ([], [])
        state, fx = {1: False, 2: False}, False
        for e in ctls:
            c, t, v = e['ctl'], e['t'], e['v']
            if kind(c) == 'position':
                ts, vs = self.values.setdefault(c, ([], []))
                ts.append(t)
                vs.append(v)
            if v != 1:
                continue
            for d in (1, 2):
                if c == f'deck{d}.play':
                    state[d] = not state[d]
                elif c in (f'deck{d}.cue', f'deck{d}.load'):
                    state[d] = False
                else:
                    continue
                self.playing[d][0].append(t)
                self.playing[d][1].append(state[d])
            if c == 'fx.beat.on':  # each press toggles
                fx = not fx
                self.fx_on[0].append(t)
                self.fx_on[1].append(fx)
        # Rekordbox keeps the Beat FX on/off state, so it may already be on at Record. DJs ride the
        # level knob while the effect is on: start on if that puts more level moves while on.
        self.fx_start = False
        rides = self.values.get('fx.beat.level', ([], []))[0]
        while_on = sum(1 for t in rides if self._at(self.fx_on, t, False))
        if len(rides) - while_on > while_on:
            self.fx_start = True
            self.fx_on = (self.fx_on[0], [not on for on in self.fx_on[1]])

    @staticmethod
    def _at(series, t, default):
        ts, vs = series
        i = bisect_right(ts, t)
        return vs[i - 1] if i else default

    def value(self, ctl, t):
        default = DEFAULTS.get(ctl.rsplit('.', 1)[-1], 0.5)
        return self._at(self.values.get(ctl, ([], [])), t, default)

    def is_playing(self, d, t):
        return self._at(self.playing[d], t, False)

    def fx_is_on(self, t):
        return self._at(self.fx_on, t, self.fx_start)

    def level(self, d, t):
        if not self.is_playing(d, t):
            return 0.0
        return self.value(f'deck{d}.fader', t) * xfader_gain(d, self.value('mixer.crossfader', t))

    def samples(self, t0, t1, step=0.1):
        n = max(0, int(round((t1 - t0) / step)) + 1)
        return [round(t0 + i * step, 3) for i in range(n)]


def stamp(seconds, tenths=False):
    """m:ss or h:mm:ss, with a decimal when tenths is set."""
    if seconds is None:
        return '?'
    s = max(0.0, seconds)
    h, rest = divmod(int(s), 3600)
    m, sec = divmod(rest, 60)
    frac = f'.{int((s - int(s)) * 10)}' if tenths else ''
    return f'{h}:{m:02}:{sec:02}{frac}' if h else f'{m}:{sec:02}{frac}'


def parse_time(text):
    """'14:02', '1:02:03' or '842.5' to seconds."""
    parts = [float(p) for p in text.split(':')]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def window_lines(moves, t0, t1):
    out = []
    for m in moves:
        if m['end'] < t0 or m['start'] > t1:
            continue
        span = stamp(m['start'], True) if m['start'] == m['end'] else f"{stamp(m['start'], True)}-{stamp(m['end'], True)}"
        if 'steps' in m:
            what = f"{m['steps']:+d} steps"
        elif 'from' in m:
            what = f"{m['from']:.2f} -> {m['to']:.2f}"
        else:
            what = 'press'
        out.append(f"{span}  {m['ctl']}  {what}  ({m['n']})")
    return out
