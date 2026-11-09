#pragma once

#include <cstdint>
#include <string>
#include <vector>

// The track list: Rekordbox's play history around a recording, saved next to the log as
// <name>.tracks.json so the set can be analysed on any computer.

struct HistoryRow {
	std::string created_at; // UTC, as Rekordbox stores it: 2026-11-05 16:48:00.147 +00:00
	std::string title, artist, key, file;
	double bpm = 0;
};

// Rows played between from_ms and to_ms (Unix ms). Opens master.db read-only.
bool history_read(const std::string &db_path, int64_t from_ms, int64_t to_ms, std::vector<HistoryRow> &rows,
		  std::string &error);
std::string rekordbox_key();
std::string utc_text(int64_t ms);
int64_t utc_ms(const std::string &text); // -1 if it can't parse
// {"v":1,"session_wall":...,"tracks":[{"logged":<s since start_ms>,"title":...}]}
std::string tracks_json(const std::string &session_wall, int64_t start_ms, const std::vector<HistoryRow> &rows);

// Rekordbox adds a track 60 s into playing it, so the list is written 70 s after Stop.
// Writes <log without .rekordbox.jsonl>.tracks.json; never overwrites one (it may have hand fixes).
void tracks_schedule(const std::string &log_path, const std::string &session_wall, int64_t start_ms, int64_t stop_ms,
		     int delay_s = 70);
void tracks_flush(); // writes every waiting list now and waits for them (OBS is closing)
std::string tracks_status();
