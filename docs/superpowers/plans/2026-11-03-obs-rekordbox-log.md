# obs-rekordbox-log Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An OBS plugin that, while OBS records or streams, logs every DJ controller action (named controls for the Pioneer DJ DDJ-FLX4, raw MIDI for any other device) to a JSON Lines file timed from the recording's start, plus a Python script that turns the log and Rekordbox's play history into a tracklist, transitions, FX spans and YouTube chapters.

**Architecture:** The plugin (C++, built from `obsproject/obs-plugintemplate`) listens to OBS frontend events, opens one log file per running output, and receives MIDI from every source through CoreMIDI alongside Rekordbox. A pure mapper turns FLX4 MIDI into names like `deck1.fader`. The plugin only records raw facts. All analysis runs after the set in `analysis/rekordbox_log.py`, which reads Rekordbox's database with `pyrekordbox`.

**Tech Stack:** C++17, CMake 3.28+ with Xcode generator, OBS 31.1.1 SDK (runs on OBS 33), Qt 6, CoreMIDI (macOS 11+ UMP API), Python 3.10+, pyrekordbox.

**Spec:** `docs/superpowers/specs/2026-11-03-obs-rekordbox-log-design.md`. Read it first.

**Repo:** `~/Documents/GitHub/obs-rekordbox-log`, branch `feat/obs-rekordbox-log`. Public: github.com/mehulkundu/obs-rekordbox-log. Every commit message ends with:

```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

## File map

| File | Responsibility |
|---|---|
| `CMakeLists.txt`, `CMakePresets.json`, `buildspec.json`, `cmake/`, `.github/`, `build-aux/`, `data/`, `src/plugin-support.*` | From the template. Edited only where a task says. |
| `src/controllers.{h,cpp}` | MIDI 1.0 message to named control. FLX4 table. No OBS, no CoreMIDI. |
| `src/session.{h,cpp}` | Open log files, write header/events/end, thread-safe. No OBS. |
| `src/midi.{h,cpp}` | CoreMIDI client: connect every source, hot-plug, decode UMP, send events to sessions. No OBS. |
| `src/dock.{h,cpp}` | Read-only Qt status dock. |
| `src/plugin-main.cpp` | Module load/unload, OBS frontend events, log paths. |
| `tests/controllers_test.cpp`, `tests/session_test.cpp` | `assert` programs, built with `clang++`. |
| `analysis/rekordbox_log.py` | Log + Rekordbox history to tracklist/transitions/fx/chapters. Has `--selftest`. |
| `docs/format.md` | The log format, for other tools. |

Tests for the C++ parts that have no OBS dependency are built directly:

```bash
mkdir -p build && clang++ -std=c++17 -Wall -Wextra src/controllers.cpp tests/controllers_test.cpp -o build/controllers_test && build/controllers_test
```

---

## Chunk 1: Scaffold, controller mapper, log writer

### Task 1: Import the OBS plugin template and switch to GPL-2.0

**Files:**
- Create (from template): `CMakeLists.txt`, `CMakePresets.json`, `buildspec.json`, `cmake/**`, `.github/**`, `build-aux/**`, `data/**`, `src/plugin-support.c.in`, `src/plugin-support.h`, `.clang-format`, `.gersemirc`
- Replace: `LICENSE` (MIT to the template's GPL-2.0), `.gitignore`
- Rename: template `src/plugin-main.c` to `src/plugin-main.cpp`
- Modify: `README.md` (licence section)

- [ ] **Step 1: Copy the template in**

```bash
cd ~/Documents/GitHub/obs-rekordbox-log
git clone --depth 1 https://github.com/obsproject/obs-plugintemplate.git /tmp/obs-plugintemplate
rsync -a --exclude .git --exclude README.md --exclude .gitignore /tmp/obs-plugintemplate/ ./
mv src/plugin-main.c src/plugin-main.cpp
head -2 LICENSE
```
Expected: `GNU GENERAL PUBLIC LICENSE` / `Version 2, June 1991`.

- [ ] **Step 2: Replace `.gitignore`**

The template ignores everything except listed paths. Keep that, and add this repo's folders:

```gitignore
# Exclude everything
/*

# Except for default project files
!/.github
!/analysis
!/build-aux
!/cmake
!/data
!/docs
!/src
!/tests
!.clang-format
!.gersemirc
!.gitignore
!buildspec.json
!CMakeLists.txt
!CMakePresets.json
!LICENSE
!README.md

# Exclude lock files
*.lock.json

# Exclude macOS legacy resource forks
.DS_Store

# Exclude CMake build number cache
/cmake/.CMakeBuildNumber

# Python
__pycache__/
```

- [ ] **Step 3: Set the plugin's identity in `buildspec.json`**

Change only these fields (leave `dependencies` as is):

```json
    "platformConfig": {
        "macos": {
            "bundleId": "com.mehulkundu.obs-rekordbox-log"
        }
    },
    "name": "obs-rekordbox-log",
    "displayName": "Rekordbox Log",
    "version": "0.1.0",
    "author": "Mehul Kundu",
    "website": "https://github.com/mehulkundu/obs-rekordbox-log",
    "email": "mehulkundu@users.noreply.github.com"
```

- [ ] **Step 4: Turn on the frontend API and Qt**

In `CMakePresets.json`, in the `"template"` configure preset's `cacheVariables`, set:

```json
        "ENABLE_FRONTEND_API": true,
        "ENABLE_QT": true
```

In `CMakeLists.txt`, change the sources line to:

```cmake
target_sources(${CMAKE_PROJECT_NAME} PRIVATE src/plugin-main.cpp)
```

- [ ] **Step 4b: Build only macOS in CI**

v1 is macOS-only (CoreMIDI), so the template's Linux and Windows CI jobs would fail. In `.github/workflows/build-project.yaml`, delete the whole `ubuntu-build:` and `windows-build:` jobs. Nothing else references them, and `push.yaml` copes with the missing platforms.

- [ ] **Step 5: Configure and build**

```bash
cmake --preset macos
```
The first run downloads OBS 31.1.1 sources, obs-deps and Qt 6 into `.deps/` (several minutes). Expected last lines: `-- Generating done` and `-- Build files have been written to: .../build_macos`.

```bash
cmake --build --preset macos
```
Expected: `** BUILD SUCCEEDED **` and `build_macos/RelWithDebInfo/obs-rekordbox-log.plugin` exists.

- [ ] **Step 6: Install and check OBS loads it**

Quit OBS, then:

```bash
rm -rf ~/Library/Application\ Support/obs-studio/plugins/obs-rekordbox-log.plugin
cp -R build_macos/RelWithDebInfo/obs-rekordbox-log.plugin ~/Library/Application\ Support/obs-studio/plugins/
open -a OBS
```
Wait for OBS to open, quit it, then:

```bash
grep obs-rekordbox-log "$(ls -t ~/Library/Application\ Support/obs-studio/logs/*.txt | head -1)"
```
Expected: a line with `[obs-rekordbox-log] plugin loaded successfully (version 0.1.0)`.

- [ ] **Step 7: Licence section in `README.md`**

Replace the `## License` section with:

```markdown
## License

GPL-2.0, like OBS Studio and the OBS plugin template this is built from. See `LICENSE`.
```

- [ ] **Step 8: Commit**

```bash
git add -A
git status --short
git commit -q -m "Import the OBS plugin template, switch to GPL-2.0

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
`git status` must not list `build_macos/` or `.deps/` (the `.gitignore` excludes them).

---

### Task 2: Controller mapper (DDJ-FLX4)

The FLX4's MIDI numbers come from Pioneer DJ's "DDJ-FLX4 MIDI Message List" (cross-checked against Mixxx's FLX4 mapping). In short:
- Deck buttons: note on, status `0x90` (deck 1) / `0x91` (deck 2). Velocity `0x7F` = press, `0x00` = release.
- Deck knobs and faders: CC on `0xB0`/`0xB1`, 14-bit: MSB on CC n, LSB on CC n+0x20. Tempo 0x00, trim 0x04, EQ hi 0x07, mid 0x0B, low 0x0F, channel fader 0x13.
- Jogs: relative CC, 64 = still. 0x21 side, 0x22/0x23 platter, 0x29 platter + shift.
- Mixer, status `0xB6`, 14-bit: headphone mix 0x0C, CFX deck 1 0x17, CFX deck 2 0x18, crossfader 0x1F. Browse 0x40 (relative).
- Beat FX: notes on `0x94`: on/off 0x47, select 0x63, prev 0x4A, next 0x4B, channel 1 0x10; `0x95` 0x11 channel 2, 0x47 on/off. Level: CC `0xB4` 0x02 (14-bit).
- Load: `0x96` note 0x46 (deck 1), 0x47 (deck 2). Browse press 0x41.
- Pads: `0x97` deck 1, `0x98` deck 1 + shift, `0x99` deck 2, `0x9A` deck 2 + shift. Note = mode base + pad index 0..7. Bases: 0x00 hot cue, 0x10 pad FX 1, 0x20 beat jump, 0x30 sampler, 0x40 keyboard, 0x50 pad FX 2, 0x60 beat loop, 0x70 key shift.

Anything else stays unknown and is logged raw, so a wrong or missing entry loses nothing.

**Files:**
- Create: `src/controllers.h`, `src/controllers.cpp`
- Test: `tests/controllers_test.cpp`

- [ ] **Step 1: Write the header**

`src/controllers.h`:

```cpp
#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <tuple>

// What one MIDI message means. unknown: log it raw. consumed: first half of a 14-bit pair, log nothing yet.
enum class Kind { unknown, named, consumed };

struct Ctl {
	Kind kind = Kind::unknown;
	std::string name;
	double v = 0;
};

// Turns MIDI 1.0 channel-voice messages from known controllers into named controls.
// Stateful: holds the MSB of each 14-bit control until its LSB arrives.
class Mapper {
public:
	Ctl map(const std::string &src, uint8_t status, uint8_t d1, uint8_t d2);
	static bool knows(const std::string &src);

private:
	std::map<std::tuple<std::string, uint8_t, uint8_t>, uint8_t> msb_;
};
```

- [ ] **Step 2: Write the failing test**

`tests/controllers_test.cpp`:

```cpp
#include "../src/controllers.h"

#include <cassert>
#include <cmath>
#include <cstdio>

int main()
{
	Mapper m;
	const std::string flx = "DDJ-FLX4";

	Ctl c = m.map(flx, 0x90, 0x0B, 0x7F);
	assert(c.kind == Kind::named && c.name == "deck1.play" && c.v == 1);
	c = m.map(flx, 0x91, 0x0B, 0x00);
	assert(c.name == "deck2.play" && c.v == 0);
	c = m.map(flx, 0x81, 0x0B, 0x40); // note off counts as release
	assert(c.name == "deck2.play" && c.v == 0);

	// 14-bit: the MSB is held, the LSB emits
	c = m.map(flx, 0xB1, 0x13, 0x7F);
	assert(c.kind == Kind::consumed);
	c = m.map(flx, 0xB1, 0x33, 0x7F);
	assert(c.name == "deck2.fader" && c.v == 1);
	m.map(flx, 0xB6, 0x1F, 0x40);
	c = m.map(flx, 0xB6, 0x3F, 0x00);
	assert(c.name == "mixer.crossfader" && std::fabs(c.v - 8192 / 16383.0) < 1e-9);
	m.map(flx, 0xB6, 0x17, 0x00);
	c = m.map(flx, 0xB6, 0x37, 0x00);
	assert(c.name == "deck1.cfx" && c.v == 0);
	m.map(flx, 0xB4, 0x02, 0x7F);
	c = m.map(flx, 0xB4, 0x22, 0x7F);
	assert(c.name == "fx.beat.level" && c.v == 1);

	c = m.map(flx, 0xB0, 0x22, 0x3E); // jog back 2
	assert(c.name == "deck1.jog" && c.v == -2);
	c = m.map(flx, 0x97, 0x02, 0x7F);
	assert(c.name == "deck1.pad.hotcue.3");
	c = m.map(flx, 0x9A, 0x15, 0x7F);
	assert(c.name == "deck2.pad.padfx1.6.shift");
	c = m.map(flx, 0x96, 0x47, 0x7F);
	assert(c.name == "deck2.load");
	c = m.map(flx, 0x94, 0x47, 0x7F);
	assert(c.name == "fx.beat.on");
	c = m.map(flx, 0x95, 0x11, 0x7F);
	assert(c.name == "fx.beat.channel" && c.v == 2);

	// LSB with no MSB yet, unknown message, unknown device: all raw
	assert(m.map(flx, 0xB0, 0x27, 0x10).kind == Kind::unknown);
	assert(m.map(flx, 0x90, 0x7E, 0x7F).kind == Kind::unknown);
	assert(m.map("Launchpad", 0x90, 0x0B, 0x7F).kind == Kind::unknown);

	std::puts("controllers ok");
}
```

- [ ] **Step 3: Run it to check it fails**

```bash
mkdir -p build && clang++ -std=c++17 -Wall -Wextra src/controllers.cpp tests/controllers_test.cpp -o build/controllers_test && build/controllers_test
```
Expected: error `no such file or directory: 'src/controllers.cpp'`.

- [ ] **Step 4: Write the mapper**

`src/controllers.cpp`:

```cpp
#include "controllers.h"

// Pioneer DJ DDJ-FLX4, from Pioneer DJ's "DDJ-FLX4 MIDI Message List".
// Channel 0 = deck 1, 1 = deck 2, 4/5 = beat FX, 6 = mixer and browser, 7-10 = pads.
namespace flx4 {

const char *deck_note(uint8_t n)
{
	switch (n) {
	case 0x0B: return "play";
	case 0x0C: return "cue";
	case 0x10: return "loop.in";
	case 0x11: return "loop.out";
	case 0x1B: return "pad.mode.hotcue";
	case 0x1E: return "pad.mode.padfx1";
	case 0x20: return "pad.mode.beatjump";
	case 0x22: return "pad.mode.sampler";
	case 0x36: return "jog.touch";
	case 0x3F: return "shift";
	case 0x4D: return "reloop";
	case 0x51: return "loop.half";
	case 0x53: return "loop.double";
	case 0x54: return "headphone.cue";
	case 0x58: return "sync";
	case 0x5C: return "sync.long";
	case 0x69: return "pad.mode.keyboard";
	case 0x6B: return "pad.mode.padfx2";
	case 0x6D: return "pad.mode.beatloop";
	}
	return nullptr;
}

// 14-bit: MSB on CC n, LSB on CC n + 0x20.
const char *deck_cc14(uint8_t n)
{
	switch (n) {
	case 0x00: return "tempo";
	case 0x04: return "trim";
	case 0x07: return "eq.hi";
	case 0x0B: return "eq.mid";
	case 0x0F: return "eq.low";
	case 0x13: return "fader";
	}
	return nullptr;
}

const char *mixer_cc14(uint8_t n)
{
	switch (n) {
	case 0x0C: return "mixer.headphone.mix";
	case 0x17: return "deck1.cfx";
	case 0x18: return "deck2.cfx";
	case 0x1F: return "mixer.crossfader";
	}
	return nullptr;
}

// Relative: 64 = no movement.
const char *deck_rel(uint8_t cc)
{
	switch (cc) {
	case 0x21: return "jog.side";
	case 0x22: return "jog"; // platter, vinyl mode on
	case 0x23: return "jog"; // platter, vinyl mode off
	case 0x29: return "jog.search";
	}
	return nullptr;
}

const char *pad_mode(uint8_t note)
{
	static const char *modes[] = {"hotcue", "padfx1", "beatjump", "sampler", "keyboard", "padfx2", "beatloop", "keyshift"};
	return modes[(note >> 4) & 7];
}

} // namespace flx4

bool Mapper::knows(const std::string &src)
{
	return src.find("DDJ-FLX4") != std::string::npos;
}

Ctl Mapper::map(const std::string &src, uint8_t status, uint8_t d1, uint8_t d2)
{
	Ctl out;
	if (!knows(src))
		return out;

	uint8_t type = status & 0xF0, ch = status & 0x0F;
	if (type == 0x80) { // note off = note on with velocity 0
		type = 0x90;
		d2 = 0;
	}
	auto named = [&](std::string name, double v) {
		out.kind = Kind::named;
		out.name = std::move(name);
		out.v = v;
		return out;
	};
	std::string deck = ch < 2 ? "deck" + std::to_string(ch + 1) + "." : "";

	if (type == 0x90) {
		double v = d2 ? 1 : 0;
		if (ch < 2)
			if (const char *n = flx4::deck_note(d1))
				return named(deck + n, v);
		if (ch >= 7 && ch <= 10 && (d1 & 0x0F) < 8) {
			std::string name = "deck" + std::to_string(ch < 9 ? 1 : 2) + ".pad." + flx4::pad_mode(d1) + "." +
					   std::to_string((d1 & 0x0F) + 1);
			if (ch == 8 || ch == 10)
				name += ".shift";
			return named(name, v);
		}
		if ((ch == 4 || ch == 5) && d1 == 0x47)
			return named("fx.beat.on", v);
		if (ch == 4 && d1 == 0x63)
			return named("fx.beat.select", v);
		if (ch == 4 && d1 == 0x4A)
			return named("fx.beat.prev", v);
		if (ch == 4 && d1 == 0x4B)
			return named("fx.beat.next", v);
		if (ch == 4 && d1 == 0x10 && d2)
			return named("fx.beat.channel", 1);
		if (ch == 5 && d1 == 0x11 && d2)
			return named("fx.beat.channel", 2);
		if (ch == 6 && d1 == 0x46)
			return named("deck1.load", v);
		if (ch == 6 && d1 == 0x47)
			return named("deck2.load", v);
		if (ch == 6 && d1 == 0x41)
			return named("browse.press", v);
		return out;
	}

	if (type == 0xB0) {
		uint8_t n = d1 & 0x1F;
		const char *cc14 = nullptr;
		if (d1 < 0x40) {
			if (ch < 2)
				cc14 = flx4::deck_cc14(n);
			else if (ch == 6)
				cc14 = flx4::mixer_cc14(n);
			else if (ch == 4 && n == 0x02)
				cc14 = "fx.beat.level";
		}
		if (cc14) {
			auto key = std::make_tuple(src, ch, n);
			if (d1 < 0x20) {
				msb_[key] = d2;
				out.kind = Kind::consumed;
				return out;
			}
			auto it = msb_.find(key);
			if (it == msb_.end())
				return out;
			return named(deck + cc14, ((it->second << 7) | d2) / 16383.0);
		}
		if (ch < 2)
			if (const char *r = flx4::deck_rel(d1))
				return named(deck + r, int(d2) - 64);
		if (ch == 6 && d1 == 0x40)
			return named("browse", int(d2) - 64);
	}
	return out;
}
```

Note: in the 14-bit branch `deck` is empty for channels 4 and 6, so mixer and FX names come out bare.

- [ ] **Step 5: Run the test to check it passes**

```bash
clang++ -std=c++17 -Wall -Wextra src/controllers.cpp tests/controllers_test.cpp -o build/controllers_test && build/controllers_test
```
Expected: `controllers ok`, no warnings.

- [ ] **Step 6: Commit**

```bash
git add src/controllers.h src/controllers.cpp tests/controllers_test.cpp
git commit -q -m "Add the DDJ-FLX4 controller mapper

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Session log writer

**Files:**
- Create: `src/session.h`, `src/session.cpp`
- Test: `tests/session_test.cpp`

- [ ] **Step 1: Write the header**

`src/session.h`:

```cpp
#pragma once

#include <cstdint>
#include <string>
#include <vector>

// Log files, one per running OBS output ("record", "stream"). Thread-safe: open and close
// come from the OBS UI thread, events from the CoreMIDI thread. Times are host ticks
// (mach_absolute_time / MIDITimeStamp).

// Writes the session header to a new file at `path`. Never overwrites: if the file exists it
// writes name-2.rekordbox.jsonl, name-3... Returns false and keeps the error if it can't write.
bool sessions_open(const std::string &output, const std::string &path, uint64_t start_host,
		   const std::string &obs_version, const std::string &plugin_version);
// Writes {"t":...,"type":"end"} and closes.
void sessions_close(const std::string &output, uint64_t host);
void sessions_close_all(uint64_t host);
// Appends {"t":<seconds since that session started>,<fields>} to every open session, or only to `output`.
void sessions_event(uint64_t host, const std::string &fields, const std::string &output = "");

struct SessionStatus {
	std::vector<std::string> outputs;
	uint64_t events = 0;
	std::string error;
};
SessionStatus sessions_status();

std::string json_str(const std::string &s);
uint64_t host_now();
```

- [ ] **Step 2: Write the failing test**

`tests/session_test.cpp`:

```cpp
#include "../src/session.h"

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <unistd.h>
#include <vector>

static std::vector<std::string> lines(const std::string &path)
{
	std::vector<std::string> out;
	std::ifstream f(path);
	for (std::string l; std::getline(f, l);)
		out.push_back(l);
	return out;
}

int main()
{
	char dir[] = "/tmp/rbl-test-XXXXXX";
	assert(mkdtemp(dir));
	std::string path = std::string(dir) + "/set.rekordbox.jsonl";
	uint64_t t0 = host_now();

	assert(sessions_open("record", path, t0, "33.0.1", "0.1.0"));
	sessions_event(t0, "\"type\":\"ctl\",\"src\":" + json_str("DDJ \"FLX4\"") + ",\"ctl\":\"deck1.play\",\"v\":1");
	sessions_event(t0, "\"type\":\"pause\"", "stream"); // another output: not written here
	assert(sessions_status().outputs == std::vector<std::string>{"record"});
	assert(sessions_status().events == 1);
	sessions_close("record", t0);

	auto l = lines(path);
	assert(l.size() == 3);
	assert(l[0].rfind("{\"type\":\"session\",\"v\":1,\"output\":\"record\",\"wall\":\"20", 0) == 0);
	assert(l[0].find("\"offset_ms\":0,\"obs\":\"33.0.1\",\"plugin\":\"0.1.0\"}") != std::string::npos);
	assert(l[1] == "{\"t\":0.000,\"type\":\"ctl\",\"src\":\"DDJ \\\"FLX4\\\"\",\"ctl\":\"deck1.play\",\"v\":1}");
	assert(l[2] == "{\"t\":0.000,\"type\":\"end\"}");

	// a second session with the same name never overwrites the first
	assert(sessions_open("record", path, t0, "33.0.1", "0.1.0"));
	sessions_close_all(t0);
	assert(lines(path).size() == 3);
	assert(lines(std::string(dir) + "/set-2.rekordbox.jsonl").size() == 2);

	// an unwritable folder fails and reports why
	assert(!sessions_open("record", "/nonexistent/x.rekordbox.jsonl", t0, "", ""));
	assert(!sessions_status().error.empty());

	std::puts("session ok");
}
```

- [ ] **Step 3: Run it to check it fails**

```bash
clang++ -std=c++17 -Wall -Wextra src/session.cpp tests/session_test.cpp -o build/session_test && build/session_test
```
Expected: error `no such file or directory: 'src/session.cpp'`.

- [ ] **Step 4: Write the session code**

`src/session.cpp`:

```cpp
#include "session.h"

#include <mach/mach_time.h>
#include <sys/time.h>

#include <cerrno>
#include <cstdio>
#include <ctime>
#include <map>
#include <mutex>

namespace {

struct Session {
	FILE *f;
	uint64_t start;
};

std::mutex mu; // guards everything below
std::map<std::string, Session> open_sessions;
uint64_t event_count;
std::string last_error;

double seconds(uint64_t from, uint64_t to)
{
	static const mach_timebase_info_data_t tb = [] {
		mach_timebase_info_data_t t;
		mach_timebase_info(&t);
		return t;
	}();
	double ticks = to >= from ? double(to - from) : -double(from - to);
	return ticks * tb.numer / tb.denom / 1e9;
}

// 2026-11-03T21:00:01.123+05:30
std::string wall_now()
{
	timeval tv;
	gettimeofday(&tv, nullptr);
	tm lt;
	localtime_r(&tv.tv_sec, &lt);
	char base[32], tz[8], out[48];
	strftime(base, sizeof base, "%Y-%m-%dT%H:%M:%S", &lt);
	strftime(tz, sizeof tz, "%z", &lt);
	snprintf(out, sizeof out, "%s.%03d%.3s:%s", base, int(tv.tv_usec / 1000), tz, tz + 3);
	return out;
}

// Never overwrite an earlier log: set.rekordbox.jsonl, then set-2.rekordbox.jsonl, ...
FILE *open_new(const std::string &path)
{
	const std::string ext = ".rekordbox.jsonl";
	FILE *f = fopen(path.c_str(), "wx");
	if (f || errno != EEXIST || path.size() < ext.size() || path.compare(path.size() - ext.size(), ext.size(), ext) != 0)
		return f;
	std::string stem = path.substr(0, path.size() - ext.size());
	for (int n = 2; !f && errno == EEXIST && n < 1000; ++n)
		f = fopen((stem + "-" + std::to_string(n) + ext).c_str(), "wx");
	return f;
}

void write_line(Session &s, uint64_t host, const std::string &fields)
{
	fprintf(s.f, "{\"t\":%.3f,%s}\n", seconds(s.start, host), fields.c_str());
	fflush(s.f); // a crash keeps everything up to here
}

void close_locked(std::map<std::string, Session>::iterator it, uint64_t host)
{
	write_line(it->second, host, "\"type\":\"end\"");
	fclose(it->second.f);
	open_sessions.erase(it);
}

} // namespace

std::string json_str(const std::string &s)
{
	std::string out = "\"";
	for (unsigned char c : s) {
		if (c == '"' || c == '\\') {
			out += '\\';
			out += char(c);
		} else if (c < 0x20) {
			char b[8];
			snprintf(b, sizeof b, "\\u%04x", c);
			out += b;
		} else {
			out += char(c);
		}
	}
	return out + "\"";
}

uint64_t host_now()
{
	return mach_absolute_time();
}

bool sessions_open(const std::string &output, const std::string &path, uint64_t start_host,
		   const std::string &obs_version, const std::string &plugin_version)
{
	std::lock_guard<std::mutex> lock(mu);
	if (auto it = open_sessions.find(output); it != open_sessions.end())
		close_locked(it, start_host);
	FILE *f = open_new(path);
	if (!f) {
		last_error = "can't write " + path;
		return false;
	}
	last_error.clear();
	fprintf(f, "{\"type\":\"session\",\"v\":1,\"output\":%s,\"wall\":\"%s\",\"offset_ms\":0,\"obs\":%s,\"plugin\":%s}\n",
		json_str(output).c_str(), wall_now().c_str(), json_str(obs_version).c_str(), json_str(plugin_version).c_str());
	fflush(f);
	open_sessions[output] = {f, start_host};
	return true;
}

void sessions_close(const std::string &output, uint64_t host)
{
	std::lock_guard<std::mutex> lock(mu);
	if (auto it = open_sessions.find(output); it != open_sessions.end())
		close_locked(it, host);
}

void sessions_close_all(uint64_t host)
{
	std::lock_guard<std::mutex> lock(mu);
	while (!open_sessions.empty())
		close_locked(open_sessions.begin(), host);
}

void sessions_event(uint64_t host, const std::string &fields, const std::string &output)
{
	std::lock_guard<std::mutex> lock(mu);
	for (auto &[name, s] : open_sessions)
		if (output.empty() || output == name) {
			write_line(s, host, fields);
			++event_count;
		}
}

SessionStatus sessions_status()
{
	std::lock_guard<std::mutex> lock(mu);
	SessionStatus s;
	for (auto &[name, _] : open_sessions)
		s.outputs.push_back(name);
	s.events = event_count;
	s.error = last_error;
	return s;
}
```

- [ ] **Step 5: Run the test to check it passes**

```bash
clang++ -std=c++17 -Wall -Wextra src/session.cpp tests/session_test.cpp -o build/session_test && build/session_test
```
Expected: `session ok`, no warnings.

- [ ] **Step 6: Commit**

```bash
git add src/session.h src/session.cpp tests/session_test.cpp
git commit -q -m "Add the session log writer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Chunk 2: MIDI input, OBS wiring, status dock

### Task 4: CoreMIDI input

No unit test: this is a thin layer over CoreMIDI, and it is checked live in Task 7. Keep all logic that can be tested in `controllers.cpp` and `session.cpp`.

**Files:**
- Create: `src/midi.h`, `src/midi.cpp`

- [ ] **Step 1: Write the header**

`src/midi.h`:

```cpp
#pragma once

#include <string>
#include <vector>

struct MidiDevice {
	std::string name;
	bool named; // true if controllers.cpp has a table for it
};

// Call on the main thread: CoreMIDI sends setup-change notifications to the creating thread's run loop.
// Returns 0 or the CoreMIDI error.
int midi_start();
void midi_stop();
std::vector<MidiDevice> midi_devices();
```

- [ ] **Step 2: Write the CoreMIDI client**

`src/midi.cpp`:

```cpp
#include "midi.h"

#include "controllers.h"
#include "session.h"

#include <CoreMIDI/CoreMIDI.h>

#include <map>
#include <memory>
#include <mutex>
#include <set>

namespace {

MIDIClientRef client;
MIDIPortRef port;
Mapper mapper; // used only on CoreMIDI's receive thread

// Each source's name lives here until midi_stop. Its address is the connection's refCon, so the
// receive thread never reads a container that the main thread is changing.
std::map<SInt32, std::unique_ptr<std::string>> names; // by kMIDIPropertyUniqueID
std::set<SInt32> connected;

std::mutex devices_mu;
std::vector<MidiDevice> present;

std::string endpoint_name(MIDIEndpointRef e)
{
	CFStringRef s = nullptr;
	if (MIDIObjectGetStringProperty(e, kMIDIPropertyDisplayName, &s) != noErr || !s)
		return "unknown";
	char buf[256] = "unknown";
	CFStringGetCString(s, buf, sizeof buf, kCFStringEncodingUTF8);
	CFRelease(s);
	return buf;
}

void device_event(const std::string &name, const char *state)
{
	sessions_event(host_now(), "\"type\":\"device\",\"src\":" + json_str(name) + ",\"state\":\"" + state + "\"");
}

// Connect sources we aren't connected to; log the ones that went away. Main thread only.
void scan()
{
	std::vector<MidiDevice> now;
	std::set<SInt32> seen;
	for (ItemCount i = 0, n = MIDIGetNumberOfSources(); i < n; ++i) {
		MIDIEndpointRef src = MIDIGetSource(i);
		SInt32 id = 0;
		MIDIObjectGetIntegerProperty(src, kMIDIPropertyUniqueID, &id);
		std::string name = endpoint_name(src);
		seen.insert(id);
		now.push_back({name, Mapper::knows(name)});
		if (connected.count(id))
			continue;
		auto &slot = names[id];
		if (!slot)
			slot = std::make_unique<std::string>(name);
		if (MIDIPortConnectSource(port, src, slot.get()) == noErr) {
			connected.insert(id);
			device_event(*slot, "connected");
		}
	}
	for (auto it = connected.begin(); it != connected.end();) {
		if (seen.count(*it)) {
			++it;
			continue;
		}
		device_event(*names[*it], "disconnected"); // CoreMIDI drops the connection itself
		it = connected.erase(it);
	}
	std::lock_guard<std::mutex> lock(devices_mu);
	present = std::move(now);
}

void on_message(const std::string &src, uint64_t host, uint8_t status, uint8_t d1, uint8_t d2)
{
	Ctl c = mapper.map(src, status, d1, d2);
	if (c.kind == Kind::consumed)
		return;
	std::string fields = "\"src\":" + json_str(src);
	if (c.kind == Kind::named) {
		char v[32];
		snprintf(v, sizeof v, "%.6g", c.v);
		sessions_event(host, "\"type\":\"ctl\"," + fields + ",\"ctl\":\"" + c.name + "\",\"v\":" + v);
	} else {
		sessions_event(host, "\"type\":\"midi\"," + fields + ",\"raw\":[" + std::to_string(status) + "," +
					     std::to_string(d1) + "," + std::to_string(d2) + "]");
	}
}

// Universal MIDI Packets: the message type (top 4 bits of the first word) gives its length in words.
void receive(const MIDIEventList *list, void *refcon)
{
	static const uint8_t words_for_type[16] = {1, 1, 1, 2, 2, 4, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4};
	const std::string &src = *static_cast<const std::string *>(refcon);
	const MIDIEventPacket *p = &list->packet[0];
	for (UInt32 i = 0; i < list->numPackets; ++i, p = MIDIEventPacketNext(p)) {
		uint64_t host = p->timeStamp ? p->timeStamp : host_now();
		for (UInt32 w = 0; w < p->wordCount;) {
			uint32_t word = p->words[w];
			uint8_t type = word >> 28;
			uint32_t size = words_for_type[type];
			if (type == 2) { // MIDI 1.0 channel voice
				on_message(src, host, (word >> 16) & 0xFF, (word >> 8) & 0x7F, word & 0x7F);
			} else if (type != 1) { // type 1 is clock and other system messages: skipped, it would flood the log
				std::string raw = "\"type\":\"midi\",\"src\":" + json_str(src) + ",\"ump\":[";
				for (uint32_t k = 0; k < size && w + k < p->wordCount; ++k)
					raw += (k ? "," : "") + std::to_string(p->words[w + k]);
				sessions_event(host, raw + "]");
			}
			w += size;
		}
	}
}

} // namespace

int midi_start()
{
	OSStatus err = MIDIClientCreateWithBlock(CFSTR("obs-rekordbox-log"), &client, ^(const MIDINotification *n) {
		if (n->messageID == kMIDIMsgSetupChanged)
			scan();
	});
	if (err)
		return err;
	err = MIDIInputPortCreateWithProtocol(client, CFSTR("in"), kMIDIProtocol_1_0, &port,
					      ^(const MIDIEventList *list, void *refcon) {
						      receive(list, refcon);
					      });
	if (err)
		return err;
	scan();
	return 0;
}

void midi_stop()
{
	if (port)
		MIDIPortDispose(port);
	if (client)
		MIDIClientDispose(client);
	port = 0;
	client = 0;
	connected.clear();
	names.clear(); // safe now: no more receive callbacks
}

std::vector<MidiDevice> midi_devices()
{
	std::lock_guard<std::mutex> lock(devices_mu);
	return present;
}
```

- [ ] **Step 3: Check it compiles on its own**

```bash
clang++ -std=c++17 -Wall -Wextra -fsyntax-only src/midi.cpp
```
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add src/midi.h src/midi.cpp
git commit -q -m "Add CoreMIDI input for every MIDI source

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Plugin entry point and OBS events

**Files:**
- Modify (replace): `src/plugin-main.cpp`
- Create: `src/dock.h` (one line, so this task compiles; the dock comes in Task 6)
- Modify: `CMakeLists.txt`

- [ ] **Step 1: Write `src/dock.h`**

```cpp
#pragma once

// Adds the read-only "Rekordbox Log" dock to OBS.
void dock_create();
```

- [ ] **Step 2: Replace `src/plugin-main.cpp`**

Keep the template's GPL header comment at the top, filled in:

```cpp
/*
obs-rekordbox-log
Copyright (C) 2026 Mehul Kundu

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program. If not, see <https://www.gnu.org/licenses/>
*/

#include <obs-frontend-api.h>
#include <obs-module.h>
#include <plugin-support.h>
#include <util/config-file.h>

#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>

#include "dock.h"
#include "midi.h"
#include "session.h"

OBS_DECLARE_MODULE()
OBS_MODULE_USE_DEFAULT_LOCALE(PLUGIN_NAME, "en-US")

namespace {

const char *EXT = ".rekordbox.jsonl";

std::string dated_name(const char *output)
{
	time_t now = time(nullptr);
	tm lt;
	localtime_r(&now, &lt);
	char buf[64];
	strftime(buf, sizeof buf, "%Y-%m-%d %H-%M-%S", &lt);
	return std::string(buf) + "-" + output + EXT;
}

// The folder this profile records into.
std::string recording_folder()
{
	config_t *c = obs_frontend_get_profile_config();
	const char *dir = nullptr;
	const char *mode = config_get_string(c, "Output", "Mode");
	if (mode && strcmp(mode, "Advanced") == 0) {
		const char *type = config_get_string(c, "AdvOut", "RecType");
		dir = config_get_string(c, "AdvOut", type && strcmp(type, "FFmpeg") == 0 ? "FFFilePath" : "RecFilePath");
	} else {
		dir = config_get_string(c, "SimpleOutput", "FilePath");
	}
	if (dir && *dir)
		return dir;
	const char *home = getenv("HOME");
	return std::string(home ? home : "/tmp") + "/Movies";
}

// OBS sets the recording path before the output starts, so at RECORDING_STARTED this is the new
// file. The extension is dropped because auto-remux may change it after stop.
std::string record_log_path()
{
	char *p = obs_frontend_get_last_recording();
	if (!p)
		return recording_folder() + "/" + dated_name("record");
	std::string s = p;
	bfree(p);
	size_t slash = s.find_last_of('/'), dot = s.find_last_of('.');
	if (dot != std::string::npos && (slash == std::string::npos || dot > slash))
		s.erase(dot);
	return s + EXT;
}

void start(const char *output, const std::string &path)
{
	if (sessions_open(output, path, host_now(), obs_get_version_string(), PLUGIN_VERSION))
		obs_log(LOG_INFO, "logging %s to %s", output, path.c_str());
	else
		obs_log(LOG_ERROR, "can't write %s", path.c_str());
}

void on_event(enum obs_frontend_event e, void *)
{
	switch (e) {
	case OBS_FRONTEND_EVENT_RECORDING_STARTED:
		start("record", record_log_path());
		break;
	case OBS_FRONTEND_EVENT_RECORDING_STOPPED:
		sessions_close("record", host_now());
		break;
	case OBS_FRONTEND_EVENT_RECORDING_PAUSED:
		sessions_event(host_now(), "\"type\":\"pause\"", "record");
		break;
	case OBS_FRONTEND_EVENT_RECORDING_UNPAUSED:
		sessions_event(host_now(), "\"type\":\"resume\"", "record");
		break;
	case OBS_FRONTEND_EVENT_STREAMING_STARTED:
		start("stream", recording_folder() + "/" + dated_name("stream"));
		break;
	case OBS_FRONTEND_EVENT_STREAMING_STOPPED:
		sessions_close("stream", host_now());
		break;
	case OBS_FRONTEND_EVENT_EXIT:
		sessions_close_all(host_now());
		break;
	default:
		break;
	}
}

} // namespace

bool obs_module_load(void)
{
	if (int err = midi_start())
		obs_log(LOG_ERROR, "CoreMIDI setup failed (%d), logging without MIDI", err);
	obs_frontend_add_event_callback(on_event, nullptr);
	dock_create();
	obs_log(LOG_INFO, "plugin loaded successfully (version %s)", PLUGIN_VERSION);
	return true;
}

void obs_module_unload(void)
{
	obs_frontend_remove_event_callback(on_event, nullptr);
	midi_stop(); // before closing sessions, so no MIDI callback writes to a closed file
	sessions_close_all(host_now());
	obs_log(LOG_INFO, "plugin unloaded");
}
```

- [ ] **Step 3: Add the sources and CoreMIDI to `CMakeLists.txt`**

Replace the `target_sources` line with:

```cmake
target_sources(
  ${CMAKE_PROJECT_NAME}
  PRIVATE src/plugin-main.cpp src/controllers.cpp src/session.cpp src/midi.cpp src/dock.cpp
)
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE "-framework CoreMIDI" "-framework CoreFoundation")
```

`src/dock.cpp` comes in Task 6. Commit this task together with Task 6, after the build passes.

---

### Task 6: Status dock

**Files:**
- Create: `src/dock.cpp`

- [ ] **Step 1: Write the dock**

`src/dock.cpp`:

```cpp
#include "dock.h"

#include "midi.h"
#include "session.h"

#include <obs-frontend-api.h>

#include <QLabel>
#include <QString>
#include <QTimer>
#include <QVBoxLayout>
#include <QWidget>

namespace {

QString status_text()
{
	QString t;
	auto devices = midi_devices();
	t += devices.empty() ? "No MIDI devices\n" : "MIDI devices:\n";
	for (auto &d : devices)
		t += QString("  %1%2\n").arg(QString::fromStdString(d.name), d.named ? "" : " (raw MIDI)");
	SessionStatus s = sessions_status();
	t += "\n";
	if (s.outputs.empty())
		t += "Not logging. Starts with Record or Go Live.\n";
	for (auto &o : s.outputs)
		t += QString("Logging %1\n").arg(QString::fromStdString(o));
	t += QString("Events: %1\n").arg(qulonglong(s.events));
	if (!s.error.empty())
		t += QString("\nError: %1\n").arg(QString::fromStdString(s.error));
	return t;
}

} // namespace

void dock_create()
{
	auto *w = new QWidget();
	auto *label = new QLabel(w);
	label->setTextFormat(Qt::PlainText);
	label->setWordWrap(true);
	label->setAlignment(Qt::AlignTop | Qt::AlignLeft);
	auto *layout = new QVBoxLayout(w);
	layout->addWidget(label);
	auto *timer = new QTimer(w);
	QObject::connect(timer, &QTimer::timeout, label, [label] { label->setText(status_text()); });
	timer->start(500);
	label->setText(status_text());
	obs_frontend_add_dock_by_id("rekordbox-log", "Rekordbox Log", w);
}
```

- [ ] **Step 2: Build**

```bash
cmake --build --preset macos
```
Expected: `** BUILD SUCCEEDED **`. If CMake complains about the sources list, re-run `cmake --preset macos` first.

- [ ] **Step 3: Format**

The template's CI checks formatting on every push.

CI uses clang-format 19 and the OBS build of gersemi; install the same ones:

```bash
brew install obsproject/tools/clang-format@19 obsproject/tools/gersemi
PATH="$(brew --prefix clang-format@19)/bin:$PATH" ./build-aux/run-clang-format src/*.cpp src/*.h tests/*.cpp
./build-aux/run-gersemi
```
Re-run both unit tests and the build. All pass.

- [ ] **Step 4: Commit Tasks 5 and 6**

```bash
git add src tests CMakeLists.txt
git commit -q -m "Wire the plugin to OBS: log per output, CoreMIDI, status dock

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Live check in OBS (no Rekordbox needed yet)

- [ ] **Step 1: Install** (as Task 1 Step 6: quit OBS, `rm -rf`, `cp -R`, open OBS).

- [ ] **Step 2: Dock.** In OBS, Docks menu > Rekordbox Log. Expected: the panel lists MIDI devices (plug in the FLX4: `DDJ-FLX4` appears without "(raw MIDI)" within a second) and says "Not logging".

- [ ] **Step 3: Record.** Press Start Recording. Move the deck 1 fader, press deck 1 Play, turn the crossfader, then unplug and replug the FLX4 USB. Pause and resume the recording once. Stop.

- [ ] **Step 4: Check the file.**

```bash
ls -t ~/Movies | head -3
```
Expected: the newest video and `<same name>.rekordbox.jsonl` next to it. (If your recordings go elsewhere, look there.)

```bash
f="$(ls -t ~/Movies/*.rekordbox.jsonl | head -1)"; head -3 "$f"; grep -c '"ctl"' "$f"; grep -E 'device|pause|resume|"end"' "$f"; grep '"midi"' "$f" | head
```
Expected: a session header, `deck1.fader`, `deck1.play`, `mixer.crossfader` lines with `t` rising from about 0, `disconnected` then `connected`, `pause`, `resume`, and an `end` line. Any `"midi"` lines are FLX4 controls missing from the table: note them and add them to `controllers.cpp` (with a test case) before moving on.

- [ ] **Step 5: Stream** (optional, needs a stream target). Start/stop streaming and check that `<date>-stream.rekordbox.jsonl` appears in the recording folder.

---

## Chunk 3: Analysis, docs, end-to-end

### Task 8: Analysis script

**Files:**
- Create: `analysis/rekordbox_log.py`

- [ ] **Step 1: Write the self-test first**

Create `analysis/rekordbox_log.py` with only the test and a stub, so it fails:

```python
#!/usr/bin/env python3
"""Turn an obs-rekordbox-log .jsonl into a tracklist, transitions, FX spans and YouTube chapters.

    python3 rekordbox_log.py SET.rekordbox.jsonl [--out DIR]
    python3 rekordbox_log.py --selftest

Track names come from Rekordbox's play history through pyrekordbox (pip install pyrekordbox).
Without it, everything else still works and tracks are named by deck.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


def analyse(header, events, history):
    raise NotImplementedError


def selftest():
    header = {'type': 'session', 'v': 1, 'wall': '2026-11-03T21:00:00.000+05:30', 'offset_ms': 0}

    def c(t, name, v):
        return {'t': t, 'type': 'ctl', 'src': 'DDJ-FLX4', 'ctl': name, 'v': v}

    events = [
        c(1, 'deck1.load', 1), c(2, 'deck1.play', 1),
        c(28, 'fx.beat.channel', 1), c(29, 'fx.beat.level', 0.7),
        c(30, 'fx.beat.on', 1), c(40, 'fx.beat.on', 1),
        c(60, 'deck2.load', 1), c(65, 'deck2.fader', 0.0), c(70, 'deck2.play', 1),
        c(72, 'deck2.fader', 0.5), c(76, 'deck2.eq.low', 0.2),
        c(80, 'deck2.fader', 1.0), c(85, 'deck1.fader', 0.6), c(90, 'deck1.fader', 0.05),
        {'t': 100, 'type': 'pause'}, {'t': 110, 'type': 'resume'},
        c(120, 'deck1.eq.low', 0.5), {'t': 130, 'type': 'end'},
    ]
    history = [
        {'title': 'One', 'artist': 'A', 'bpm': 122.0, 'key': '8A', 'path': '/1', 't': 20},
        {'title': 'Two', 'artist': 'B', 'bpm': 123.0, 'key': '9A', 'path': '/2', 't': 75},
    ]

    vt = video_clock(header, events)
    assert vt(50) == 50 and vt(120) == 110, 'paused time is removed'

    r = analyse(header, events, history)
    assert [t['title'] for t in r['tracklist']] == ['One', 'Two'], r['tracklist']
    assert r['tracklist'][1]['deck'] == 2 and r['tracklist'][1]['start'] == 70
    (tr,) = r['transitions']
    assert (tr['start'], tr['swap'], tr['end']) == (72, 80, 90), tr
    assert tr['moves'] == [{'t': 76, 'ctl': 'deck2.eq.low', 'v': 0.2}], tr['moves']
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
    print('selftest ok')


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        selftest()
```

- [ ] **Step 2: Run it to check it fails**

```bash
python3 analysis/rekordbox_log.py --selftest
```
Expected: `NameError: name 'video_clock' is not defined`.

- [ ] **Step 3: Write the analysis**

Replace the `analyse` stub with the following, and replace the `__main__` block at the end with the one shown at the bottom:

```python
AUDIBLE = 0.1


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
    """Rekordbox history rows played during the session, with t in log seconds."""
    try:
        from pyrekordbox import MasterDatabase
    except ImportError:
        print('pyrekordbox not installed: tracks are named by deck', file=sys.stderr)
        return []
    # Rekordbox stores created_at as naive local time
    start = datetime.fromisoformat(header['wall']).astimezone().replace(tzinfo=None)
    end = start + timedelta(seconds=end_t)
    try:
        rows = [s for s in MasterDatabase().get_history_songs().all() if start <= s.created_at <= end]
    except Exception as err:  # database locked, key missing, schema changed
        print(f'cannot read Rekordbox history ({err}): tracks are named by deck', file=sys.stderr)
        return []
    out = []
    for s in sorted(rows, key=lambda s: s.created_at):
        c = s.Content
        if c is None:
            continue
        out.append({
            'title': c.Title, 'artist': c.ArtistName, 'bpm': c.BPM / 100 if c.BPM else None,
            'key': c.KeyName, 'path': c.FolderPath, 't': (s.created_at - start).total_seconds(),
        })
    return out


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
    tracks = []
    for e in ctls:
        for d in (1, 2):
            if e['ctl'] == f'deck{d}.load' and e['v'] == 1:
                tracks.append({'deck': d, 'load': e['t'], 'start': None})
    for tr in tracks:
        d = tr['deck']
        until = min([x['load'] for x in tracks if x['deck'] == d and x['load'] > tr['load']], default=end_t)
        tr['start'] = next((e['t'] for e in ctls
                            if e['ctl'] == f'deck{d}.play' and e['v'] == 1 and tr['load'] < e['t'] < until), None)
    tracks = [tr for tr in tracks if tr['start'] is not None]

    used = set()
    for h in history:
        names = {k: h[k] for k in ('title', 'artist', 'bpm', 'key', 'path')}
        free = [i for i, tr in enumerate(tracks) if i not in used and tr['load'] is not None and tr['load'] <= h['t']]
        if free:
            i = max(free, key=lambda i: tracks[i]['load'])
            used.add(i)
            tracks[i].update(names)
        else:  # loaded with the mouse: no load press to pair with
            tracks.append({'deck': None, 'load': None, 'start': h['t'], **names})
    if history:  # played but never reached the history: previewed in headphones only
        tracks = [tr for tr in tracks if 'title' in tr]
    return sorted(tracks, key=lambda tr: tr['start'])


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
        for e in ctls:  # replay from the top so every control has its latest value
            m.apply(e)
            if e['t'] < b['load']:
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
        knobs = ('eq.hi', 'eq.mid', 'eq.low', 'cfx', 'trim')
        stop = end if end is not None else swap
        moves = [{'t': e['t'], 'ctl': e['ctl'], 'v': e['v']} for e in ctls
                 if start is not None and stop is not None and start <= e['t'] <= stop
                 and any(e['ctl'] == f'deck{d}.{k}' for d in (A, B) for k in knobs)]
        out.append({'into': i + 1, 'from': label(a), 'to': label(b), 'from_deck': A, 'to_deck': B,
                    'start': start, 'swap': swap, 'end': end, 'moves': moves})
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


def analyse(header, events, history):
    """history: [{'title', 'artist', 'bpm', 'key', 'path', 't'}] with t in log seconds."""
    vt = video_clock(header, events)
    ctls = [e for e in events if e['type'] == 'ctl']
    end_t = events[-1]['t'] if events else 0

    tracks = find_tracks(ctls, history, end_t)
    transitions = find_transitions(tracks, ctls)
    fx = find_fx(ctls, end_t)

    # Everything below is in video time.
    for tr in tracks:
        tr['load'], tr['start'] = vt(tr['load']), vt(tr['start'])
    for t in transitions:
        t['start'], t['swap'], t['end'] = vt(t['start']), vt(t['swap']), vt(t['end'])
        for mv in t['moves']:
            mv['t'] = vt(mv['t'])
    for s in fx:
        s['start'], s['end'] = vt(s['start']), vt(s['end'])
    tracklist = [{'n': i + 1, **tr} for i, tr in enumerate(tracks)]
    return {'tracklist': tracklist, 'transitions': transitions, 'fx': fx, 'chapters': chapters(tracks, transitions)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('log', type=Path)
    ap.add_argument('--out', type=Path, help='output folder (default: next to the log, <name>.analysis)')
    args = ap.parse_args()

    header, events = load(args.log)
    end_t = events[-1]['t'] if events else 0
    result = analyse(header, events, read_history(header, end_t))

    out = args.out or args.log.with_name(args.log.name.removesuffix('.rekordbox.jsonl') + '.analysis')
    out.mkdir(parents=True, exist_ok=True)
    for name in ('tracklist', 'transitions', 'fx'):
        (out / f'{name}.json').write_text(json.dumps(result[name], indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (out / 'chapters.txt').write_text(result['chapters'], encoding='utf-8')
    print(f"{len(result['tracklist'])} tracks, {len(result['transitions'])} transitions, "
          f"{len(result['fx'])} FX spans -> {out}")
```

The end of the file becomes:

```python
if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        selftest()
    else:
        main()
```

- [ ] **Step 4: Run the self-test to check it passes**

```bash
python3 analysis/rekordbox_log.py --selftest
```
Expected: `selftest ok`.

- [ ] **Step 5: Run it on the Task 7 log** (no Rekordbox tracks in it, so expect 0-1 tracks and no errors):

```bash
python3 analysis/rekordbox_log.py "$(ls -t ~/Movies/*.rekordbox.jsonl | head -1)"
```
Expected: a `N tracks, N transitions, N FX spans -> ....analysis` line, and the folder holds `tracklist.json`, `transitions.json`, `fx.json`, `chapters.txt`.

- [ ] **Step 6: Commit**

```bash
git add analysis/rekordbox_log.py
git commit -q -m "Add the analysis script: tracklist, transitions, FX spans, chapters

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Docs

**Files:**
- Create: `docs/format.md`
- Modify: `README.md`

- [ ] **Step 1: Write `docs/format.md`**

Document, with one example per line type: the header (`type: session`, `v`, `output`, `wall`, `offset_ms`, `obs`, `plugin`); `t` (seconds since the output started, wall-clock, pauses included); `ctl` (`src`, `ctl`, `v`: 0..1 for faders and knobs, 1/0 for buttons, signed delta for jogs and browse); `midi` with `raw` (status, data1, data2) or `ump` (32-bit words); `device` (`connected`/`disconnected`); `pause`/`resume`; `end` (missing if OBS crashed). List the FLX4 control names from Task 2. Say that other controllers should reuse those names when the control means the same thing.

- [ ] **Step 2: Update `README.md`**

Replace the status note with Install (download the `.pkg` from Releases, or build: the Task 1 commands; unsigned build: right-click > Open, or `xattr -dr com.apple.quarantine ~/Library/Application\ Support/obs-studio/plugins/obs-rekordbox-log.plugin`), Use (open Docks > Rekordbox Log, record as usual, the `.rekordbox.jsonl` lands next to the video), Analyse (`pip install pyrekordbox`, `python3 analysis/rekordbox_log.py <log>`, what each output file holds; quit Rekordbox first if the tracklist comes out empty), and Contributing (add a controller table in `src/controllers.cpp` plus a test; the Windows port replaces `src/midi.cpp`).

- [ ] **Step 3: Commit**

```bash
git add docs/format.md README.md
git commit -q -m "Document the log format, install and analysis

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: End-to-end test with Rekordbox and the FLX4

Needs the human DJ at the controller. Agentic workers: stop here and hand this checklist to the user.

- [ ] **Step 1:** Install the latest build (Task 1 Step 6). Open Rekordbox in Performance mode with the FLX4, then OBS. Note the time on the Mac clock.
- [ ] **Step 2:** In OBS, Start Recording. Clap once on camera/mic next to the FLX4 while pressing deck 1 Play (an alignment mark).
- [ ] **Step 3:** Load track A to deck 1, play it 60 s. Load track B to deck 2 with its channel fader down, start it, bring it in over about 15 s with the low EQ cut, swap the lows, take deck 1 out. Turn Beat FX on for a few seconds, then off. Turn the deck 2 CFX knob away and back. Stop recording.
- [ ] **Step 4: Log name.** The `.rekordbox.jsonl` sits next to the video with the same base name.
- [ ] **Step 5: Alignment.** In the video, find the clap's frame time. In the log, find the first `deck1.play`. If they differ by more than about 40 ms, set `offset_ms` in the header to (video time - log time) × 1000 and note the value in the README as typical.
- [ ] **Step 6: History.** With Rekordbox still open, run `python3 analysis/rekordbox_log.py <log>`. If `tracklist.json` has no titles, quit Rekordbox and run it again. Record which case is true in the README (Analyse section).
- [ ] **Step 7: Time zone.** Check that track A's `start` in `tracklist.json` matches the video (within a second or two). If it is off by your UTC offset, Rekordbox stores UTC: in `read_history`, change `.astimezone().replace(tzinfo=None)` to `.astimezone(timezone.utc).replace(tzinfo=None)` (import `timezone`) and re-check.
- [ ] **Step 8: Transitions and FX.** `transitions.json` has one transition A to B whose `start`, `swap` and `end` match what you hear in the video, with low EQ moves listed. `fx.json` has the Beat FX span and the CFX span.
- [ ] **Step 9: Raw leftovers.** `grep '"midi"' <log>` lists FLX4 controls missing from the table. Add each to `src/controllers.cpp` with a test case.
- [ ] **Step 10: Commit** any fixes from Steps 5-9:

```bash
git add -A && git commit -q -m "Fixes from the end-to-end test

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Push and open a pull request

- [ ] **Step 1:** `git push`
- [ ] **Step 2:** Open the PR into `main`:

```bash
gh pr create --base main --head feat/obs-rekordbox-log --title "obs-rekordbox-log v0.1.0" --body "$(cat <<'EOF'
OBS plugin that logs DJ controller actions (named DDJ-FLX4 controls, raw MIDI for anything else) in sync with OBS recording or streaming, plus an analysis script for tracklist, transitions, FX spans and YouTube chapters.

- Spec: docs/superpowers/specs/2026-11-03-obs-rekordbox-log-design.md
- Format: docs/format.md
- Tested: unit tests, analysis self-test, end-to-end with Rekordbox 7 and a DDJ-FLX4

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
- [ ] **Step 3:** Check that the template's GitHub Actions (build and format) pass on the PR. Fix and push if not.
