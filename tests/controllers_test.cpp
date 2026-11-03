#include "../src/controllers.h"

#include <cassert>
#include <cmath>
#include <cstdio>

int main()
{
	Mapper m;
	const std::string flx = "DDJ-FLX4";

	Ctl c = m.map(flx, 0x90, 0x0B, 0x7F);
	assert(c.kind == Kind::named && c.name == "deck1.play" && c.v == 1);
	c = m.map(flx, 0x91, 0x0B, 0x00);
	assert(c.name == "deck2.play" && c.v == 0);
	c = m.map(flx, 0x81, 0x0B, 0x40); // note off counts as release
	assert(c.name == "deck2.play" && c.v == 0);

	// 14-bit: the MSB is held, the LSB emits
	c = m.map(flx, 0xB1, 0x13, 0x7F);
	assert(c.kind == Kind::consumed);
	c = m.map(flx, 0xB1, 0x33, 0x7F);
	assert(c.name == "deck2.fader" && c.v == 1);
	m.map(flx, 0xB6, 0x1F, 0x40);
	c = m.map(flx, 0xB6, 0x3F, 0x00);
	assert(c.name == "mixer.crossfader" && std::fabs(c.v - 8192 / 16383.0) < 1e-9);
	m.map(flx, 0xB6, 0x17, 0x00);
	c = m.map(flx, 0xB6, 0x37, 0x00);
	assert(c.name == "deck1.cfx" && c.v == 0);
	m.map(flx, 0xB4, 0x02, 0x7F);
	c = m.map(flx, 0xB4, 0x22, 0x7F);
	assert(c.name == "fx.beat.level" && c.v == 1);
	assert(m.map(flx, 0xB5, 0x02, 0x7F).kind == Kind::consumed); // its channel 5 copy
	assert(m.map(flx, 0xB5, 0x22, 0x7F).kind == Kind::consumed);

	c = m.map(flx, 0xB0, 0x22, 0x3E); // jog back 2
	assert(c.name == "deck1.jog" && c.v == -2);
	c = m.map(flx, 0x97, 0x02, 0x7F);
	assert(c.name == "deck1.pad.hotcue.3");
	c = m.map(flx, 0x9A, 0x15, 0x7F);
	assert(c.name == "deck2.pad.padfx1.6.shift");
	c = m.map(flx, 0x96, 0x47, 0x7F);
	assert(c.name == "deck2.load");
	c = m.map(flx, 0x94, 0x47, 0x7F);
	assert(c.name == "fx.beat.on");
	c = m.map(flx, 0x95, 0x11, 0x7F);
	assert(c.name == "fx.beat.channel" && c.v == 2);
	assert(m.map(flx, 0x94, 0x10, 0x00).kind == Kind::consumed);

	// LSB with no MSB yet, unknown message, unknown device: all raw
	assert(m.map(flx, 0xB0, 0x27, 0x10).kind == Kind::unknown);
	assert(m.map(flx, 0x90, 0x7E, 0x7F).kind == Kind::unknown);
	assert(m.map("Launchpad", 0x90, 0x0B, 0x7F).kind == Kind::unknown);

	std::puts("controllers ok");
}
