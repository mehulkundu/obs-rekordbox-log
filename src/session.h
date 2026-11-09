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
struct ClosedSession {
	std::string path, wall;    // the file actually written, and the header's wall clock
	int64_t start_ms, stop_ms; // Unix ms
};
// Writes {"t":...,"type":"end"} and closes. Returns what was closed (nothing if it wasn't open).
std::vector<ClosedSession> sessions_close(const std::string &output, uint64_t host);
std::vector<ClosedSession> sessions_close_all(uint64_t host);
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
