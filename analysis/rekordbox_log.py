#!/usr/bin/env python3
"""Turn an obs-rekordbox-log .jsonl into a tracklist, transitions, FX spans and YouTube chapters.

    python3 rekordbox_log.py SET.rekordbox.jsonl [--out DIR]
    python3 rekordbox_log.py --selftest

Track names come from Rekordbox's play history through pyrekordbox (pip install pyrekordbox).
Without it, everything else still works and tracks are named by deck.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


AUDIBLE = 0.1


def load(path):
    header, events = None, []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue  # a crash can leave half a line at the end
            if e.get('type') == 'session':
                header = e
            else:
                events.append(e)
    if header is None:
        sys.exit(f'{path}: no session header, not an obs-rekordbox-log file')
    return header, events


def video_clock(header, events):
    """Returns vt(t): seconds into the video. Adds offset_ms and removes time spent paused."""
    offset = header.get('offset_ms', 0) / 1000
    pauses, paused_at = [], None
    for e in events:
        if e['type'] == 'pause':
            paused_at = e['t']
        elif e['type'] == 'resume' and paused_at is not None:
            pauses.append((paused_at, e['t']))
            paused_at = None
    if paused_at is not None:
        pauses.append((paused_at, float('inf')))

    def vt(t):
        if t is None:
            return None
        gone = sum(min(t, b) - a for a, b in pauses if t > a)
        return round(t + offset - gone, 3)
    return vt


def read_history(header, end_t):
    """Rekordbox history rows played during the session, with t in log seconds."""
    try:
        from pyrekordbox import MasterDatabase
    except ImportError:
        print('pyrekordbox not installed: tracks are named by deck', file=sys.stderr)
        return []
    # Rekordbox stores created_at as naive local time
    start = datetime.fromisoformat(header['wall']).astimezone().replace(tzinfo=None)
    end = start + timedelta(seconds=end_t)
    try:
        rows = [s for s in MasterDatabase().get_history_songs().all() if start <= s.created_at <= end]
    except Exception as err:  # database locked, key missing, schema changed
        print(f'cannot read Rekordbox history ({err}): tracks are named by deck', file=sys.stderr)
        return []
    out = []
    for s in sorted(rows, key=lambda s: s.created_at):
        c = s.Content
        if c is None:
            continue
        out.append({
            'title': c.Title, 'artist': c.ArtistName, 'bpm': c.BPM / 100 if c.BPM else None,
            'key': c.KeyName, 'path': c.FolderPath, 't': (s.created_at - start).total_seconds(),
        })
    return out


def xfader_gain(deck, x):
    # Both decks full at the centre, cut at the far end, like Rekordbox's default curve.
    return min(1.0, 2 * (1 - x)) if deck == 1 else min(1.0, 2 * x)


class Mixer:
    """Replays controller events. MIDI only reports changes, so untouched controls are assumed
    at their usual spot: channel faders up, crossfader and knobs centred, decks stopped."""

    def __init__(self):
        self.ctl = {}
        self.playing = {1: False, 2: False}

    def apply(self, e):
        name, v = e['ctl'], e['v']
        self.ctl[name] = v
        for d in (1, 2):
            if name == f'deck{d}.play' and v == 1:
                self.playing[d] = not self.playing[d]
            elif name in (f'deck{d}.cue', f'deck{d}.load') and v == 1:
                self.playing[d] = False

    def level(self, d):
        if not self.playing[d]:
            return 0.0
        return self.ctl.get(f'deck{d}.fader', 1.0) * xfader_gain(d, self.ctl.get('mixer.crossfader', 0.5))


def find_tracks(ctls, history, end_t):
    """Every load that was then played is a track. History rows give the names."""
    # By position in the log, not time: a load and a play can land in the same millisecond.
    # `i` is the load's index in ctls; analyse() drops it from the output.
    tracks = []
    for i, e in enumerate(ctls):
        for d in (1, 2):
            if e['ctl'] == f'deck{d}.load' and e['v'] == 1:
                tracks.append({'deck': d, 'load': e['t'], 'start': None, 'i': i})
    for tr in tracks:
        d = tr['deck']
        until = min([x['i'] for x in tracks if x['deck'] == d and x['i'] > tr['i']], default=len(ctls))
        tr['start'] = next((e['t'] for e in ctls[tr['i'] + 1:until]
                            if e['ctl'] == f'deck{d}.play' and e['v'] == 1), None)
    tracks = [tr for tr in tracks if tr['start'] is not None]

    used = set()
    for h in history:
        names = {k: h[k] for k in ('title', 'artist', 'bpm', 'key', 'path')}
        free = [i for i, tr in enumerate(tracks) if i not in used and tr['load'] is not None and tr['load'] <= h['t']]
        if free:
            i = max(free, key=lambda i: tracks[i]['load'])
            used.add(i)
            tracks[i].update(names)
        else:  # loaded with the mouse: no load press to pair with
            tracks.append({'deck': None, 'load': None, 'start': h['t'], 'i': None, **names})
    if history:  # played but never reached the history: previewed in headphones only
        tracks = [tr for tr in tracks if 'title' in tr]
    return sorted(tracks, key=lambda tr: tr['start'])


def label(tr):
    if tr.get('title'):
        return f"{tr['title']} - {tr['artist']}" if tr.get('artist') else tr['title']
    return f"Deck {tr['deck']}"


def find_transitions(tracks, ctls):
    out = []
    for i, (a, b) in enumerate(zip(tracks, tracks[1:])):
        A, B = a['deck'], b['deck']
        if not A or not B or A == B:
            continue
        m = Mixer()
        start = swap = end = None
        for j, e in enumerate(ctls):  # replay from the top so every control has its latest value
            m.apply(e)
            if j < b['i']:
                continue
            la, lb = m.level(A), m.level(B)
            if start is None and lb > AUDIBLE:
                start = e['t']
            if start is not None and swap is None and lb >= la:
                swap = e['t']
            if start is not None and end is None and la < AUDIBLE:
                end = e['t']
            if swap is not None and end is not None:
                break
        knobs = ('eq.hi', 'eq.mid', 'eq.low', 'cfx', 'trim')
        stop = end if end is not None else swap
        moves = [{'t': e['t'], 'ctl': e['ctl'], 'v': e['v']} for e in ctls
                 if start is not None and stop is not None and start <= e['t'] <= stop
                 and any(e['ctl'] == f'deck{d}.{k}' for d in (A, B) for k in knobs)]
        out.append({'into': i + 1, 'from': label(a), 'to': label(b), 'from_deck': A, 'to_deck': B,
                    'start': start, 'swap': swap, 'end': end, 'moves': moves})
    return out


def find_fx(ctls, end_t):
    spans, on, channel, level = [], None, None, None
    for e in ctls:
        n = e['ctl']
        if n == 'fx.beat.channel':
            channel = e['v']
        elif n == 'fx.beat.level':
            level = e['v']
        elif n == 'fx.beat.on' and e['v'] == 1:  # each press toggles
            if on is None:
                on = {'fx': 'beat', 'start': e['t'], 'end': end_t, 'channel': channel, 'level': level}
                spans.append(on)
            else:
                on['end'] = e['t']
                on = None
    for d in (1, 2):
        span = None
        for e in ctls:
            if e['ctl'] != f'deck{d}.cfx':
                continue
            away = abs(e['v'] - 0.5) > 0.05
            if away and span is None:
                span = {'fx': 'cfx', 'start': e['t'], 'end': end_t, 'deck': d, 'peak': e['v']}
                spans.append(span)
            elif away:
                span['peak'] = max(span['peak'], e['v'], key=lambda v: abs(v - 0.5))
            elif span is not None:
                span['end'] = e['t']
                span = None
    return sorted(spans, key=lambda s: s['start'])


def stamp(seconds):
    s = int(seconds)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f'{h}:{m:02}:{s:02}' if h else f'{m}:{s:02}'


def chapters(tracks, transitions):
    into = {t['into']: (t['swap'] if t['swap'] is not None else t['start']) for t in transitions}
    lines, last = [], None
    for i, tr in enumerate(tracks):
        at = 0 if i == 0 else into.get(i, tr['start'])
        if at is None or (last is not None and at - last < 10):  # YouTube: chapters at least 10s long
            continue
        lines.append(f'{stamp(at)} {label(tr)}')
        last = at
    if len(lines) < 3:
        lines.insert(0, f'# YouTube needs at least 3 chapters; this set has {len(lines)}.')
    return '\n'.join(lines) + '\n'


def analyse(header, events, history):
    """history: [{'title', 'artist', 'bpm', 'key', 'path', 't'}] with t in log seconds."""
    vt = video_clock(header, events)
    ctls = [e for e in events if e['type'] == 'ctl']
    end_t = events[-1]['t'] if events else 0

    tracks = find_tracks(ctls, history, end_t)
    transitions = find_transitions(tracks, ctls)
    fx = find_fx(ctls, end_t)

    # Everything below is in video time.
    for tr in tracks:
        tr['load'], tr['start'] = vt(tr['load']), vt(tr['start'])
        del tr['i']
    for t in transitions:
        t['start'], t['swap'], t['end'] = vt(t['start']), vt(t['swap']), vt(t['end'])
        for mv in t['moves']:
            mv['t'] = vt(mv['t'])
    for s in fx:
        s['start'], s['end'] = vt(s['start']), vt(s['end'])
    tracklist = [{'n': i + 1, **tr} for i, tr in enumerate(tracks)]
    return {'tracklist': tracklist, 'transitions': transitions, 'fx': fx, 'chapters': chapters(tracks, transitions)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('log', type=Path)
    ap.add_argument('--out', type=Path, help='output folder (default: next to the log, <name>.analysis)')
    args = ap.parse_args()

    header, events = load(args.log)
    end_t = events[-1]['t'] if events else 0
    result = analyse(header, events, read_history(header, end_t))

    out = args.out or args.log.with_name(args.log.name.removesuffix('.rekordbox.jsonl') + '.analysis')
    out.mkdir(parents=True, exist_ok=True)
    for name in ('tracklist', 'transitions', 'fx'):
        (out / f'{name}.json').write_text(json.dumps(result[name], indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (out / 'chapters.txt').write_text(result['chapters'], encoding='utf-8')
    print(f"{len(result['tracklist'])} tracks, {len(result['transitions'])} transitions, "
          f"{len(result['fx'])} FX spans -> {out}")


def selftest():
    header = {'type': 'session', 'v': 1, 'wall': '2026-11-03T21:00:00.000+05:30', 'offset_ms': 0}

    def c(t, name, v):
        return {'t': t, 'type': 'ctl', 'src': 'DDJ-FLX4', 'ctl': name, 'v': v}

    events = [
        # load and play in the same millisecond, with releases, as the hardware sends them
        c(1, 'deck1.load', 1), c(1, 'deck1.load', 0), c(1, 'deck1.play', 1), c(1, 'deck1.play', 0),
        c(28, 'fx.beat.channel', 1), c(29, 'fx.beat.level', 0.7),
        c(30, 'fx.beat.on', 1), c(40, 'fx.beat.on', 1),
        c(60, 'deck2.load', 1), c(65, 'deck2.fader', 0.0), c(70, 'deck2.play', 1),
        c(72, 'deck2.fader', 0.5), c(76, 'deck2.eq.low', 0.2),
        c(80, 'deck2.fader', 1.0), c(85, 'deck1.fader', 0.6), c(90, 'deck1.fader', 0.05),
        {'t': 100, 'type': 'pause'}, {'t': 110, 'type': 'resume'},
        c(120, 'deck1.eq.low', 0.5), {'t': 130, 'type': 'end'},
    ]
    history = [
        {'title': 'One', 'artist': 'A', 'bpm': 122.0, 'key': '8A', 'path': '/1', 't': 20},
        {'title': 'Two', 'artist': 'B', 'bpm': 123.0, 'key': '9A', 'path': '/2', 't': 75},
    ]

    vt = video_clock(header, events)
    assert vt(50) == 50 and vt(120) == 110, 'paused time is removed'

    r = analyse(header, events, history)
    assert [t['title'] for t in r['tracklist']] == ['One', 'Two'], r['tracklist']
    assert r['tracklist'][1]['deck'] == 2 and r['tracklist'][1]['start'] == 70
    (tr,) = r['transitions']
    assert (tr['start'], tr['swap'], tr['end']) == (72, 80, 90), tr
    assert tr['moves'] == [{'t': 76, 'ctl': 'deck2.eq.low', 'v': 0.2}], tr['moves']
    assert r['fx'] == [{'fx': 'beat', 'start': 30, 'end': 40, 'channel': 1, 'level': 0.7}], r['fx']
    assert r['chapters'].splitlines() == [
        '# YouTube needs at least 3 chapters; this set has 2.',
        '0:00 One - A',
        '1:20 Two - B',
    ], r['chapters']

    # Without history: tracks are named by deck, transitions still found
    r = analyse(header, events, [])
    assert [t['deck'] for t in r['tracklist']] == [1, 2]
    assert len(r['transitions']) == 1
    print('selftest ok')


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        selftest()
    else:
        main()
