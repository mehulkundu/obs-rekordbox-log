#include "controllers.h"

// Pioneer DJ DDJ-FLX4, from Pioneer DJ's "DDJ-FLX4 MIDI Message List".
// Channel 0 = deck 1, 1 = deck 2, 4/5 = beat FX, 6 = mixer and browser, 7-10 = pads.
namespace flx4 {

const char *deck_note(uint8_t n)
{
	switch (n) {
	case 0x0B: return "play";
	case 0x0C: return "cue";
	case 0x10: return "loop.in";
	case 0x11: return "loop.out";
	case 0x1B: return "pad.mode.hotcue";
	case 0x1E: return "pad.mode.padfx1";
	case 0x20: return "pad.mode.beatjump";
	case 0x22: return "pad.mode.sampler";
	case 0x36: return "jog.touch";
	case 0x3F: return "shift";
	case 0x4D: return "reloop";
	case 0x51: return "loop.half";
	case 0x53: return "loop.double";
	case 0x54: return "headphone.cue";
	case 0x58: return "sync";
	case 0x5C: return "sync.long";
	case 0x69: return "pad.mode.keyboard";
	case 0x6B: return "pad.mode.padfx2";
	case 0x6D: return "pad.mode.beatloop";
	}
	return nullptr;
}

// 14-bit: MSB on CC n, LSB on CC n + 0x20.
const char *deck_cc14(uint8_t n)
{
	switch (n) {
	case 0x00: return "tempo";
	case 0x04: return "trim";
	case 0x07: return "eq.hi";
	case 0x0B: return "eq.mid";
	case 0x0F: return "eq.low";
	case 0x13: return "fader";
	}
	return nullptr;
}

const char *mixer_cc14(uint8_t n)
{
	switch (n) {
	case 0x0C: return "mixer.headphone.mix";
	case 0x17: return "deck1.cfx";
	case 0x18: return "deck2.cfx";
	case 0x1F: return "mixer.crossfader";
	}
	return nullptr;
}

// Relative: 64 = no movement.
const char *deck_rel(uint8_t cc)
{
	switch (cc) {
	case 0x21: return "jog.side";
	case 0x22: return "jog"; // platter, vinyl mode on
	case 0x23: return "jog"; // platter, vinyl mode off
	case 0x29: return "jog.search";
	}
	return nullptr;
}

const char *pad_mode(uint8_t note)
{
	static const char *modes[] = {"hotcue", "padfx1", "beatjump", "sampler", "keyboard", "padfx2", "beatloop", "keyshift"};
	return modes[(note >> 4) & 7];
}

} // namespace flx4

bool Mapper::knows(const std::string &src)
{
	return src.find("DDJ-FLX4") != std::string::npos;
}

Ctl Mapper::map(const std::string &src, uint8_t status, uint8_t d1, uint8_t d2)
{
	Ctl out;
	if (!knows(src))
		return out;

	uint8_t type = status & 0xF0, ch = status & 0x0F;
	if (type == 0x80) { // note off = note on with velocity 0
		type = 0x90;
		d2 = 0;
	}
	auto named = [&](std::string name, double v) {
		out.kind = Kind::named;
		out.name = std::move(name);
		out.v = v;
		return out;
	};
	std::string deck = ch < 2 ? "deck" + std::to_string(ch + 1) + "." : "";

	if (type == 0x90) {
		double v = d2 ? 1 : 0;
		if (ch < 2)
			if (const char *n = flx4::deck_note(d1))
				return named(deck + n, v);
		if (ch >= 7 && ch <= 10 && (d1 & 0x0F) < 8) {
			std::string name = "deck" + std::to_string(ch < 9 ? 1 : 2) + ".pad." + flx4::pad_mode(d1) + "." +
					   std::to_string((d1 & 0x0F) + 1);
			if (ch == 8 || ch == 10)
				name += ".shift";
			return named(name, v);
		}
		if ((ch == 4 || ch == 5) && d1 == 0x47)
			return named("fx.beat.on", v);
		if (ch == 4 && d1 == 0x63)
			return named("fx.beat.select", v);
		if (ch == 4 && d1 == 0x4A)
			return named("fx.beat.prev", v);
		if (ch == 4 && d1 == 0x4B)
			return named("fx.beat.next", v);
		if (ch == 4 && d1 == 0x10 && d2)
			return named("fx.beat.channel", 1);
		if (ch == 5 && d1 == 0x11 && d2)
			return named("fx.beat.channel", 2);
		if (ch == 6 && d1 == 0x46)
			return named("deck1.load", v);
		if (ch == 6 && d1 == 0x47)
			return named("deck2.load", v);
		if (ch == 6 && d1 == 0x41)
			return named("browse.press", v);
		return out;
	}

	if (type == 0xB0) {
		uint8_t n = d1 & 0x1F;
		const char *cc14 = nullptr;
		if (d1 < 0x40) {
			if (ch < 2)
				cc14 = flx4::deck_cc14(n);
			else if (ch == 6)
				cc14 = flx4::mixer_cc14(n);
			else if (ch == 4 && n == 0x02)
				cc14 = "fx.beat.level";
		}
		if (cc14) {
			auto key = std::make_tuple(src, ch, n);
			if (d1 < 0x20) {
				msb_[key] = d2;
				out.kind = Kind::consumed;
				return out;
			}
			auto it = msb_.find(key);
			if (it == msb_.end())
				return out;
			return named(deck + cc14, ((it->second << 7) | d2) / 16383.0);
		}
		if (ch < 2)
			if (const char *r = flx4::deck_rel(d1))
				return named(deck + r, int(d2) - 64);
		if (ch == 6 && d1 == 0x40)
			return named("browse", int(d2) - 64);
	}
	return out;
}
