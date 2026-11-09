# Analysis v2: an edit sheet for editors and AI

Date: 2026-11-04. Status: approved. Revised after spec review, then against the two real recordings while drafting the plan.
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

The FX channel lever (`fx.beat.channel`) counts as a position control, and its value is the
deck number. Times are in video time (v1's `vt`). `moves.jsonl` is this list, for scripts. `window`
builds the moves from the raw log.

## 2. Tracks, levels and transition windows

**Tracks** work as in v1: by event order, including tracks loaded before Record, with history
matched by its 60 s delay.

**Track list:** names come from `<name>.tracks.json` (see `docs/format.md`), which the plugin writes
on Stop, so the log, video and track list can be analysed on any computer. Without it, the
analysis reads Rekordbox through pyrekordbox, up to 70 s after the end, and writes the file. Hand
fixes (`start` rows) name the track starting nearest that time.

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
If nothing matches, the style is `unusual`. The order is: tricks first, then how the decks were
mixed, then how the old track left, then blends. The sheet shows all of a transition's styles,
joined with ` + `, leaving out the blend kinds when anything else matched.

Transitions, in priority order (A = outgoing deck, B = incoming deck; "B starts" means the
transition's `start`, when B becomes audible):

| Style | Rule (starting thresholds; the tests pin them) | Moment |
|---|---|---|
| `wordplay` | A has 3 or more presses of `loop.in`, `loop.half`, any `pad.beatloop.*`, or the same `pad.hotcue.N` in the 8 s before B starts, and B starts within 1 s of A's last such press | B starts |
| `loop roll` | 3 or more presses of `loop.half` or `pad.beatloop.*` on A within 8 s, then A's level drops below 0.1 within 4 s of the last | the last press |
| `spinback` | `deckA.jog` moves (the top platter, not `jog.side` or `jog.search`) totalling -40 steps or fewer within 1 s, then A's level drops below 0.1 within 1 s. Negative = backwards; the sign is checked on the fixture | the burst |
| `double drop` | Both decks at level 0.8 or more with both `eq.low` at 0.4 or more for at least 4 s, with an audio drop in that stretch. Without the audio this is only a blend with the EQs left alone | the audio drop |
| `drop swap` | A's level drops by at least 0.7 and B's rises by at least 0.7, both within 0.3 s of each other, with less than 2 s of overlap before | the cut |
| `scratch` | 10 or more `jog` moves on one deck within 5 s, with 4 or more `deckN.fader` or `mixer.crossfader` moves in the same span | the span's start |
| `three-band swap` | A band swap (below) for each of low, mid and high, with the three at least 2 s apart | the low swap |
| `bass swap` | A low swap: a move of B's `eq.low` from 0.2 or below to above 0.4, and a move of A's `eq.low` from above 0.2 to below 0.2, ending within 4 s of each other (about 2 bars at 128 BPM). DJs often swap back and forth, so the moment is the last swap in the window | the last low swap |
| `echo out` | `fx.beat.on` turning the effect on while `fx.beat.channel` = A, within 8 s before A's level drops below 0.1 | A's drop |
| `filter out` | A's `cfx` moves to at least 0.3 from centre while A fades: A's level 4 s after the move is at least 0.2 below its level at the start | the sweep's end |
| `filter in` | B's `cfx` moves back to centre (within 0.05) from at least 0.3 off while B rises: B's level at the end is at least 0.2 above its level 4 s before the start | the sweep's end |
| `tempo ramp` | A's or B's `tempo` moves during the overlap add up to a change of at least 0.05. This is measured from moves, because an untouched slider's real position is unknown | mid-ramp |
| `crossfader cut` | 4 or more `mixer.crossfader` moves of more than 0.5 each within 3 s | the first move |
| `long blend` | Overlap of at least 16 s | the swap |
| `quick mix` | Overlap under 4 s | the swap |

The edit sheet shows `unusual` windows with their moves, so an AI can judge them (see section 6).

Moments outside transitions are found across the whole set, with the same shape:
- `loop roll` and `scratch`, as above
- `hot cue juggling`: 6 or more `pad.hotcue.*` presses on one deck within 8 s
- `sampler hit`: `pad.sampler.*` presses on one deck, with presses less than 8 s apart merged into one moment
- `beat fx`: each `fx.beat.on` span, with its channel
- `filter sweep`: `cfx` moves to at least 0.3 from centre on one deck, with sweeps less than 8 s apart merged
- `drop mixing`: 3 or more `drop swap`s in a row, with each track on for under 60 s

A moment is skipped when a transition already has a match that covers it, within 5 s of it: `loop roll` by `loop roll` or `wordplay`, `scratch` by `scratch`, `filter sweep` by `filter out` or `filter in`, and `beat fx` by `echo out`.

## 4. Audio (`analysis/audio.py`)

- **Video:** the file next to the log with the same base name and a video extension (`.mov`,
  `.mp4`, `.mkv`, `.flv`, `.ts`, `.m4v`), or `--video PATH`. The audio is read through ffmpeg as
  mono, 11,025 Hz, 32-bit float PCM on stdout. Its time base is the video's, the same as `vt`.
- **Features**, every 0.1 s (numpy FFT over 0.2 s frames): `bass` (30-150 Hz energy) and `rms`.
  `bass` is smoothed before any threshold, so the dips between kicks don't count: first a 0.6 s
  moving maximum (this bridges the gap between kicks at 100 BPM and up), then a 1 s moving mean.
  "Full" means at least `F`, and `F` follows the music: 0.8 × the 80th percentile of the smoothed
  bass within 45 s either side. A single threshold for the whole set fails because DJs mix tracks at
  very different bass levels (on a real set, the quieter tracks never reached it). The 80th percentile
  means one loud burst can't drag `F` up; ±45 s beats ±30 s and ±60 s on the real set.
- **Drops** are a jump in the waveform: the energy falls away (a breakdown or build), then the bass
  and the loudness come back much higher and stay there. On a real set the DJ's three drops (1:30, 2:48,
  4:36) jumped +10 to +50 dB in bass and +7 to +12 dB in loudness. A frame is a drop when:
  - the smoothed bass in the 3 s after is at least 8 dB above the 3 s before, and loudness 5 dB above
  - every second from 3 to 10 s after stays at least 5 dB above the level before (it holds; a burst
    or a single hit doesn't)
  - at least 80% of the 5 s to 1 s before is music, not silence (the set starting isn't a drop)
  - the bass 5-12 s before wasn't already within 6 dB of the new level (that's a re-hit after a short
    cut, the same drop)
  Jumps within 8 s are one drop, at the frame with the biggest jump, moved to the first kick: the first
  frame from 3 s before where the raw bass is within 5 dB of the new level. Drops 6 s apart or less
  merge. In the analysis, a drop within 2 s of a fader or low EQ being raised by 0.3 or more over more
  than 0.4 s is a track being mixed in, not a drop. A fader slammed up at the jump (a drop swap) keeps it.
  A jump while the DJ rides the Beat FX level (within 2 s of a level move, with the effect on) is the
  effect, not a drop: on the real set, 6:17 was this, and the DJ confirmed it isn't a drop.
- **Beat FX state at Record:** Rekordbox keeps the effect's on/off state, and the log can't see it at
  Record. DJs ride the level knob while the effect is on, so the timeline starts the effect on if that
  puts more level moves inside on-stretches than starting it off would.
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
  - **Energy jump**, 0-2: (smoothed bass 5 s after the moment minus 5 s before) ÷ `F`,
    clamped to 0-2. It is 0 without audio.
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
- Real fixtures:
  - `flx4-bassswap` gives one transition with style `bass swap` and its moment between 1:10 and
    1:15, the last of two low swaps (1:12.4). `filter out` is also in its `styles`.
  - `flx4-cues` gives a `bass swap` between 1:45 and 1:52. Its knobs moved 2.4 s apart.
  - Both come in under the line budget scaled to their length.
- Audio: a generated 90 s signal gives one drop at 30.0 s ± 0.1 s, with no breakdown and no silence.
  The signal is quiet for 30 s, then kick-like 60 Hz pulses at 128 BPM. A silent file skips audio
  with a reason.
- `edit.md` from a made-up 1-hour, 25-track set is at most 300 lines.

## Out of scope

- Naming tracks under 60 s by matching their audio against the library files (a hand fix in the
  track list covers it).
- Rekordbox phrase analysis (intro/chorus/outro from the ANLZ files).
- The replay app.
- Telling whether a mix sounded good (beatmatching, key clashes).
