# Analysis v2: an edit sheet for editors and AI

Date: 2026-11-04. Status: approved in brainstorming, awaiting spec review.
Builds on `2026-11-03-obs-rekordbox-log-design.md`. The plugin and the raw log do not change.

## Why

A real test set (DDJ-FLX4, Rekordbox 7.2) wrote 3,000-7,000 raw lines in 1.5-2 minutes. That is
7-20 MB, or 90,000-280,000 lines, for a 1-hour set, far past any AI agent's context. The raw log
stays, because it is the full-detail record a future replay app needs. But nobody should have to read it.
Editors and AI need a short sheet: which song is on, what kind of transition happened and when,
where the drops are, and every clip worth cutting.

## Layers

| File | 1-hour size | Reader |
|---|---|---|
| `<name>.rekordbox.jsonl` (raw, unchanged) | 7-20 MB | Replay tools. Never handed to an AI. |
| `<name>.analysis/moves.jsonl` | 2-3k lines | Scripts. AI uses it only through `window`. |
| `<name>.analysis/edit.md` | at most 300 lines | Editors and AI, together with the video. |
| `<name>.analysis/clips.json` | 50-150 entries | Scripts and editing tools. |

The v1 outputs (`tracklist.json`, `transitions.json`, `fx.json`, `chapters.txt`) stay.
`transitions.json` drops its per-event `moves` list and gains `style`, `moment` and `evidence`.

## 1. Moves (`analysis/moves.py`)

A move is one control moving continuously: its `ctl` events with gaps under 0.5 s between them.
`{"start","end","ctl","from","to","n"}` (`n` = events merged). For a button, a move is one
press (`v` = 1) with `start` = `end`. Releases are dropped. Times are in video time (v1's `vt`).
On the two real logs this gives 81 and 68 moves, from 7,284 and 3,172 lines.

## 2. Tracks and transition windows

As v1 (event order, tracks loaded before Record, history matched by its 60 s delay, levels from
fader x crossfader x playing). Each transition window runs from `start` - 10 s to `end` + 5 s.
Without an `end`, it runs to `swap` + 20 s, or to the next track's start.

## 3. Technique rules (`analysis/techniques.py`)

A table of rule functions. Each takes a `Window`: the window's moves, both decks' levels sampled
every 0.1 s, the audio features in the window (or none), and the two decks' numbers. Each returns
`None` or `{"style","moment","confidence","evidence"}`:
- `moment` is the time the editor needs.
- `confidence` is `high`, `medium` or `low`.
- `evidence` is one plain line built from the numbers, e.g.
  `deck1 fader 1.00->0.00 and deck2 0.00->1.00 within 0.12 s`.

All rules run. Every match is kept in `styles`. The match with the highest priority (first in the
table below) and then the highest confidence is the transition's `style`. If nothing matches,
the style is `unusual`, and `edit.md` lists the window's moves, at most 60 lines, for an AI to judge.

Transitions, in priority order (A = outgoing deck, B = incoming deck):

| Style | Rule (starting thresholds; the tests pin them) | Moment |
|---|---|---|
| `wordplay` | A has a loop (`loop.in`, `loop.half`, `pad.beatloop.*`) or the same hot cue at least 3 times in the 8 s before B becomes audible, and B starts within 1 s of A's last loop or cue press | B's start |
| `loop roll` | At least 3 presses of `loop.half` or of shorter `pad.beatloop.*` on A within 8 s, then A's level drops below 0.1 within 4 s | the last press |
| `spinback` | A jog burst on A totalling at most -40 steps in under 1 s, then A's level drops below 0.1 within 1 s | the burst |
| `double drop` | Both decks at level 0.8 or more with both `eq.low` 0.4 or more for at least 4 s | where both are full |
| `drop swap` | A's level drops by at least 0.7 and B's rises by at least 0.7, both within 0.3 s of each other, with less than 2 s of both above 0.3 before | the cut |
| `echo out` | Beat FX turned on with channel = A within 8 s before A's level drops below 0.1 | A's drop |
| `scratch` | At least 10 `jog` moves on one deck within 5 s, with at least 4 fader or crossfader reversals in the same span | the span's start |
| `filter out` / `filter in` | A's `cfx` moves at least 0.3 from centre while A fades out / B's `cfx` returns from at least 0.3 off centre while B fades in | the sweep's end |
| `three-band swap` | The low, mid and high EQ of both decks swap (B goes up and A goes down for the same band within 2 s), with the bands at least 2 s apart | the low swap |
| `bass swap` | B's `eq.low` is 0.2 or below when B becomes audible, then B's low rises above 0.4 and A's falls below 0.2 within 2 s of each other | the low crossing |
| `tempo ramp` | The `tempo` of A or B moves at least 0.05 during the overlap | mid-ramp |
| `crossfader cut` | At least 4 crossfader reversals of more than 0.5 within 3 s | the first reversal |
| `long blend` | Both decks above 0.3 for at least 16 s and none of the above | the swap |
| `quick mix` | Both above 0.3 for under 4 s, with no cut | the swap |

Moments that are not transitions are found across the whole set, with the same `{style, moment,
confidence, evidence}` shape: `loop roll`, `scratch`, `hot cue juggling` (at least 6 hot cue
presses on one deck within 8 s), `sampler hit` (any `pad.sampler.*` press), `beat fx` (each
`fx.beat.on` span), `filter sweep` (each `cfx` move of at least 0.3 outside a transition), and
`drop mixing` (3 or more `drop swap`s in a row with each track on for under 60 s).

## 4. Audio (`analysis/audio.py`)

- **Video:** the file next to the log with the same base name and a video extension (`.mov`,
  `.mp4`, `.mkv`, `.flv`, `.ts`, `.m4v`), or `--video PATH`. The audio is read through ffmpeg as
  mono, 11,025 Hz, 32-bit float PCM on stdout. Its time base is the video's, the same as `vt`.
- **Features**, every 0.1 s (numpy FFT over 0.2 s frames): `bass` (30-150 Hz energy) and `rms`.
  `full` = bass at or above 70 % of the set's 95th-percentile bass.
- **Drops** (the rule from `dj/video/SHORTS.md`): bass becomes `full` and holds for 8 s after
  20 s with no 2 s stretch of `full`. A re-hit within 6 s of the last drop is the same drop. The
  drop time then moves back to the first frame within 2 s before it where `bass` passes 50 % of
  `full`, which is the first kick.
- **Breakdowns:** at least 16 s with bass under 30 % of `full`, after a drop.
- **Silence:** `rms` under -50 dBFS for at least 1 s.
- **Energy:** the mean `bass` and `rms` per minute, scaled 0-8.
- If the video is missing, ffmpeg is missing or the audio is silent (peak under -60 dBFS), audio
  is skipped and `edit.md` says why in its header. A `drop swap` is `high` confidence only when a
  drop lands within 1 s of its cut.

## 5. Clips

Every transition, every drop and every non-transition moment becomes a candidate, with windows
from `SHORTS.md`:

| Kind | Window |
|---|---|
| `transition` | swap - 20 s to swap + 20 s |
| `drop` | drop - 20 s to drop + 12 s |
| `transition+drop` | swap - 18 s to drop + 10 s, when a drop lands 8-30 s after a swap |
| `slam` | drop - 20 s to drop + 12 s, when a drop lands within 5 s of a swap |
| `moment` | moment - 10 s to moment + 15 s |

- A drop that becomes a `transition+drop` or a `slam` does not also produce its own `drop`
  clip. Windows are clamped to the video.
- **Score** = drop confirmed by audio (+3) + style weight (`drop swap`, `double drop`,
  `wordplay` 3; `loop roll`, `scratch`, `hot cue juggling`, `spinback`, `drop mixing` 2; `echo out`,
  `unusual` 1.5; `filter out/in`, `bass swap`, `three-band swap`, `tempo ramp`, `crossfader cut`,
  `filter sweep`, `beat fx`, `sampler hit` 1; `long blend`, `quick mix` 0.5) + energy jump
  (bass 5 s after the moment minus 5 s before, scaled 0-2) + 0.5 when both songs are named.
- **Reason:** the parts of the score in words, e.g.
  `confirmed drop, drop swap, big energy jump, both songs named`.
- **IDs:** `C01`, `C02`, ... in time order, so they stay stable between runs.
- `edit.md` lists the clips by score, and nothing is cut.
- **`clips.json`:** `[{"id","kind","start","end","moment","style","score","reason","from","to"}]`.

## 6. `edit.md`

Times are `m:ss`, or `h:mm:ss` past an hour. The sections, in order:

1. **Header**: the video file, the set length, the track count, and what was missing: audio
   (and why), or names (tracks under 60 s, or no `pyrekordbox`).
2. **Tracklist**: `01:19  Vatta Vatta - AFTERAll  (deck 1)`.
3. **Lower thirds**: one per track, shown at swap + 2 s for 8 s (the first track at its start + 2 s), with its
   on-air span: `01:19-14:41 on air | show 01:21-01:29 | Vatta Vatta - AFTERAll`. A track with no name
   is still listed, as `(unnamed, deck 2)`.
4. **Transitions**: `01:19  bass swap  Vatta Vatta -> Deck 2  | deck2 low 0.05->0.92 while deck1 low 0.88->0.10 within 1.4 s`.
5. **Edit cues**: drops (`punch in / cut to wide`), technique moments (`close-up on hands`),
   breakdowns (`calm shot / talking overlay`). One line each, in time order.
6. **Energy**: one line per 10 minutes, a 10-character bar (`▁▂▃▄▅▆▇█`) for bass. The 3 highest-energy
   moments are marked as thumbnail candidates.
7. **Checks**: silence in the middle of the set, a deck stopping while audible (play or cue pressed at
   level 0.5 or more, with no fade), and 3 minutes or more with no controller moves.
8. **Clips**: `- [ ] C07  14:21-14:53  slam  8.0  Jiya Jale -> Dum Maro Dum  | confirmed drop, drop swap, ...`,
   by score, so they can be ticked in Obsidian or named to an AI.
9. **Unusual**: each `unusual` transition with its moves, at most 60 lines each.
10. **YouTube**: chapters, then a description block with the timestamped tracklist.
11. **Footer**: how to get more detail (`rekordbox_log.py window <log> <from> <to>`).

**Budget:** at most 300 lines for a 1-hour set with 25 tracks. A test checks it.

## 7. `window` command

`python3 rekordbox_log.py window LOG FROM TO` prints the moves between `FROM` and `TO` (`m:ss` or
seconds), one line each: `14:02.3-14:03.1  deck2.eq.low  0.50 -> 0.02  (12)`. It needs no audio and
no history.

## Files

`analysis/rekordbox_log.py` (CLI, v1 logic), `moves.py`, `techniques.py`, `audio.py`, `sheet.py`
(`edit.md` and `clips.json`). Tests in `analysis/test_analysis.py`, plain `assert`s, run as
`python3 analysis/test_analysis.py`. `--selftest` keeps working. The two real logs go in as
fixtures, gzipped: `analysis/fixtures/flx4-bassswap.jsonl.gz` and `flx4-cues.jsonl.gz`.

## Testing

- One case per transition style and per moment, built from made-up moves that just meet the
  rule and just miss it.
- Real fixtures: `flx4-bassswap` gives one transition whose `styles` include `bass swap`, with its
  moment between 1:15 and 1:23. Both fixtures come in under the line budget scaled to their length.
- Audio: a generated 90 s signal (a 60 Hz tone that is quiet for 30 s, then full) gives one drop
  at 30.0 s ± 0.1 s, with no breakdown and no silence. A silent file skips audio with a reason.
- `edit.md` from a made-up 1-hour, 25-track set is at most 300 lines.

## Out of scope

- Naming tracks under 60 s by matching their audio against the library files.
- Rekordbox phrase analysis (intro/chorus/outro from the ANLZ files).
- The replay app.
- Telling whether a mix sounded good (beatmatching, key clashes).
