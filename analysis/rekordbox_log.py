#!/usr/bin/env python3
"""Turn an obs-rekordbox-log .jsonl into an edit sheet: tracks, labelled transitions, drops and clips.

    python3 rekordbox_log.py SET.rekordbox.jsonl [--out DIR] [--video FILE]
    python3 rekordbox_log.py window SET.rekordbox.jsonl FROM TO
    python3 rekordbox_log.py --selftest

Writes <name>.analysis/edit.md (for editors and AI), clips.json, moves.jsonl, tracklist.json,
transitions.json, fx.json and chapters.txt. Track names come from Rekordbox's play history through
pyrekordbox; drops come from the video's audio through numpy and ffmpeg. Without either, the rest works.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


AUDIBLE = 0.1
# Rekordbox adds a track to its history once it has played this long (60.007 s measured on
# Rekordbox 7.2 with a DDJ-FLX4).
HISTORY_DELAY = 60
NAME_KEYS = ('title', 'artist', 'bpm', 'key', 'file')


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
    """(Rekordbox history rows played during the session with t in log seconds, why names are missing)."""
    try:
        from pyrekordbox import MasterDatabase
    except ImportError:
        return [], 'pyrekordbox not installed (pip install pyrekordbox): tracks are named by deck'

    # Rekordbox stores created_at as naive local time
    start = datetime.fromisoformat(header['wall']).astimezone().replace(tzinfo=None)
    end = start + timedelta(seconds=end_t + HISTORY_DELAY + 10)  # the last track is logged after Stop
    since = start - timedelta(minutes=15)  # a track played just before Record was logged then
    try:
        rows = [s for s in MasterDatabase().get_history_songs().all() if since <= s.created_at <= end]
    except Exception as err:  # database locked, key missing, schema changed
        return [], f'cannot read Rekordbox history ({err}): tracks are named by deck'
    out = []
    for s in sorted(rows, key=lambda s: s.created_at):
        c = s.Content
        if c is None:
            continue
        out.append({
            'title': c.Title, 'artist': c.ArtistName, 'bpm': c.BPM / 100 if c.BPM else None,
            'key': c.KeyName, 'file': c.FileNameL, 't': (s.created_at - start).total_seconds(),
        })
    return out, None


def tracks_path(log_path):
    return log_path.with_name(log_path.name.removesuffix('.rekordbox.jsonl') + '.tracks.json')


def read_tracks(path):
    """(history rows, hand fixes) from a <name>.tracks.json. A row has "logged": seconds from Record
    when Rekordbox logged it. A hand fix has "start": the video time (seconds or m:ss) the track starts."""
    from moves import parse_time
    rows, fixes = [], []
    for e in json.loads(path.read_text(encoding='utf-8')).get('tracks', []):
        names = {k: e.get(k) for k in NAME_KEYS}
        if 'start' in e:
            s = e['start']
            fixes.append({**names, 'start': parse_time(s) if isinstance(s, str) else float(s)})
        elif 'logged' in e:
            rows.append({**names, 't': float(e['logged'])})
    return rows, fixes


def write_tracks(path, header, rows):
    """The same file the plugin writes on Stop: one track per line, easy to fix by hand."""
    lines = [json.dumps({'logged': round(h['t'], 3), **{k: h[k] for k in NAME_KEYS}}, ensure_ascii=False)
             for h in rows]
    path.write_text(f'{{"v": 1, "session_wall": {json.dumps(header["wall"])}, "tracks": [\n'
                    + ',\n'.join('  ' + x for x in lines) + '\n]}\n', encoding='utf-8')


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
    # A deck played before any load in the log was loaded before Record (or with the mouse).
    for d in (1, 2):
        first_load = next((i for i, e in enumerate(ctls) if e['ctl'] == f'deck{d}.load' and e['v'] == 1), len(ctls))
        play = next((i for i, e in enumerate(ctls[:first_load]) if e['ctl'] == f'deck{d}.play' and e['v'] == 1), None)
        if play is not None:
            tracks.append({'deck': d, 'load': None, 'start': ctls[play]['t'], 'i': play})

    used = set()
    for h in history:
        if h['t'] < 0:
            continue  # from before Record: below
        names = {k: h[k] for k in NAME_KEYS}
        free = [i for i, tr in enumerate(tracks) if i not in used and tr['i'] is not None and tr['start'] <= h['t']]
        if free:
            i = min(free, key=lambda i: abs(h['t'] - tracks[i]['start'] - HISTORY_DELAY))
            used.add(i)
            tracks[i].update(names)
        elif h['t'] <= end_t:  # no load or play press to pair with
            tracks.append({'deck': None, 'load': None, 'start': h['t'], 'i': None, **names})
    # A deck already loaded at Record may have played that track just before: Rekordbox logged it
    # then, and doesn't log the same loaded track twice. Newest row first, to the earliest such track.
    early = sorted((h for h in history if h['t'] < 0), key=lambda h: -h['t'])
    waiting = sorted((tr for tr in tracks if tr['load'] is None and tr['i'] is not None and not tr.get('title')),
                     key=lambda tr: tr['start'])
    for h, tr in zip(early, waiting):
        tr.update({k: h[k] for k in NAME_KEYS}, before_record=True)
    # A track Rekordbox hasn't put in its history (it waits about a minute) is kept if it was
    # heard. One never heard was only previewed in headphones.
    tracks = [tr for tr in tracks if tr.get('title') or heard(tr, tracks, ctls)]
    return sorted(tracks, key=lambda tr: tr['start'])


def heard(tr, tracks, ctls):
    """True if the track's deck was audible at some point while the track was on it."""
    if tr['i'] is None:
        return True
    until = min([x['i'] for x in tracks if x['deck'] == tr['deck'] and x['i'] is not None and x['i'] > tr['i']],
                default=len(ctls))
    m = Mixer()
    for j, e in enumerate(ctls[:until]):
        m.apply(e)
        if j >= tr['i'] and m.level(tr['deck']) > AUDIBLE:
            return True
    return False


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
        out.append({'into': i + 1, 'from': label(a), 'to': label(b), 'from_deck': A, 'to_deck': B,
                    'start': start, 'swap': swap, 'end': end})
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


def analyse(header, events, history, fixes=()):
    """history: [{'title', 'artist', 'bpm', 'key', 'file', 't'}] with t in log seconds. fixes: hand
    fixes from the track list, each naming the track that starts nearest its 'start' (video time).
    Everything comes back in video time."""
    vt = video_clock(header, events)
    ctls = [{**e, 't': vt(e['t'])} for e in events if e['type'] == 'ctl']
    end_t = vt(events[-1]['t']) if events else 0
    history = [{**h, 't': vt(h['t'])} for h in history]

    tracks = find_tracks(ctls, history, end_t)
    for f in fixes:
        if tracks:
            tr = min(tracks, key=lambda tr: abs(tr['start'] - f['start']))
            tr.update({k: f[k] for k in NAME_KEYS})
            tr.pop('before_record', None)
    transitions = find_transitions(tracks, ctls)
    fx = find_fx(ctls, end_t)
    for tr in tracks:
        del tr['i']
    tracklist = [{'n': i + 1, **tr} for i, tr in enumerate(tracks)]
    return {'tracklist': tracklist, 'transitions': transitions, 'fx': fx, 'chapters': chapters(tracks, transitions),
            'ctls': ctls, 'end': end_t}


def drops_without_mix_ins(drops, moves, tl=None):
    """Drops minus jumps the DJ made, not the track:
    - a track being mixed in: a fader or low EQ raised by 0.3 or more over more than 0.4 s, starting
      within 2 s of the jump. A fader slammed up at the jump (a drop swap) keeps its drop.
    - riding the Beat FX level with the effect on, within 2 s of the jump (it's the effect)."""
    def mixing(m):
        if not m['ctl'].endswith(('.fader', '.eq.low')) or 'from' not in m or m['to'] - m['from'] < 0.3:
            return False
        slam = m['end'] - m['start'] <= 0.4 and m['to'] >= 0.7
        return not slam

    def riding_fx(m, d):
        return (tl is not None and m['ctl'] == 'fx.beat.level' and m['start'] - 2 <= d <= m['end'] + 2
                and tl.fx_is_on(m['start']))
    return [d for d in drops if not any((mixing(m) and abs(m['start'] - d) <= 2) or riding_fx(m, d) for m in moves)]


def build(result, log_name, audio=None, audio_reason=None, video=None, names_reason=None):
    """Label transitions, find moments and clips, and write the edit sheet. Returns
    (moves, moments, clips, edit.md text); result['transitions'] gains style, styles, moment, evidence."""
    from moves import find_moves, Timeline
    from techniques import Window, label_transition, find_moments
    from sheet import make_clips, edit_md

    ctls, end = result['ctls'], result['end']
    moves, tl = find_moves(ctls), Timeline(ctls)
    tracks, transitions = result['tracklist'], result['transitions']
    duration = max(end, audio['duration'] if audio else 0)
    if audio:
        audio['drops'] = drops_without_mix_ins(audio['drops'], moves, tl)
    drops = audio['drops'] if audio else []
    for t in transitions:
        if t['start'] is None and t['swap'] is None:
            anchor = tracks[t['into']]['start']
            t.update(style='unusual', styles=[], moment=anchor, confidence='low', t0=anchor - 10, t1=anchor + 30,
                     evidence='the incoming deck never became audible')
            continue
        nxt = tracks[t['into'] + 1]['start'] if t['into'] + 1 < len(tracks) else None
        w = Window(tl, moves, t['from_deck'], t['to_deck'], t['start'], t['swap'], t['end'], nxt, drops)
        t.update(label_transition(w), t0=round(w.t0, 3), t1=round(w.t1, 3))
    moments = find_moments(moves, tl, transitions, end)
    clips = make_clips(tracks, transitions, moments, audio, duration)
    unnamed = sum(1 for tr in tracks if not tr.get('title'))
    names = names_reason or (f'{unnamed} unnamed (Rekordbox adds a track to its history after 60 s of play)'
                             if unnamed else None)
    md = edit_md(log_name, video, duration, tracks, transitions, moments, audio, audio_reason, moves, tl, clips,
                 result['chapters'], names)
    return moves, moments, clips, md


def window(argv):
    """Print the moves between two times: the detail behind any line of the edit sheet."""
    from moves import find_moves, parse_time, window_lines
    if len(argv) != 3:
        sys.exit('usage: rekordbox_log.py window SET.rekordbox.jsonl FROM TO   (m:ss, h:mm:ss or seconds)')
    header, events = load(Path(argv[0]))
    vt = video_clock(header, events)
    ctls = [{**e, 't': vt(e['t'])} for e in events if e['type'] == 'ctl']
    print('\n'.join(window_lines(find_moves(ctls), parse_time(argv[1]), parse_time(argv[2]))) or '(no moves)')


def main():
    if sys.argv[1:2] == ['window']:
        return window(sys.argv[2:])
    import audio as audio_mod
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('log', type=Path)
    ap.add_argument('--out', type=Path, help='output folder (default: next to the log, <name>.analysis)')
    ap.add_argument('--video', type=Path, help='the recording (default: the video next to the log)')
    args = ap.parse_args()

    header, events = load(args.log)
    end_t = events[-1]['t'] if events else 0
    track_list = tracks_path(args.log)
    if track_list.exists():  # saved by the plugin on Stop, maybe fixed by hand
        history, fixes = read_tracks(track_list)
        names_reason = None
    else:  # an older recording: read Rekordbox here, and keep the list with the log
        fixes = []
        history, names_reason = read_history(header, end_t)
        if names_reason is None:
            write_tracks(track_list, header, history)
    result = analyse(header, events, history, fixes)
    audio, video, audio_reason = audio_mod.load(args.log, args.video)
    moves, moments, clips, md = build(result, args.log.name, audio, audio_reason, video, names_reason)

    out = args.out or args.log.with_name(args.log.name.removesuffix('.rekordbox.jsonl') + '.analysis')
    out.mkdir(parents=True, exist_ok=True)
    for name in ('tracklist', 'transitions', 'fx'):
        (out / f'{name}.json').write_text(json.dumps(result[name], indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (out / 'chapters.txt').write_text(result['chapters'], encoding='utf-8')
    (out / 'clips.json').write_text(json.dumps(clips, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (out / 'moves.jsonl').write_text(''.join(json.dumps(m) + '\n' for m in moves), encoding='utf-8')
    (out / 'edit.md').write_text(md, encoding='utf-8')
    print(f"{len(result['tracklist'])} tracks, {len(result['transitions'])} transitions, {len(moments)} moments, "
          f"{len(clips)} clips, audio: {'yes' if audio else audio_reason} -> {out / 'edit.md'}")


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
        {'title': 'One', 'artist': 'A', 'bpm': 122.0, 'key': '8A', 'file': '/1', 't': 20},
        {'title': 'Two', 'artist': 'B', 'bpm': 123.0, 'key': '9A', 'file': '/2', 't': 75},
    ]

    vt = video_clock(header, events)
    assert vt(50) == 50 and vt(120) == 110, 'paused time is removed'

    r = analyse(header, events, history)
    assert [t['title'] for t in r['tracklist']] == ['One', 'Two'], r['tracklist']
    assert r['tracklist'][1]['deck'] == 2 and r['tracklist'][1]['start'] == 70
    (tr,) = r['transitions']
    assert (tr['start'], tr['swap'], tr['end']) == (72, 80, 90), tr
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

    # A deck loaded before Record starts a track at its first play. A track never heard (fader
    # down the whole time) is dropped. A heard one stays, even before it reaches the history.
    ev = [c(1, 'deck1.play', 1), c(5, 'deck2.load', 1), c(6, 'deck2.fader', 0.0), c(7, 'deck2.play', 1),
          c(30, 'deck1.load', 1), c(31, 'deck1.play', 1), {'t': 40, 'type': 'end'}]
    r = analyse(header, ev, [{'title': 'Pre', 'artist': 'P', 'bpm': None, 'key': None, 'file': '/p', 't': 3}])
    assert [(t['deck'], t['load'], t['start'], t.get('title')) for t in r['tracklist']] == \
        [(1, None, 1, 'Pre'), (1, 30, 31, None)], r['tracklist']

    # Real FLX4 session: a history row lands 60 s after its track starts, after another deck has
    # started. It belongs to the track that started 60 s earlier, not the latest one.
    ev = [c(8.484, 'deck1.load', 1), c(17.534, 'deck1.play', 1), c(51.253, 'deck2.play', 1), {'t': 94, 'type': 'end'}]
    r = analyse(header, ev, [{'title': 'Vatta Vatta', 'artist': 'AFTERAll', 'bpm': 130.0, 'key': '4A', 'file': '/v', 't': 77.541}])
    assert [(t['deck'], t.get('title')) for t in r['tracklist']] == [(1, 'Vatta Vatta'), (2, None)], r['tracklist']
    print('selftest ok')


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        selftest()
    else:
        main()
