# MIDI-to-BMS-Converter
Converts Midis to *Super Mario Galaxy 1 &amp; 2's* BMS sequence format

## Usage
Drag and drop your Midi on one of the bat files or use command line usage:
`python MIDI-to-BMS.py Input.mid Output.bms LogarithmicConvert?`

Example: `python MIDI-to-BMS.py HappyBirthday.mid ToYou.bms True`
### Instruments
The instrument and bank values defined in the Midi are transferred directly to the BMS.
For example, if you have mixed a Midi with the soundfont file extracted from the game, the exact same instruments will also be used in the BMS.
Provided that your DAW/midi editor also exports them!

If there are no Bank Select commands in the Midi, the game will use bank 0 as default.
### Looping
Place markers with the names **LoopStart** and **LoopEnd** in your midi to define loop points.
If you want the song to be repeated in its entirety, add a marker with the name **LoopAll** in the midi.
If none of these markers are in the midi, the song will simply end.

Note that if you have a **LoopAll** but also a **LoopStart** and **LoopEnd** marker in the midi, it will use the loop points instead of looping the whole song.

### Midi Controllers
Currently, the following midi controllers will be imported to the BMS:

- **CC 91** Reverb (Wet/Dry)
- **CC 92** Tremolo (Wet/Dry)
- **CC 93** Tremolo (Rate) - If CC 92 is used but not this one, the game will use a default value of 50%
- **CC 01** Vibrato (Wet/Dry)
- **CC 02** Vibrato (Rate) - If CC 1 is used but not this one, the game will use a default value of 50%

Pitch Wheel and BPM changes during the song are also supported.

### Logarithmic
Super Mario Galaxy's Synthesizer uses logarithmic volume relation. So if your midi was created with a Synthesizer with linear volume ratios, you can enter "True" in place of ***LogarithmicConvert?*** in command line (or use the bat file per drag and drop) to have the BMS converted logarithmic values.

### PPQN
Currently, the PPQN (the "resolution" of a Midi) will be converted to 120 by default in the exported BMS, which is the standard of the Galaxy games.

## Preparation
You need:
* **Python**
* **Mido Python Module**

To install Mido, open command line and enter ***pip install mido*** 

The Bat files with "compressed" requires path to a compress tool, such as yaz0enc.exe from [RARC Tools](https://kuribo64.net/get.php?id=5c98RKoV3uJdGBin). Open the Bat with a text editor and replace "C:\Tools\yaz0enc.exe" with path to the exe.

## Plans for Updates
* Timing and Chord Generation
* Control about BMS-only events (such as jumping to other parts of the song) via Markers or similar


