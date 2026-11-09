// Build and run (from the repo root):
//   clang -c -O1 -w -DSQLITE_HAS_CODEC -DSQLCIPHER_CRYPTO_CC -DSQLITE_TEMP_STORE=2 \
//     -DSQLITE_EXTRA_INIT=sqlcipher_extra_init -DSQLITE_EXTRA_SHUTDOWN=sqlcipher_extra_shutdown \
//     deps/sqlcipher/sqlite3.c -o build/sqlcipher.o
//   clang++ -std=c++17 -DSQLITE_HAS_CODEC -Ideps/sqlcipher src/history.cpp src/session.cpp tests/history_test.cpp \
//     build/sqlcipher.o -framework Security -framework CoreFoundation -o build/history_test && build/history_test
#include "../src/history.h"

#include <sqlite3.h>

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <unistd.h>

static std::string slurp(const std::string &path)
{
	std::stringstream s;
	s << std::ifstream(path).rdbuf();
	return s.str();
}

// A tiny master.db encrypted like Rekordbox's, with only the columns the plugin reads.
static void make_db(const std::string &path)
{
	sqlite3 *db;
	assert(sqlite3_open(path.c_str(), &db) == SQLITE_OK);
	std::string key = rekordbox_key();
	sqlite3_key(db, key.data(), int(key.size()));
	const char *sql =
		"CREATE TABLE djmdContent (ID TEXT, Title TEXT, ArtistID TEXT, BPM INTEGER, KeyID TEXT, FileNameL TEXT);"
		"CREATE TABLE djmdArtist (ID TEXT, Name TEXT);"
		"CREATE TABLE djmdKey (ID TEXT, ScaleName TEXT);"
		"CREATE TABLE djmdSongHistory (ID TEXT, ContentID TEXT, created_at TEXT);"
		"INSERT INTO djmdArtist VALUES ('a1', 'KV5 Dubai');"
		"INSERT INTO djmdKey VALUES ('k1', '1A');"
		"INSERT INTO djmdContent VALUES ('c1', 'Bheegi \"Bheegi\"', 'a1', 12500, 'k1', 'Bheegi Bheegi.flac');"
		"INSERT INTO djmdContent VALUES ('c2', 'No Artist', NULL, 0, NULL, 'x.mp3');"
		"INSERT INTO djmdSongHistory VALUES ('h0', 'c1', '2026-11-05 16:20:00.000 +00:00');" // too early
		"INSERT INTO djmdSongHistory VALUES ('h1', 'c1', '2026-11-05 16:47:00.500 +00:00');" // before Record
		"INSERT INTO djmdSongHistory VALUES ('h2', 'c2', '2026-11-05 16:52:35.738 +00:00');";
	char *err = nullptr;
	assert(sqlite3_exec(db, sql, nullptr, nullptr, &err) == SQLITE_OK);
	sqlite3_close(db);
}

int main()
{
	// times
	int64_t start = utc_ms("2026-11-05 16:48:00.000 +00:00");
	assert(start == 1793897280000);
	assert(utc_text(start + 147) == "2026-11-05 16:48:00.147 +00:00");
	assert(utc_ms("2026-11-05 22:18:00.147 +05:30") == start + 147);
	assert(utc_ms("2026-11-05 16:48:00") == start);
	assert(utc_ms("nonsense") == -1);

	char dir[] = "/tmp/rbl-history-XXXXXX";
	assert(mkdtemp(dir));
	std::string lib = std::string(dir) + "/Library/Pioneer/rekordbox";
	assert(system(("mkdir -p '" + lib + "'").c_str()) == 0);
	make_db(lib + "/master.db");

	// read: 15 minutes before Record to the end, read-only
	std::vector<HistoryRow> rows;
	std::string error;
	assert(history_read(lib + "/master.db", start - 15 * 60000, start + 10 * 60000, rows, error));
	assert(rows.size() == 2);
	assert(rows[0].title == "Bheegi \"Bheegi\"" && rows[0].artist == "KV5 Dubai" && rows[0].bpm == 125 &&
	       rows[0].key == "1A" && rows[0].file == "Bheegi Bheegi.flac");
	assert(rows[1].artist.empty() && rows[1].bpm == 0);

	std::string json = tracks_json("2026-11-05T22:18:00.000+05:30", start, rows);
	assert(json ==
	       "{\"v\":1,\"session_wall\":\"2026-11-05T22:18:00.000+05:30\",\"tracks\":[\n"
	       "  {\"logged\":-59.500,\"title\":\"Bheegi \\\"Bheegi\\\"\",\"artist\":\"KV5 Dubai\",\"bpm\":125,"
	       "\"key\":\"1A\",\"file\":\"Bheegi Bheegi.flac\"},\n"
	       "  {\"logged\":275.738,\"title\":\"No Artist\",\"artist\":\"\",\"bpm\":null,\"key\":\"\",\"file\":\"x.mp3\"}\n"
	       "]}\n");
	assert(tracks_json("w", start, {}) == "{\"v\":1,\"session_wall\":\"w\",\"tracks\":[]}\n");

	// wrong file or missing library: an error, no crash
	rows.clear();
	assert(!history_read(std::string(dir) + "/none.db", 0, 1, rows, error) && !error.empty());

	// scheduled write: lands next to the log, and never overwrites a hand-fixed list
	setenv("HOME", dir, 1);
	std::string log = std::string(dir) + "/set.rekordbox.jsonl";
	tracks_schedule(log, "wall", start, start + 10 * 60000, 3600);
	tracks_flush(); // OBS closing: written now, not in an hour
	std::string out = std::string(dir) + "/set.tracks.json";
	assert(slurp(out).find("\"logged\":-59.500") != std::string::npos);
	assert(tracks_status() == "Track list: 2 tracks saved to set.tracks.json");
	std::ofstream(out) << "hand fixed";
	tracks_schedule(log, "wall", start, start + 10 * 60000, 0);
	tracks_flush();
	assert(slurp(out) == "hand fixed");
	assert(tracks_status() == "Track list: kept the existing set.tracks.json");

	std::puts("history ok");
}
