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
#include "history.h"
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
		dir = config_get_string(c, "AdvOut",
					type && strcmp(type, "FFmpeg") == 0 ? "FFFilePath" : "RecFilePath");
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

// The track list is written once Rekordbox has caught up (or now, if OBS is closing).
void save_tracks(const std::vector<ClosedSession> &closed)
{
	for (auto &c : closed)
		tracks_schedule(c.path, c.wall, c.start_ms, c.stop_ms);
}

void on_event(enum obs_frontend_event e, void *)
{
	switch (e) {
	case OBS_FRONTEND_EVENT_RECORDING_STARTED:
		start("record", record_log_path());
		break;
	case OBS_FRONTEND_EVENT_RECORDING_STOPPED:
		save_tracks(sessions_close("record", host_now()));
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
		save_tracks(sessions_close("stream", host_now()));
		break;
	case OBS_FRONTEND_EVENT_EXIT:
		save_tracks(sessions_close_all(host_now()));
		tracks_flush();
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
	save_tracks(sessions_close_all(host_now()));
	tracks_flush();
	obs_log(LOG_INFO, "plugin unloaded");
}
