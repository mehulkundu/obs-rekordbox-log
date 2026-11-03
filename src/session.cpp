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
	if (f || errno != EEXIST || path.size() < ext.size() ||
	    path.compare(path.size() - ext.size(), ext.size(), ext) != 0)
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
	fprintf(f,
		"{\"type\":\"session\",\"v\":1,\"output\":%s,\"wall\":\"%s\",\"offset_ms\":0,\"obs\":%s,\"plugin\":%s}\n",
		json_str(output).c_str(), wall_now().c_str(), json_str(obs_version).c_str(),
		json_str(plugin_version).c_str());
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
