# obs-rekordbox-log

An OBS Studio plugin that records what you do in Rekordbox while you record or stream a DJ set.

Press Record (or Go Live) in OBS and it starts a log next to your video: every fader, EQ,
crossfader, FX and play/cue move on your controller, timed to the millisecond from the
start of the recording. After the set, a small script joins that log with Rekordbox's play
history to give you:

- the tracklist with times (saved with the recording, so it works on any computer)
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
python3 -m pip install numpy pyrekordbox   # audio; pyrekordbox only for recordings without a track list
python3 analysis/rekordbox_log.py ~/Movies/"My Set.rekordbox.jsonl"
```

This writes a `My Set.analysis/` folder next to the log. **Give `edit.md` and the video to your
editor or AI.** It stays under about 300 lines for an hour-long set:

| Section of `edit.md` | What it's for |
|---|---|
| Now playing | Lower thirds: each track's on-air span and when to show its name |
| Transitions | Each one labelled (bass swap, drop swap, wordplay, filter out, ...) with the evidence |
| Edit cues | Drops to punch in on, tricks to show hands for, breakdowns for calm shots |
| Energy | Bass per minute, and thumbnail candidates |
| Checks | Silence, a deck stopped while audible, long idle stretches |
| Clips | Every clip for shorts, ranked, with a checkbox to tick (`- [ ] C07 ...`) |
| YouTube chapters | Ready to paste |

For the detail behind any line, print the moves in that stretch:

```bash
python3 analysis/rekordbox_log.py window ~/Movies/"My Set.rekordbox.jsonl" 14:00 14:40
```

The folder also has `clips.json` (every clip, for scripts), `moves.jsonl` (every gesture),
`tracklist.json`, `transitions.json`, `fx.json` and `chapters.txt`. All times are seconds into the
video, with paused time removed.

Track names come from your Rekordbox play history. About a minute after you press Stop, the plugin
saves the tracks you played to `My Set.tracks.json` next to the video (the Rekordbox Log dock
says when). Send the video, the log and that file, and anyone can run the analysis without your
Rekordbox. Only file names are saved, not your folders.

A track gets into the history once it has played for 60 seconds in a row (a pause restarts the
count). Shorter ones are named by deck ("Deck 2"); to name one, add a line with its start time to
the track list, like `{"start": "1:09", "title": "Addictive", "artist": "..."}`. A track you played
just before pressing Record is named from the history before the recording, and marked so you can
check it. For recordings made before this, the script reads Rekordbox itself (with pyrekordbox)
and writes the track list.
Drops come from the video's audio, so add Rekordbox's output to OBS: an Audio Output Capture for
Rekordbox, or your audio interface as an Audio Input Capture. Without audio, or without numpy and
ffmpeg, the sheet still has everything except drops and energy, and says why.

Check your setup: `python3 analysis/test_analysis.py`.

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

  `tests/history_test.cpp` checks reading Rekordbox's history (build commands at the top of the file).

  `tests/fake_flx4.cpp` pretends to be a DDJ-FLX4 and plays a short mix, so you can test the plugin
  in OBS without the hardware (build and run commands are at the top of the file).

## Rekordbox's library

Rekordbox 6 and 7 encrypt their library (`master.db`) with one key shared by every install. The
plugin carries that key (the same one [pyrekordbox](https://github.com/dylanljones/pyrekordbox)
uses) and opens the library read-only with a bundled [SQLCipher](https://github.com/sqlcipher/sqlcipher)
(BSD licence, `deps/sqlcipher`). It only reads the play history.

## Not affiliated

Not affiliated with or endorsed by AlphaTheta, Pioneer DJ or OBS Project. Rekordbox is a
trademark of AlphaTheta Corporation. This tool only reads your own controller and your
own Rekordbox library.

## License

GPL-2.0, like OBS Studio and the OBS plugin template this is built from. See `LICENSE`.
