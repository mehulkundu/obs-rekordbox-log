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

## Supports

- macOS (Apple Silicon and Intel), OBS 31+, Rekordbox 6/7 in Performance mode
- Named controls for the Pioneer DJ **DDJ-FLX4**. Any other MIDI controller is logged as raw
  MIDI. Tables for more controllers, and a Windows port, are welcome (see Contributing).

## Install

Build it (Xcode and CMake 3.28+ needed):

```bash
cmake --preset macos
cmake --build --preset macos
cp -R build_macos/RelWithDebInfo/obs-rekordbox-log.plugin ~/Library/Application\ Support/obs-studio/plugins/
```

The first `cmake --preset macos` downloads the OBS sources and dependencies (a few minutes).
Restart OBS afterwards.

If macOS blocks a downloaded build, clear the quarantine flag:

```bash
xattr -dr com.apple.quarantine ~/Library/Application\ Support/obs-studio/plugins/obs-rekordbox-log.plugin
```

## Use

1. Plug in your controller and open Rekordbox, then OBS.
2. Optional: Docks > **Rekordbox Log** shows the MIDI devices it sees, whether it is logging,
   and the event count.
3. Record or stream as usual. When you record, `My Set.mov` gets a `My Set.rekordbox.jsonl` next to it.
   When you stream, the log goes in your recording folder, named with the date.

The format is in [`docs/format.md`](docs/format.md).

## Analyse

```bash
pip install pyrekordbox
python3 analysis/rekordbox_log.py ~/Movies/"My Set.rekordbox.jsonl"
```

This writes a `My Set.analysis/` folder next to the log:

| File | What's in it |
|---|---|
| `tracklist.json` | Each track: title, artist, BPM, key, file, deck, when it was loaded and started |
| `transitions.json` | Each change of deck: `start` (new track audible), `swap` (new track as loud as the old), `end` (old track gone), and the EQ/trim/CFX moves in between |
| `fx.json` | Beat FX on/off spans with channel and level, and CFX filter spans with their peak |
| `chapters.txt` | YouTube chapters, ready to paste into the description |

All times are seconds into the video, with paused time removed. Track names come from your own
Rekordbox play history. Without `pyrekordbox`, the script still writes everything else and
names tracks by deck. If the tracklist comes out without names, quit Rekordbox and run it again.
Rekordbox may not have saved its history yet.

Check your setup: `python3 analysis/rekordbox_log.py --selftest`.

## Contributing

- **Another controller:** add a table to `src/controllers.cpp`, reusing the control names in
  `docs/format.md`, and add a case to `tests/controllers_test.cpp`. To find the numbers, record
  a few seconds in OBS while you touch each control: every unmapped control shows up in the log
  as a `"midi"` line.
- **Windows:** CoreMIDI is only used in `src/midi.cpp`. A Windows port replaces that one file.
- **Tests:**

  ```bash
  mkdir -p build
  clang++ -std=c++17 src/controllers.cpp tests/controllers_test.cpp -o build/controllers_test && build/controllers_test
  clang++ -std=c++17 src/session.cpp tests/session_test.cpp -o build/session_test && build/session_test
  ```

  `tests/fake_flx4.cpp` pretends to be a DDJ-FLX4 and plays a short mix, so you can test the plugin
  in OBS without the hardware (build and run commands are at the top of the file).

## Not affiliated

Not affiliated with or endorsed by AlphaTheta, Pioneer DJ or OBS Project. Rekordbox is a
trademark of AlphaTheta Corporation. This tool only reads your own controller and your
own Rekordbox library.

## License

GPL-2.0, like OBS Studio and the OBS plugin template this is built from. See `LICENSE`.
