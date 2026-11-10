#include "history.h"

#include "rekordbox-key.h"
#include "session.h"

#include <sqlite3.h>

#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <mutex>
#include <sstream>
#include <thread>

namespace {

// LEFT JOIN: a play whose track has left the library (removed device, unresolved stream) is kept
// with no name, so its slot and time stay in the list to fill in by hand (rekordbox-connect v1.2.12).
const char *QUERY = "SELECT h.created_at, c.Title, a.Name, c.BPM, k.ScaleName, c.FileNameL "
		    "FROM djmdSongHistory h LEFT JOIN djmdContent c ON c.ID = h.ContentID "
		    "LEFT JOIN djmdArtist a ON a.ID = c.ArtistID LEFT JOIN djmdKey k ON k.ID = c.KeyID "
		    "WHERE h.created_at >= ?1 AND h.created_at <= ?2 ORDER BY h.created_at";

std::string text(sqlite3_stmt *st, int col)
{
	const unsigned char *s = sqlite3_column_text(st, col);
	return s ? reinterpret_cast<const char *>(s) : "";
}

std::mutex mu; // guards everything below
std::condition_variable wake;
bool write_now;
std::vector<std::thread> workers;
std::string status;

// Where Rekordbox keeps its library: options.json has ["db-path","/…/master.db"] (a library moved
// in Preferences lives elsewhere). Read the same way as pyrekordbox and rekordbox-connect.
std::string default_db()
{
	const char *h = getenv("HOME");
	std::string home = h ? h : "";
	std::stringstream ss;
	ss << std::ifstream(home + "/Library/Application Support/Pioneer/rekordboxAgent/storage/options.json").rdbuf();
	std::string s = ss.str(), path;
	size_t p = s.find("\"db-path\"");
	if (p != std::string::npos && (p = s.find('"', p + 9)) != std::string::npos)
		for (++p; p < s.size() && s[p] != '"'; ++p)
			path += s[p] == '\\' && p + 1 < s.size() ? s[++p] : s[p]; // \/ \\ \"
	return path.empty() ? home + "/Library/Pioneer/rekordbox/master.db" : path;
}

void set_status(const std::string &s)
{
	std::lock_guard<std::mutex> lock(mu);
	status = s;
}

std::string clock_text(int64_t ms)
{
	time_t s = time_t(ms / 1000);
	tm lt;
	localtime_r(&s, &lt);
	char buf[16];
	strftime(buf, sizeof buf, "%H:%M:%S", &lt);
	return buf;
}

} // namespace

std::string rekordbox_key()
{
	const char pad[] = "obs-rekordbox-log";
	std::string k;
	for (size_t i = 0; i < sizeof REKORDBOX_KEY; ++i)
		k += char(REKORDBOX_KEY[i] ^ pad[i % (sizeof pad - 1)]);
	return k;
}

std::string utc_text(int64_t ms)
{
	time_t s = time_t(ms / 1000);
	tm t;
	gmtime_r(&s, &t);
	char base[24], out[40];
	strftime(base, sizeof base, "%Y-%m-%d %H:%M:%S", &t);
	snprintf(out, sizeof out, "%s.%03d +00:00", base, int(ms % 1000));
	return out;
}

int64_t utc_ms(const std::string &s)
{
	tm t = {};
	int n = 0;
	if (sscanf(s.c_str(), "%4d-%2d-%2d %2d:%2d:%2d%n", &t.tm_year, &t.tm_mon, &t.tm_mday, &t.tm_hour, &t.tm_min,
		   &t.tm_sec, &n) != 6)
		return -1;
	t.tm_year -= 1900;
	t.tm_mon -= 1;
	int64_t ms = int64_t(timegm(&t)) * 1000;
	const char *p = s.c_str() + n;
	if (*p == '.') {
		int scale = 100;
		for (++p; *p >= '0' && *p <= '9'; ++p, scale /= 10)
			ms += (*p - '0') * scale;
	}
	while (*p == ' ')
		++p;
	int hh = 0, mm = 0;
	if ((*p == '+' || *p == '-') && sscanf(p + 1, "%2d:%2d", &hh, &mm) == 2)
		ms -= (*p == '+' ? 1 : -1) * int64_t(hh * 60 + mm) * 60000;
	return ms;
}

bool history_read(const std::string &db_path, int64_t from_ms, int64_t to_ms, std::vector<HistoryRow> &rows,
		  std::string &error)
{
	sqlite3 *db = nullptr;
	if (sqlite3_open_v2(db_path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
		error = "no Rekordbox library at " + db_path;
		sqlite3_close(db);
		return false;
	}
	std::string key = rekordbox_key();
	sqlite3_key(db, key.data(), int(key.size()));
	sqlite3_busy_timeout(db, 3000); // Rekordbox may be writing
	sqlite3_stmt *st = nullptr;
	if (sqlite3_prepare_v2(db, QUERY, -1, &st, nullptr) != SQLITE_OK) {
		error = std::string("can't read Rekordbox's history: ") + sqlite3_errmsg(db);
		sqlite3_close(db);
		return false;
	}
	std::string from = utc_text(from_ms), to = utc_text(to_ms);
	sqlite3_bind_text(st, 1, from.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(st, 2, to.c_str(), -1, SQLITE_TRANSIENT);
	int rc;
	while ((rc = sqlite3_step(st)) == SQLITE_ROW)
		rows.push_back({text(st, 0), text(st, 1), text(st, 2), text(st, 4), text(st, 5),
				sqlite3_column_int(st, 3) / 100.0});
	bool ok = rc == SQLITE_DONE;
	if (!ok)
		error = std::string("can't read Rekordbox's history: ") + sqlite3_errmsg(db);
	sqlite3_finalize(st);
	sqlite3_close(db);
	return ok;
}

std::string tracks_json(const std::string &session_wall, int64_t start_ms, const std::vector<HistoryRow> &rows)
{
	std::string out = "{\"v\":1,\"session_wall\":" + json_str(session_wall) + ",\"tracks\":[";
	for (size_t i = 0; i < rows.size(); ++i) {
		const HistoryRow &r = rows[i];
		char num[64];
		snprintf(num, sizeof num, "%.3f", (utc_ms(r.created_at) - start_ms) / 1000.0);
		out += std::string(i ? ",\n" : "\n") + "  {\"logged\":" + num + ",\"title\":" + json_str(r.title) +
		       ",\"artist\":" + json_str(r.artist);
		snprintf(num, sizeof num, "%g", r.bpm);
		out += std::string(",\"bpm\":") + (r.bpm > 0 ? num : "null") + ",\"key\":" + json_str(r.key) +
		       ",\"file\":" + json_str(r.file) + "}";
	}
	return out + (rows.empty() ? "]}\n" : "\n]}\n");
}

void tracks_schedule(const std::string &log_path, const std::string &session_wall, int64_t start_ms, int64_t stop_ms,
		     int delay_s)
{
	const std::string ext = ".rekordbox.jsonl";
	std::string out = log_path;
	if (out.size() >= ext.size() && out.compare(out.size() - ext.size(), ext.size(), ext) == 0)
		out.erase(out.size() - ext.size());
	out += ".tracks.json";
	std::string name = out.substr(out.find_last_of('/') + 1);

	std::lock_guard<std::mutex> lock(mu);
	status = "Track list: saving at " + clock_text(stop_ms + delay_s * 1000) +
		 " (Rekordbox adds a track after 60 s)";
	workers.emplace_back([=] {
		{
			std::unique_lock<std::mutex> wait(mu);
			wake.wait_for(wait, std::chrono::seconds(delay_s), [] { return write_now; });
		}
		std::vector<HistoryRow> rows;
		std::string error;
		// A track played just before Record was logged then: look 15 minutes back.
		if (!history_read(default_db(), start_ms - 15 * 60 * 1000, stop_ms + delay_s * 1000, rows, error)) {
			set_status("Track list: " + error);
			return;
		}
		FILE *f = fopen(out.c_str(), "wx");
		if (!f) {
			set_status("Track list: kept the existing " + name);
			return;
		}
		fputs(tracks_json(session_wall, start_ms, rows).c_str(), f);
		fclose(f);
		set_status("Track list: " + std::to_string(rows.size()) + " tracks saved to " + name);
	});
}

void tracks_flush()
{
	std::vector<std::thread> waiting;
	{
		std::lock_guard<std::mutex> lock(mu);
		write_now = true;
		waiting.swap(workers);
	}
	wake.notify_all();
	for (auto &t : waiting)
		t.join();
}

std::string tracks_status()
{
	std::lock_guard<std::mutex> lock(mu);
	return status;
}
