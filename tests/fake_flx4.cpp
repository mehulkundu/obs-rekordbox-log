// Pretends to be a DDJ-FLX4: a virtual MIDI source that plays a short two-deck mix, so the
// plugin can be tested without the hardware. Start an OBS recording, then run:
//   clang++ -std=c++17 tests/fake_flx4.cpp -framework CoreMIDI -framework CoreFoundation -o build/fake_flx4 && build/fake_flx4

#include <CoreMIDI/CoreMIDI.h>
#include <unistd.h>

#include <cstdio>

static MIDIEndpointRef src;

static void send(uint8_t status, uint8_t d1, uint8_t d2)
{
	MIDIEventList list;
	MIDIEventPacket *p = MIDIEventListInit(&list, kMIDIProtocol_1_0);
	uint32_t word = (0x2u << 28) | (uint32_t(status) << 16) | (uint32_t(d1) << 8) | d2;
	MIDIEventListAdd(&list, sizeof list, p, 0, 1, &word);
	MIDIReceivedEventList(src, &list);
}

static void press(uint8_t status, uint8_t note)
{
	send(status, note, 0x7F);
	send(status, note, 0x00);
}

static void cc14(uint8_t status, uint8_t cc, double v)
{
	int x = int(v * 16383 + 0.5);
	send(status, cc, uint8_t(x >> 7));
	send(status, uint8_t(cc + 0x20), uint8_t(x & 0x7F));
}

static void wait(double s)
{
	usleep(useconds_t(s * 1e6));
}

int main()
{
	MIDIClientRef client;
	if (MIDIClientCreate(CFSTR("fake-flx4"), nullptr, nullptr, &client) ||
	    MIDISourceCreateWithProtocol(client, CFSTR("DDJ-FLX4 (fake)"), kMIDIProtocol_1_0, &src)) {
		std::fputs("can't create the virtual MIDI source\n", stderr);
		return 1;
	}
	wait(1); // let the plugin see the new device and connect

	press(0x96, 0x46); // load deck 1
	press(0x90, 0x0B); // play deck 1
	wait(1);
	press(0x94, 0x10);     // beat FX on channel 1
	cc14(0xB4, 0x02, 0.7); // FX level
	press(0x94, 0x47);     // FX on
	wait(1);
	press(0x94, 0x47); // FX off
	press(0x96, 0x47); // load deck 2
	cc14(0xB1, 0x13, 0.0);
	press(0x91, 0x0B); // play deck 2
	wait(0.5);
	cc14(0xB1, 0x13, 0.5); // bring deck 2 in
	cc14(0xB1, 0x0F, 0.2); // with the lows cut
	wait(0.5);
	cc14(0xB1, 0x13, 1.0);
	cc14(0xB1, 0x0F, 0.5); // swap the lows
	wait(0.5);
	cc14(0xB0, 0x13, 0.6);
	wait(0.5);
	cc14(0xB0, 0x13, 0.05); // deck 1 out
	cc14(0xB6, 0x1F, 0.25); // crossfader
	send(0xB0, 0x22, 0x3E); // jog back 2
	send(0x90, 0x7E, 0x7F); // not in the table: logged raw
	wait(0.5);

	MIDIEndpointDispose(src); // the plugin logs a disconnect
	wait(0.5);
	std::puts("fake FLX4 done");
	return 0;
}
