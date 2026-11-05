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
			} else if (type !=
				   1) { // type 1 is clock and other system messages: skipped, it would flood the log
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
