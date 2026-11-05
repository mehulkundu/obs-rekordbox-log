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
