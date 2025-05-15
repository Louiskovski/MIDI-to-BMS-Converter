# MIDI-to-BMS-Converter
Converts Midis to *Super Mario Galaxy 1 &amp; 2's* BMS sequence format

## Usage
Drag and drop your Midi on the DragMidiOnMe.bat to get your BMS file.
### Instruments
The instrument and bank commands defined in the Midi are transferred directly to the BMS.
For example, if you have mixed a Midi with the soundfont file extracted from the game, the exact same instruments will also be used in the BMS.
Provided that your DAW/midi editor also exports them!
### Looping
Place markers with the names **LoopStart** and **LoopEnd** in your midi to define loop points.
If none of these markers are in the midi, the song will simply be repeated in its entirety.
If you don't want a loop (e.g. for jingles), add a marker with the name **NoLoop** in the midi.

## Prepation
You need:
* **Python**
* **Mido Python Module**

To install Mido, open command line and enter ***pip install mido*** 
