# Log format (version 1)

Each recording or stream gets one `.rekordbox.jsonl` file: JSON Lines, one event per line,
written and flushed as it happens. For a recording, the file has the video's name, with
`.rekordbox.jsonl` in place of the video's extension. For a stream, it is
`<YYYY-MM-DD HH-MM-SS>-stream.rekordbox.jsonl` in the recording folder.

## Header (first line)

```json
{"type":"session","v":1,"output":"record","wall":"2026-11-03T21:00:01.123+05:30","offset_ms":0,"obs":"33.0.1","plugin":"0.1.0"}
```

| Field | Meaning |
|---|---|
| `v` | Format version. |
| `output` | `record` or `stream`. |
| `wall` | Local wall-clock time when the output started (ISO 8601, ms, UTC offset). |
| `offset_ms` | Added to every `t` to line up with the video. 0 by default. Set it by hand if a clap test shows a gap. Measured with a DDJ-FLX4, Rekordbox 7.2 and OBS 33: the log was never behind the video, and a deck's sound reached the mic 73 ms or more after its Cue press, most of that being Rekordbox's audio delay. 0 is fine for editing. |
| `obs`, `plugin` | Versions. |

## Events

Every other line has `t`: seconds since the output started. `t` keeps counting while a recording
is paused. Subtract the time between `pause` and `resume` to get the position in the video.

```json
{"t":15.002,"type":"ctl","src":"DDJ-FLX4","ctl":"deck1.play","v":1}
{"t":15.210,"type":"ctl","src":"DDJ-FLX4","ctl":"deck2.eq.low","v":0.42}
{"t":16.400,"type":"ctl","src":"DDJ-FLX4","ctl":"deck1.jog","v":-2}
{"t":301.500,"type":"midi","src":"DDJ-FLX4","raw":[144,126,127]}
{"t":302.000,"type":"midi","src":"Some Device","ump":[805306368,0]}
{"t":412.000,"type":"device","src":"DDJ-FLX4","state":"disconnected"}
{"t":900.000,"type":"pause"}
{"t":930.000,"type":"resume"}
{"t":3600.120,"type":"end"}
```

| `type` | Fields |
|---|---|
| `ctl` | A named control. `src` is the MIDI device. `v` is 0..1 for faders and knobs (14-bit), 1/0 for button press/release, and a signed step count for jogs and the browse knob. |
| `midi` | A message with no name. `raw` is a MIDI 1.0 message (status, data1, data2). `ump` is the 32-bit words of any other Universal MIDI Packet, such as SysEx. MIDI clock is not logged. |
| `device` | A MIDI device `connected` or `disconnected`. |
| `pause`, `resume` | Recording paused and resumed. |
| `end` | The output stopped. If it is missing, OBS quit or crashed, and the log runs up to its last line. |

Faders and knobs start unknown: MIDI only reports changes.

## Control names (DDJ-FLX4)

Other controllers should use the same names when a control means the same thing, so that tools
reading the log work unchanged.

- `deck1.` / `deck2.` followed by:
  - `play`, `cue`, `sync`, `sync.long`, `load`, `shift`, `headphone.cue`
  - `tempo`, `trim`, `fader`, `eq.hi`, `eq.mid`, `eq.low`, `cfx` (0..1, centre 0.5)
  - `jog`, `jog.side`, `jog.search` (steps), `jog.touch`
  - `loop.in`, `loop.out`, `reloop`, `loop.half`, `loop.double`
  - `pad.mode.{hotcue,padfx1,padfx2,beatjump,beatloop,sampler,keyboard}`
  - `pad.<mode>.<1-8>`, plus `.shift` when Shift is held (`deck1.pad.hotcue.3`, `deck2.pad.padfx1.6.shift`)
- `mixer.crossfader` (0 = deck 1 side), `mixer.headphone.mix`
- `fx.beat.on` (each press toggles), `fx.beat.select`, `fx.beat.prev`, `fx.beat.next`,
  `fx.beat.channel` (1 or 2), `fx.beat.level` (0..1)
- `browse` (steps), `browse.press`

## Track list (`<name>.tracks.json`)

About 70 s after Stop (Rekordbox adds a track to its history 60 s into playing it), the plugin
reads Rekordbox's play history, read-only, from 15 minutes before Record to 70 s after Stop, and
writes it next to the log. If OBS closes sooner, it writes right away. It never overwrites an
existing file, so hand fixes are kept. Only file names are saved, not folders.

```json
{"v":1,"session_wall":"2026-11-05T22:19:35.783+05:30","tracks":[
  {"logged":179.955,"title":"Bheegi Bheegi","artist":"KV5 Dubai","bpm":125,"key":"1A","file":"Bheegi Bheegi - KV5 Dubai.flac"},
  {"start":"1:09","title":"Addictive"}
]}
```

- `logged`: seconds from the start of the recording (wall clock) when Rekordbox logged the track.
  Negative for a track logged before Record.
- A hand fix has `start` instead: the video time (seconds or `m:ss`) the track starts. It names
  the track that starts nearest that time. Use it for tracks played under 60 s, which Rekordbox
  never logs.
