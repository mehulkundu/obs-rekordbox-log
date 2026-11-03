# obs-rekordbox-log: design

Date: 2026-11-03. Status: approved in brainstorming, awaiting spec review.
Open source (MIT) at github.com/mehulkundu/obs-rekordbox-log.

## Goal

When a DJ records or streams a set in OBS, keep a timestamped log of what happened in
Rekordbox: which track was playing, how the decks were mixed (faders, crossfader, EQ, trim,
tempo), which effects were used and when each transition happened. The log starts and stops
with the OBS output, so its timeline matches the video's. Afterwards, the log and the video
go to an editor, a script or an AI to find transitions and drops, cut shorts and write
chapters, without guessing them from the audio.

## v1 target

- macOS on Apple Silicon, OBS 33+, Rekordbox 6/7 in Performance mode.
- Named controls for the Pioneer DJ DDJ-FLX4. Every other MIDI controller is still logged as
  raw MIDI.
- Rekordbox has no public API, so data comes from two places:
  1. **The controller's MIDI.** CoreMIDI lets a second client read a source Rekordbox is also
     reading, without affecting Rekordbox. This gives every physical action, timed to the
     millisecond.
  2. **Rekordbox's play history** in `master.db` (SQLCipher), read with
     [pyrekordbox](https://github.com/dylanljones/pyrekordbox). Checked on Rekordbox 7.2:
     `djmdSongHistory` rows carry `created_at` with millisecond precision and link to
     `djmdContent` (title, artist, BPM, key, file path).

## Split

The plugin records raw facts only. Everything derived (tracklist, transitions, FX spans,
chapters) is computed after the set by a Python script in this repo. The analysis can
improve without rebuilding the plugin, and the plugin never touches the encrypted database.

```
obs-rekordbox-log/
  src/            OBS plugin (C++)
  tests/          plugin unit tests
  analysis/       rekordbox_log.py
  docs/
```

## Part 1: the OBS plugin

Built from `obsproject/obs-plugintemplate` (CMake, Qt 6, its GitHub Actions for builds) with
`ENABLE_FRONTEND_API` and `ENABLE_QT` on, producing `obs-rekordbox-log.plugin`, installed to
`~/Library/Application Support/obs-studio/plugins/`.

| File | Responsibility |
|---|---|
| `src/plugin-main.cpp` | Module load/unload. Registers an `obs_frontend` event callback for `RECORDING_STARTED/STOPPED/PAUSED/UNPAUSED`, `STREAMING_STARTED/STOPPED` and `EXIT`. Starts one `Session` per active output. On `EXIT` it closes all sessions. In unload, it disposes the MIDI client first, then frees sessions. |
| `src/session.{h,cpp}` | One log file. Opens on output start, appends one JSON line per event, `fflush`es after each line, closes on stop. Holds the start host time and computes `t`. A global mutex guards both the list of open sessions and the writes, because sessions open and close on the UI thread while the MIDI thread writes. |
| `src/midi.{h,cpp}` | CoreMIDI client, created on the main thread (setup-change notifications arrive on the run loop of the creating thread). One input port via `MIDIInputPortCreateWithProtocol(kMIDIProtocol_1_0)`. It delivers `MIDIEventList`s of Universal MIDI Packets: one channel-voice message per 32-bit word (message type 2), so there is no running-status parsing. SysEx and other UMP types are logged raw. It connects to every source, with a refCon that is an index into a table of source names owned by `midi.cpp` and kept for the plugin's lifetime. On `kMIDIMsgSetupChanged` it reconnects to new sources and logs `device` events. For each message, it asks the mapper for a name and forwards a `ctl` or `midi` event to all open sessions. |
| `src/controllers.{h,cpp}` | A small stateful mapper: (source name, MIDI 1.0 message) to `{ctl, v}` or nothing. Holds one table per supported controller, picked by a substring of the source name. v1 has one table: DDJ-FLX4, from Pioneer DJ's published MIDI message list. For 14-bit controls (MSB/LSB CC pairs), it caches the last MSB per (source, channel, CC) and emits on the LSB, scaled to 0..1. Buttons give 1/0. Jog gives a signed delta. Adding a controller means adding a table. No OBS or CoreMIDI dependency, so it can be unit-tested. |
| `src/dock.cpp` | Read-only Qt dock "Rekordbox Log", added with `obs_frontend_add_dock_by_id`. It shows the MIDI devices seen (and whether each one has named controls), which outputs are logging, the event count and the last error. Refreshed by a 500 ms `QTimer` reading atomics. No settings. |

### Control names (DDJ-FLX4)

`deck{1,2}.` + `play`, `cue`, `sync`, `load`, `tempo`, `jog`, `jog.touch`, `fader`, `trim`,
`eq.hi`, `eq.mid`, `eq.low`, `cfx`, `headphone.cue`, `pad.mode.{hotcue,padfx,beatjump,sampler}`,
`pad.{1..8}`, `shift`;
`mixer.crossfader`, `mixer.master`, `fx.beat.on`, `fx.beat.select`, `fx.beat.level`,
`fx.beat.channel`, `fx.smartcfx`, `fx.smartfader`. The exact set comes from the MIDI message
list. Anything missing is caught by the raw fallback. Other controllers should reuse these
names where the control means the same thing, so the analysis works unchanged.

### Timing

- `t` = seconds since the `*_STARTED` frontend event, on the host clock.
  `mach_absolute_time()` and incoming `MIDITimeStamp`s count the same ticks, which are not
  nanoseconds (125/3 ns on Apple Silicon). Convert with `mach_timebase_info`. If an incoming
  timestamp is 0, use `mach_absolute_time()` at receipt.
- `t` is wall time on the recording's clock, pauses included. Recording pause and unpause
  write `pause` and `resume` events, and the analysis subtracts paused time to get video time.
- The frontend event fires a few ms after the output starts. The header carries
  `offset_ms: 0`, which the analysis adds to every `t`. It can be edited by hand if a clap
  test shows drift.
- The header carries `wall` (ISO 8601, local offset, ms) so history rows can be joined.

### File naming

- Record: at `RECORDING_STARTED`, `obs_frontend_get_last_recording()` already returns the
  new file (OBS sets the path before the output starts; `bfree` the result). The log is that
  path with its extension replaced by `.rekordbox.jsonl`. The extension is stripped because
  auto-remux can turn `.mkv` into `.mp4` after stop. No rename. With automatic file
  splitting, the log is named after the first segment and `t` covers the whole recording.
- Stream: `<recording folder>/<YYYY-MM-DD HH-MM-SS>-stream.rekordbox.jsonl`. The folder comes from
  `obs_frontend_get_profile_config`: `SimpleOutput/FilePath` in simple mode, and
  `AdvOut/RecFilePath` (or `AdvOut/FFFilePath` when `AdvOut/RecType` is `FFmpeg`) in advanced mode.
- Record and stream running together give two files with their own start times.

### Event format (JSON Lines, version 1)

```
{"type":"session","v":1,"output":"record","wall":"2026-11-03T21:00:01.123+05:30","offset_ms":0,"obs":"33.0.1","plugin":"0.1.0"}
{"t":15.002,"type":"ctl","src":"DDJ-FLX4","ctl":"deck1.play","v":1}
{"t":15.210,"type":"ctl","src":"DDJ-FLX4","ctl":"deck2.eq.low","v":0.42}
{"t":301.500,"type":"midi","src":"DDJ-FLX4","raw":[176,31,64]}
{"t":412.000,"type":"device","src":"DDJ-FLX4","state":"disconnected"}
{"t":900.000,"type":"pause"}
{"t":930.000,"type":"resume"}
{"t":3600.120,"type":"end"}
```

All events are logged, jog included. A 1-hour set is expected to be a few MB to a few tens of MB.
If size becomes a problem, coalesce jog deltas per 50 ms. The format is documented in
`docs/format.md`, so other tools can read it.

### Errors

- No MIDI device at start: keep logging (the header still marks the session). Hot-plug
  connects devices later.
- File can't be opened: `blog(LOG_ERROR)`, the dock shows the error, and OBS output is not touched.
- Never block the OBS UI thread. The MIDI callback runs on CoreMIDI's thread, and writes are short and mutex-guarded.
- OBS crash: every line is already flushed. The missing `end` line marks the log as cut short.

## Part 2: analysis (`analysis/rekordbox_log.py`)

`python3 rekordbox_log.py <log.jsonl> [--out DIR]`. Needs only `pyrekordbox`; everything else is
the standard library. It writes:

All output times are video time: `t + offset_ms/1000` minus any paused time before it.

**Starting state.** MIDI only reports changes, so every control is unknown until it is first
touched. The analysis assumes: channel faders up (1.0) and crossfader centred (0.5), with
EQ, trim and CFX at centre (0.5) until their first event.

- `tracklist.json`: history rows with `created_at` between the session's `wall` start and
  its end (the `end` line, or the last event). Rows are treated as naive local time and
  converted to `t`. Each row gets title, artist, BPM, key and path. Each track is assigned a
  deck by pairing it with the nearest preceding `deckN.load` not already used. Its start
  becomes that deck's next `deckN.play` press. If there is no load (loaded with the mouse),
  `deck` is null and the start is the history `created_at`.
- `transitions.json`: one per track change on decks. `start` = the first time after the
  incoming track's `deckN.load` that the incoming deck's `fader` crosses 0.1 upward, or the crossfader moves more than 0.1 toward it, while the
  outgoing deck is audible (fader > 0.1). `swap` = the incoming deck's level passes the
  outgoing one, where a deck's level is its fader times its crossfader gain (linear: deck 1
  gain = 1 - x, deck 2 = x). `end` = the outgoing deck's level drops below 0.1. EQ moves on
  both decks inside the window are listed.
- `fx.json`: spans of `fx.beat.on` with the channel and level at that moment, and spans
  where `deckN.cfx` is away from centre (|v - 0.5| > 0.05).
- `chapters.txt`: YouTube chapters (`0:00 Title - Artist`, `1:00:16` past an hour), first at
  0:00 and then at each swap. Chapters under 10 s apart are merged into the earlier one. With
  fewer than 3 chapters (YouTube's minimum), the file is still written with a note on the first line.

Without `pyrekordbox` or database access, it still writes `transitions.json` and `fx.json`
from the controller events, with deck numbers instead of track names.

A `__main__` self-check (`--selftest`) builds a made-up log (two tracks, one transition, one
FX span) and asserts the outputs.

## Testing

1. `tests/controllers_test.cpp` (ctest): raw bytes in, expected `{ctl, v}` out, for buttons, a
   14-bit fader pair (MSB then LSB), jog, an unknown message and an unknown device.
2. `rekordbox_log.py --selftest`.
3. End to end: OBS record 2 min. Play deck 1, load and blend in deck 2 with EQ and one Beat
   FX, stop. Check that the `.jsonl` sits next to the video with the same basename, that
   events look right, and that the analysis finds both tracks and the transition.
4. Live history check, part of step 3: confirm Rekordbox has written the history rows by the
   time the analysis runs (it may only flush on quit; if so, the README says to run the
   analysis after quitting Rekordbox).

## Distribution

- MIT licence. README says it is not affiliated with AlphaTheta or Pioneer DJ, and that it
  only reads the user's own Rekordbox database.
- Releases: the template's GitHub Actions build a macOS `.pkg`. Without an Apple Developer ID
  it is unsigned, so the README gives the right-click > Open / `xattr -dr com.apple.quarantine`
  step. Signing and notarising come later.

## Out of scope (add when needed)

- Live "now playing" in the dock (would need SQLCipher in C++).
- The name of the effect Rekordbox selects. Controllers only send select presses, and
  Rekordbox's on-screen state is not readable.
- Named controls for controllers other than the DDJ-FLX4 (raw MIDI is still logged;
  contributions add tables).
- Windows (WinMM/WinRT MIDI instead of CoreMIDI). Wanted, since many Rekordbox DJs are on
  Windows; the plugin keeps CoreMIDI inside `midi.cpp` so a Windows port only replaces that file.
