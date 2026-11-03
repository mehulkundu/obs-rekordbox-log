# Analysis v2: an edit sheet for editors and AI

Date: 2026-11-04. Status: approved in brainstorming, revised after spec review.
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
| `<name>.analysis/moves.jsonl` | 2-5k lines | Scripts, and the `window` command. |
| `<name>.analysis/edit.md` | at most 300 lines | Editors and AI, together with the video. |
| `<name>.analysis/clips.json` | 50-150 entries | Scripts and editing tools. Every clip. |

The v1 outputs (`tracklist.json`, `transitions.json`, `fx.json`, `chapters.txt`) stay.
`transitions.json` drops its per-event `moves` list and gains `style`, `styles`, `moment` and `evidence`.

## 1. Moves (`analysis/moves.py`)

A move is one control moving in one direction: its `ctl` events, with gaps under 0.5 s between them.
A new move starts when the gap is longer, or when the direction reverses (the value goes up after
going down, or down after going up).

- **Faders and knobs:** `{"start","end","ctl","from","to","n"}`, where `n` is the number of events
  merged. A control's first move uses its first logged value as `from`.
- **Jogs and browse** (relative steps): `{"start","end","ctl","steps","n"}`. A move ends when the
  step sign flips.
- **Buttons:** one move per press (`v` = 1), with `start` = `end`. Releases are dropped.

Times are in video time (v1's `vt`). `moves.jsonl` is this list. `window` reads it if it is
there, and otherwise builds it from the raw log.

## 2. Tracks, levels and transition windows

**Tracks** work as in v1: by event order, including tracks loaded before Record, with history
matched by its 60 s delay.

**Levels:** a deck's level is fader × crossfader gain × playing. Controls start at their usual spot:
- channel faders at 1.0
- crossfader at 0.5
- `eq.*`, `cfx`, `trim` and `tempo` at 0.5

Levels are sampled every 0.1 s.

**Overlap:** both decks above 0.3.

**Transition window:** from `start` - 10 s to `end` + 5 s. Without an `end`, it runs to
`swap` + 20 s or the next track's start, whichever comes first.

## 3. Technique rules (`analysis/techniques.py`)

A table of rule functions. Each takes a `Window`: the window's moves, both decks' levels, the audio
features in the window (or none), and the two decks' numbers. Each returns `None` or
`{"style","moment","confidence","evidence"}`:
- `confidence` is `medium`, except `drop swap`, which is `high` when an audio drop lands within
  1 s of its cut.
- `evidence` is one plain line built from the numbers, e.g.
  `deck1 fader 1.00->0.00 and deck2 0.00->1.00 within 0.12 s`.

All rules run. Every match is kept in `styles`, and the first match in table order is `style`.
If nothing matches, the style is `unusual`.

Transitions, in priority order (A = outgoing deck, B = incoming deck; "B starts" means the
transition's `start`, when B becomes audible):

| Style | Rule (starting thresholds; the tests pin them) | Moment |
|---|---|---|
| `wordplay` | A has 3 or more presses of `loop.in`, `loop.half`, any `pad.beatloop.*`, or the same `pad.hotcue.N` in the 8 s before B starts, and B starts within 1 s of A's last such press | B starts |
| `loop roll` | 3 or more presses of `loop.half` or `pad.beatloop.*` on A within 8 s, then A's level drops below 0.1 within 4 s of the last | the last press |
| `spinback` | `deckA.jog` moves (the top platter, not `jog.side` or `jog.search`) totalling -40 steps or fewer within 1 s, then A's level drops below 0.1 within 1 s. Negative = backwards; the sign is checked on the fixture | the burst |
| `double drop` | Both decks at level 0.8 or more with both `eq.low` at 0.4 or more for at least 4 s | where both are full |
| `drop swap` | A's level drops by at least 0.7 and B's rises by at least 0.7, both within 0.3 s of each other, with less than 2 s of overlap before | the cut |
| `echo out` | `fx.beat.on` with the last `fx.beat.channel` = A, within 8 s before A's level drops below 0.1 | A's drop |
| `scratch` | 10 or more `jog` moves on one deck within 5 s, with 4 or more `deckN.fader` or `mixer.crossfader` moves in the same span | the span's start |
| `filter out` | A's `cfx` moves to at least 0.3 from centre while A's level falls | the sweep's end |
| `filter in` | B's `cfx` returns to centre (within 0.05) from at least 0.3 off while B's level rises | the sweep's end |
| `three-band swap` | For each of low, mid and high, B goes up and A goes down within 2 s of each other, with the three bands at least 2 s apart | the low swap |
| `bass swap` | B's `eq.low` is 0.2 or below when B starts, then B's low rises above 0.4 and A's falls below 0.2 within 2 s of each other | the low crossing |
| `tempo ramp` | A's or B's `tempo` moves by at least 0.05 during the overlap | mid-ramp |
| `crossfader cut` | 4 or more `mixer.crossfader` moves of more than 0.5 each within 3 s | the first move |
| `long blend` | Overlap of at least 16 s | the swap |
| `quick mix` | Overlap under 4 s | the swap |

The edit sheet shows `unusual` windows with their moves, so an AI can judge them (see section 6).

Moments outside transitions are found across the whole set, with the same shape:
- `loop roll` and `scratch`, as above
- `hot cue juggling`: 6 or more `pad.hotcue.*` presses on one deck within 8 s
- `sampler hit`: `pad.sampler.*` presses, with presses less than 8 s apart merged into one moment
- `beat fx`: each `fx.beat.on` span
- `filter sweep`: each `cfx` move of at least 0.3 from centre
- `drop mixing`: 3 or more `drop swap`s in a row, with each track on for under 60 s

A moment inside a transition window whose `styles` already holds it is skipped.

## 4. Audio (`analysis/audio.py`)

- **Video:** the file next to the log with the same base name and a video extension (`.mov`,
  `.mp4`, `.mkv`, `.flv`, `.ts`, `.m4v`), or `--video PATH`. The audio is read through ffmpeg as
  mono, 11,025 Hz, 32-bit float PCM on stdout. Its time base is the video's, the same as `vt`.
- **Features**, every 0.1 s (numpy FFT over 0.2 s frames): `bass` (30-150 Hz energy) and `rms`.
  `bass` is smoothed with a 1 s moving mean before any threshold, so the dips between kicks don't
  count. `F` = 0.7 × the set's 95th-percentile smoothed bass, and "full" means at least `F`.
- **Drops:** the smoothed bass reaches `F` and stays there for 8 s, after 20 s with no 2 s stretch
  at `F`. A re-hit within 6 s of the last drop is the same drop. The drop time then moves back to
  the first frame within 2 s before it where the raw `bass` passes 0.5F, which is the first kick.
- **Breakdowns:** at least 16 s with smoothed bass under 0.3F, after a drop.
- **Silence:** `rms` under -50 dBFS for at least 1 s.
- **Energy:** the mean smoothed bass per minute, scaled 0-7 against the set's loudest minute.
- **Skipped:** if the video is missing, ffmpeg is missing, or the audio is silent (peak under -60
  dBFS), audio is skipped and `edit.md` says why in its header.

## 5. Clips

Every transition, every drop and every moment becomes a candidate. The windows:

| Kind | Window |
|---|---|
| `slam` | drop - 20 s to drop + 12 s, when a drop lands within 5 s either side of a swap |
| `transition+drop` | swap - 18 s to drop + 10 s, when a drop lands 8-30 s after a swap |
| `transition` | swap - 20 s to swap + 20 s |
| `drop` | drop - 20 s to drop + 12 s |
| `moment` | moment - 10 s to moment + 15 s |

- **Combining:** a `slam` or `transition+drop` replaces both the transition's clip and the drop's.
  A drop 5-8 s from a swap gives two separate clips. Windows are clamped to the video.
- **Score:** the sum of:
  - **Confirmed drop**, +3: an audio drop lands within 1 s of the clip's moment. Drop clips
    always count.
  - **Style weight:**
    - 3: `drop swap`, `double drop`, `wordplay`
    - 2: `loop roll`, `scratch`, `hot cue juggling`, `spinback`, `drop mixing`
    - 1.5: `echo out`, `unusual`
    - 1: `filter out`, `filter in`, `bass swap`, `three-band swap`, `tempo ramp`,
      `crossfader cut`, `filter sweep`, `beat fx`, `sampler hit`
    - 0.5: `long blend`, `quick mix`
    - 0: `drop` clips
  - **Energy jump**, 0-2: smoothed bass 5 s after the moment minus 5 s before, scaled.
  - **Both songs named**, +0.5.
- **Reason:** the parts of the score in words, e.g.
  `confirmed drop, drop swap, big energy jump, both songs named`.
- **IDs:** `C01`, `C02`, ... in time order, so they stay stable between runs.
- **`clips.json`** holds every clip: `[{"id","kind","start","end","moment","style","score","reason","from","to"}]`.

## 6. `edit.md`

Times are `m:ss`, or `h:mm:ss` past an hour. The sections, in order:

1. **Header**: the video file, the set length, the track count, and what was missing: audio (and
   why), or names (tracks under 60 s, or no `pyrekordbox`).
2. **Now playing (lower thirds)**: one line per track, in order. This also serves as the tracklist. A
   track is shown at swap + 2 s for 8 s (the first track at its start + 2 s), with its on-air
   span, e.g. `01:19-14:41 on air | show 01:21-01:29 | Vatta Vatta - AFTERAll (deck 1)`. A track
   with no name is listed as `(unnamed, deck 2)`.
3. **Transitions**, e.g.
   `01:19  bass swap  Vatta Vatta -> Deck 2  | deck2 low 0.05->0.92 while deck1 low 0.88->0.10 within 1.4 s`.
4. **Edit cues**, one line each, in time order:
   - drops: `punch in / cut to wide`
   - technique moments: `close-up on hands`
   - breakdowns: `calm shot / talking overlay`
5. **Energy**: one line per 10 minutes, a 10-character bar (`▁▂▃▄▅▆▇█`, one glyph per minute). The 3
   highest minutes are marked as thumbnail candidates.
6. **Checks**:
   - silence, excluding the first and last 60 s
   - a deck stopping while audible: play or cue pressed when the deck's level was 0.5 or more
     for the whole 0.5 s before
   - 3 minutes or more with no controller moves
7. **Clips**: the top 30 by score, e.g.
   `- [ ] C07  14:21-14:53  slam  8.0  Jiya Jale -> Dum Maro Dum  | confirmed drop, drop swap, ...`
   Each can be ticked in Obsidian or named to an AI. Then a line saying how many more are in `clips.json`.
8. **Unusual**: each `unusual` transition's moves, with at most 40 lines in this section. After that, a
   `window` command for the rest.
9. **YouTube chapters**: ready to paste.
10. **Footer**: how to get more detail (`rekordbox_log.py window <log> <from> <to>`).

**Budget:** at most 300 lines for a 1-hour set with 25 tracks: about 25 now playing, 24 transitions, 40 cues,
6 energy, 31 clips, 40 unusual, 25 chapters and 20 headers and blanks. A test checks it.

## 7. `window` command

`python3 rekordbox_log.py window LOG FROM TO` prints the moves between `FROM` and `TO` (`m:ss` or
seconds), one line each, e.g. `14:02.3-14:03.1  deck2.eq.low  0.50 -> 0.02  (12)`, or
`14:05.0-14:05.4  deck1.jog  -38 steps  (20)`. It needs no audio and no history.

## Files

The code lives in `analysis/rekordbox_log.py` (CLI, v1 logic), `moves.py`, `techniques.py`,
`audio.py` and `sheet.py` (`edit.md` and `clips.json`). Tests are in `analysis/test_analysis.py`:
plain `assert`s, run as `python3 analysis/test_analysis.py`. `--selftest` keeps working.

The two real logs become gzipped fixtures:
- `analysis/fixtures/flx4-bassswap.jsonl.gz`, from `~/Movies/2026-11-04 00-16-43.rekordbox.jsonl`
- `analysis/fixtures/flx4-cues.jsonl.gz`, from `~/Movies/2026-11-04 00-23-53.rekordbox.jsonl`

## Testing

- One case per transition style and per moment, built from made-up moves that just meet the
  rule and just miss it.
- Moves: a back-and-forth crossfader chop gives one move per direction, and a jog burst gives a
  `steps` sum.
- Real fixtures: `flx4-bassswap` gives one transition whose `styles` include `bass swap`, with its
  moment between 1:15 and 1:23. Both fixtures come in under the line budget scaled to their length.
- Audio: a generated 90 s signal gives one drop at 30.0 s ± 0.1 s, with no breakdown and no silence.
  The signal is quiet for 30 s, then kick-like 60 Hz pulses at 128 BPM. A silent file skips audio
  with a reason.
- `edit.md` from a made-up 1-hour, 25-track set is at most 300 lines.

## Out of scope

- Naming tracks under 60 s by matching their audio against the library files.
- Rekordbox phrase analysis (intro/chorus/outro from the ANLZ files).
- The replay app.
- Telling whether a mix sounded good (beatmatching, key clashes).
