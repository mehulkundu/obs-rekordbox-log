#pragma once

#include <string>
#include <vector>

struct MidiDevice {
	std::string name;
	bool named; // true if controllers.cpp has a table for it
};

// Call on the main thread: CoreMIDI sends setup-change notifications to the creating thread's run loop.
// Returns 0 or the CoreMIDI error.
int midi_start();
void midi_stop();
std::vector<MidiDevice> midi_devices();
