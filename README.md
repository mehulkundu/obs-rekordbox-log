# obs-rekordbox-log

An OBS Studio plugin that records what you do in Rekordbox while you record or stream a DJ set.

Press Record (or Go Live) in OBS and it starts a log next to your video: every fader, EQ,
crossfader, FX and play/cue move on your controller, timed to the millisecond from the
start of the recording. After the set, a small script joins that log with Rekordbox's play
history to give you:

- the tracklist with times
- every transition (when it started, when the new track took over, when the old one left)
- every effect and when it was on
- YouTube chapters

Hand the video and these files to your editor, your scripts or an AI to cut shorts, find
the drops and write chapters, without guessing them from the audio.

> **Status: in development.** The design is in
> [`docs/superpowers/specs/`](docs/superpowers/specs/2026-11-03-obs-rekordbox-log-design.md).
> Nothing to install yet.

## v1 supports

- macOS (Apple Silicon), OBS 33+, Rekordbox 6/7 in Performance mode
- Named controls for the Pioneer DJ **DDJ-FLX4**. Any other MIDI controller is logged as raw
  MIDI. Tables for more controllers, and a Windows port, are welcome as contributions.

## How it works

Rekordbox has no public API. The plugin listens to your controller's MIDI alongside
Rekordbox (Rekordbox isn't affected) and writes JSON Lines. The analysis script reads your
own Rekordbox database with [pyrekordbox](https://github.com/dylanljones/pyrekordbox) to
name the tracks.

## Not affiliated

Not affiliated with or endorsed by AlphaTheta, Pioneer DJ or OBS Project. Rekordbox is a
trademark of AlphaTheta Corporation. This tool only reads your own controller and your
own Rekordbox library.

## License

MIT
