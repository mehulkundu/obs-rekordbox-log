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
	auto closed = sessions_close("record", t0);
	assert(closed.size() == 1 && closed[0].path == path);
	assert(closed[0].start_ms > 1700000000000 && closed[0].stop_ms >= closed[0].start_ms);
	assert(closed[0].wall.rfind("20", 0) == 0);
	assert(sessions_close("record", t0).empty());

	auto l = lines(path);
	assert(l.size() == 3);
	assert(l[0].rfind("{\"type\":\"session\",\"v\":1,\"output\":\"record\",\"wall\":\"20", 0) == 0);
	assert(l[0].find("\"offset_ms\":0,\"obs\":\"33.0.1\",\"plugin\":\"0.1.0\"}") != std::string::npos);
	assert(l[1] == "{\"t\":0.000,\"type\":\"ctl\",\"src\":\"DDJ \\\"FLX4\\\"\",\"ctl\":\"deck1.play\",\"v\":1}");
	assert(l[2] == "{\"t\":0.000,\"type\":\"end\"}");

	// a second session with the same name never overwrites the first
	assert(sessions_open("record", path, t0, "33.0.1", "0.1.0"));
	closed = sessions_close_all(t0);
	assert(closed.size() == 1 && closed[0].path == std::string(dir) + "/set-2.rekordbox.jsonl");
	assert(lines(path).size() == 3);
	assert(lines(std::string(dir) + "/set-2.rekordbox.jsonl").size() == 2);

	// an unwritable folder fails and reports why
	assert(!sessions_open("record", "/nonexistent/x.rekordbox.jsonl", t0, "", ""));
	assert(!sessions_status().error.empty());

	std::puts("session ok");
}
