"""Clips and the edit sheet (edit.md): what an editor or an AI needs, in a few hundred lines."""
from moves import stamp, window_lines
from techniques import shown_styles

WEIGHTS = {
    'drop swap': 3, 'double drop': 3, 'wordplay': 3,
    'loop roll': 2, 'scratch': 2, 'hot cue juggling': 2, 'spinback': 2, 'drop mixing': 2,
    'echo out': 1.5, 'unusual': 1.5,
    'filter out': 1, 'filter in': 1, 'bass swap': 1, 'three-band swap': 1, 'tempo ramp': 1,
    'crossfader cut': 1, 'filter sweep': 1, 'beat fx': 1, 'sampler hit': 1,
    'long blend': 0.5, 'quick mix': 0.5, 'drop': 0,
}
CLOSE_UP = ('loop roll', 'scratch', 'hot cue juggling', 'spinback', 'sampler hit', 'beat fx', 'filter sweep',
            'drop mixing')
TOP_CLIPS = 30
UNUSUAL_LINES = 40
GLYPHS = '▁▂▃▄▅▆▇█'


def label(tr):
    if tr is None:
        return '?'
    if tr.get('title'):
        return f"{tr['title']} - {tr['artist']}" if tr.get('artist') else tr['title']
    return f"Deck {tr['deck']}" if tr.get('deck') else '?'


def on_air(tracks, transitions, duration):
    """Each track's on-air span: from the swap into it (or its start) to the swap out of it."""
    into = {t['into']: t['swap'] if t['swap'] is not None else t['start'] for t in transitions}
    starts = [0.0 if i == 0 else (into.get(i) if into.get(i) is not None else tr['start'])
              for i, tr in enumerate(tracks)]
    return [(s, starts[i + 1] if i + 1 < len(starts) else duration) for i, s in enumerate(starts)]


def playing_at(tracks, spans, t):
    for tr, (a, b) in zip(tracks, spans):
        if a <= t < b:
            return tr
    return tracks[-1] if tracks else None


def make_clips(tracks, transitions, moments, audio, duration):
    drops = audio['drops'] if audio else []
    spans = on_air(tracks, transitions, duration)
    used, cands = set(), []
    for t in transitions:
        swap = t['swap'] if t['swap'] is not None else t['moment']
        if swap is None:
            continue
        a, b = tracks[t['into'] - 1], tracks[t['into']]
        slam = [d for d in drops if abs(d - swap) <= 5 and d not in used]
        later = [d for d in drops if 8 <= d - swap <= 30 and d not in used]
        if slam:
            d = slam[0]
            used.add(d)
            cands.append(('slam', d - 20, d + 12, d, t['style'], a, b))
        elif later:
            d = later[0]
            used.add(d)
            cands.append(('transition+drop', swap - 18, d + 10, d, t['style'], a, b))
        else:
            cands.append(('transition', swap - 20, swap + 20, t['moment'] if t['moment'] is not None else swap,
                          t['style'], a, b))
    for d in drops:
        if d not in used:
            tr = playing_at(tracks, spans, d)
            cands.append(('drop', d - 20, d + 12, d, 'drop', tr, tr))
    for m in moments:
        tr = playing_at(tracks, spans, m['moment'])
        cands.append(('moment', m['moment'] - 10, m['moment'] + 15, m['moment'], m['style'], tr, tr))

    clips = []
    for kind, start, end, moment, style, a, b in sorted(cands, key=lambda c: c[1]):
        reasons, score = [], 0.0
        if kind == 'drop' or any(abs(d - moment) <= 1 for d in drops):
            score += 3
            reasons.append('confirmed drop')
        w = WEIGHTS.get(style, 1)
        score += w
        if style != 'drop':
            reasons.append(style)
        if audio:
            from audio import bass_at
            jump = (bass_at(audio, moment + 5) - bass_at(audio, moment - 5)) / audio['F'] if audio['F'] else 0
            jump = max(0.0, min(2.0, jump))
            score += jump
            if jump >= 1:
                reasons.append('big energy jump')
            elif jump >= 0.3:
                reasons.append('energy jump')
        if a and b and a.get('title') and b.get('title'):
            score += 0.5
            reasons.append('both songs named')
        clips.append({'kind': kind, 'start': round(max(0.0, start), 1), 'end': round(min(duration, end), 1),
                      'moment': round(moment, 1), 'style': style, 'score': round(score, 1),
                      'reason': ', '.join(reasons), 'from': label(a), 'to': label(b)})
    for i, c in enumerate(clips):
        c['id'] = f'C{i + 1:02}'
    return [{'id': c.pop('id'), **c} for c in clips]


def stopped_while_audible(moves, tl):
    """Play or cue presses that stopped a deck heard at 0.5 or more for the whole 0.5 s before."""
    out = []
    for m in moves:
        for d in (1, 2):
            t = m['start']
            if m['ctl'] in (f'deck{d}.play', f'deck{d}.cue') and tl.is_playing(d, t - 0.001) \
                    and not tl.is_playing(d, t) and all(tl.level(d, x) >= 0.5 for x in tl.samples(t - 0.5, t - 0.1)):
                out.append((t, d))
    return out


def edit_md(log_name, video, duration, tracks, transitions, moments, audio, audio_reason, moves, tl, clips,
            chapters, names_missing):
    L = []
    add = L.append
    add(f'# Edit sheet: {video.name if video else log_name}')
    add('')
    add(f'Set {stamp(duration)} | {len(tracks)} tracks | {len(transitions)} transitions | {len(clips)} clips')
    add(f'Audio: {"from " + video.name if audio else "skipped, " + audio_reason}')
    if names_missing:
        add(f'Names: {names_missing}')
    add('Times are video time. For any stretch in detail: see the footer.')

    spans = on_air(tracks, transitions, duration)
    add('')
    add('## Now playing (lower thirds)')
    for i, (tr, (a, b)) in enumerate(zip(tracks, spans)):
        show = (tr['start'] if i == 0 else a) + 2
        name = label(tr) if tr.get('title') else f"(unnamed, deck {tr.get('deck')})"
        add(f'{stamp(a)}-{stamp(b)} on air | show {stamp(show)}-{stamp(show + 8)} | {name}'
            + (f" (deck {tr['deck']})" if tr.get('title') and tr.get('deck') else ''))

    add('')
    add('## Transitions')
    for t in transitions:
        a, b = tracks[t['into'] - 1], tracks[t['into']]
        add(f"{stamp(t['moment'])}  {shown_styles(t['styles'])}  {label(a)} -> {label(b)}  | {t['evidence']}")
    if not transitions:
        add('(none)')

    add('')
    add('## Edit cues')
    cues = [(d, 'drop', 'punch in / cut to wide') for d in (audio['drops'] if audio else [])]
    cues += [(m['moment'], m['style'], 'close-up on hands') for m in moments if m['style'] in CLOSE_UP]
    cues += [(t['moment'], t['style'], 'close-up on hands') for t in transitions
             if t['style'] in ('wordplay', 'loop roll', 'scratch', 'spinback')]
    cues += [(a, 'breakdown', f'calm shot / talking overlay, until {stamp(b)}') for a, b in (audio['breakdowns'] if audio else [])]
    for t, what, how in sorted(cues):
        add(f'{stamp(t)}  {what}  -> {how}')
    if not cues:
        add('(none)')

    if audio and audio['energy']:
        add('')
        add('## Energy (bass, one glyph per minute)')
        e = audio['energy']
        for i in range(0, len(e), 10):
            add(f"{stamp(i * 60)}  {''.join(GLYPHS[v] for v in e[i:i + 10])}")
        best = sorted(range(len(e)), key=lambda i: -e[i])[:3]
        add('Thumbnail candidates: ' + ', '.join(f'{stamp(i * 60)}-{stamp(min(duration, i * 60 + 60))}' for i in sorted(best)))

    add('')
    add('## Checks')
    checks = []
    if audio:
        checks += [f'{stamp(a)}-{stamp(b)}  silence' for a, b in audio['silence'] if a > 60 and b < duration - 60]
    for t, d in stopped_while_audible(moves, tl):
        checks.append(f'{stamp(t)}  deck {d} stopped while audible (no fade)')
    starts = [m['start'] for m in moves]
    for a, b in zip(starts, starts[1:]):
        if b - a >= 180:
            checks.append(f'{stamp(a)}-{stamp(b)}  no controller moves for {stamp(b - a)}')
    L += checks or ['(none)']

    add('')
    add(f'## Clips (top {min(TOP_CLIPS, len(clips))} of {len(clips)} by score; tick the ones to make)')
    for c in sorted(clips, key=lambda c: (-c['score'], c['start']))[:TOP_CLIPS]:
        pair = c['from'] if c['from'] == c['to'] else f"{c['from']} -> {c['to']}"
        add(f"- [ ] {c['id']}  {stamp(c['start'])}-{stamp(c['end'])}  {c['kind']}  {c['score']}  {pair}  | {c['reason']}")
    if len(clips) > TOP_CLIPS:
        add(f'{len(clips) - TOP_CLIPS} more in clips.json')

    odd = [t for t in transitions if t['style'] == 'unusual']
    if odd:
        add('')
        add('## Unusual (no known pattern: judge from the moves)')
        left = UNUSUAL_LINES
        for i, t in enumerate(odd):
            if left <= 1:  # out of room: one command covers the rest
                add(f'... {len(odd) - i} more: rekordbox_log.py window "{log_name}" {stamp(t["t0"])} {stamp(odd[-1]["t1"])}')
                break
            lines = window_lines(moves, t['t0'], t['t1'])
            add(f"{stamp(t['t0'])}-{stamp(t['t1'])}  {label(tracks[t['into'] - 1])} -> {label(tracks[t['into']])}")
            left -= 1
            for line in lines[:left]:
                add('  ' + line)
            if len(lines) > left:
                add(f'  ... rekordbox_log.py window "{log_name}" {stamp(t["t0"])} {stamp(t["t1"])}')
                left = 0
            else:
                left -= len(lines)

    add('')
    add('## YouTube chapters')
    L += chapters.rstrip('\n').splitlines()
    add('')
    add('---')
    add(f'More detail for any stretch: `python3 rekordbox_log.py window "{log_name}" <from> <to>` (e.g. 14:00 14:40).')
    return '\n'.join(L) + '\n'
