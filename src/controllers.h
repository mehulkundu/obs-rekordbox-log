#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <tuple>

// What one MIDI message means. unknown: log it raw. consumed: first half of a 14-bit pair, log nothing yet.
enum class Kind { unknown, named, consumed };

struct Ctl {
	Kind kind = Kind::unknown;
	std::string name;
	double v = 0;
};

// Turns MIDI 1.0 channel-voice messages from known controllers into named controls.
// Stateful: holds the MSB of each 14-bit control until its LSB arrives.
class Mapper {
public:
	Ctl map(const std::string &src, uint8_t status, uint8_t d1, uint8_t d2);
	static bool knows(const std::string &src);

private:
	std::map<std::tuple<std::string, uint8_t, uint8_t>, uint8_t> msb_;
};
