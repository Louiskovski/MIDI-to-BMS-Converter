# MIDI-to-BMS-Converter
Converts Midis to *Super Mario Galaxy 1 &amp; 2's* BMS sequence format.

Can also generate timing tracks (for beats and CIT usage) and CIT files (chord and scale for effects).

## Usage
Drag and drop your Midi on one of the bat files or use command line usage:
`python MIDI-to-BMS.py Input.mid Output.bms LogarithmicConvert?`

Example: `python MIDI-to-BMS.py HappyBirthday.mid ToYou.bms True`
### Instruments
The instrument event values defined in the Midi (Program Change, Bank Select (MSB and LSB)) are transferred directly to the BMS.
For example, if you have mixed a Midi with the soundfont file extracted from the game, the exact same instruments will also be used in the BMS.
Provided that your DAW/midi editor also exports them!

If there are no Bank Select commands in the Midi, the game will use bank 0 as default.

(A little tutorial on how to extract the soundfont from the game for DAW use will be coming soon.)
### Looping
Place markers with the names **LoopStart** and **LoopEnd** in your midi to define loop points.
If you want the song to be repeated in its entirety, add a marker with the name **LoopAll** in the midi.
If none of these markers are in the midi, the song will simply end.

Note that if you have a **LoopAll** but also a **LoopStart** and **LoopEnd** marker in the midi, it will use the loop points instead of looping the whole song.

### Midi Controllers
Currently, the following midi controllers will be imported to the BMS:

#### Basic
- **CC 00** Bank Select (MSB)
- **CC 07** Channel Volume
- **CC 10** Pan

#### Effects
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

### Timing and CIT Data Generation
[Example Midis can be found here](https://kuribo64.net/get.php?id=vAtG6DE5AoRxOOGp)

Beat data for timing things like beat blocks, as well as associated chord and note scale data for effects such as item jingles can be generated as follows:
#### Timing/Beat
To enable timing and chord generation for your midi, add a marker called **BEAT_4/4** for a four-quarter time song or a **BEAT_3/4** for a three-quarter time song to the midi at any location.

#### Chord and Scales
Chords and scale note pairs are defined in the Midi as follows. These notes must be on a track for channel 0. Any other channel is not used for this.

![screenshot](CIT_Explain1.png)
##### Bass Note
Defines the harmonic basis for the chord. This is necessary for each chord set.

Is defined in *octave range 5 (C4 (midi 48) - B4 (midi 59))*. Only one is allowed per chord and scale set.

The length of the bass note is also defined as the range in which the chord and scale notes are taken into account. As shown in the picture:
![screenshot](CIT_Explain2.png)

##### Chord Notes
Chords whose notes are used by objects such as blue flip panels, as well as for menu sounds and 2-player luma.

Are defined in *octave range 6 (C5 (midi 60) - B5 (midi 71))*. Up to 7 notes are possible.

##### Scale Note Pairs
Music scales or harmonic ladder. These are mainly used for melody jingles such as Coin-Appear or Sling stars.
These notes are defined in ascending order in the midi.

Are specified in *octave range 7 (C6 (midi 72) - B6 (midi 83))*.

#### Converting
When converting a prepared Midi, additional information, including the notes, is displayed.

At the end you will get a *IntoBeat* and *LoopBeat* value, which you need to enter in the MultiBgmInfo for your song, if it is meant for combination with streamed AST (Multi-BGM). If it is an BMS-only song, you can ignore these values.

#### Additional Notes
If you want to use your timing and chord data for a streamed song, the song must be in AST format at 32000 Hz.


## Preparation
You need:
* **Python**
* **Mido Python Module**

To install Mido, open command line and enter ***pip install mido*** 

The Bat files with "compressed" requires path to a compress tool, such as yaz0enc.exe from [RARC Tools](https://kuribo64.net/get.php?id=5c98RKoV3uJdGBin). Open the Bat with a text editor and replace "C:\Tools\yaz0enc.exe" with path to the exe.

## Plans for Updates
* Control about BMS-only events (such as jumping to other parts of the song) via Markers or similar

## Special Thanks
* **SY24, Super Hackio and Xayrga** for documenting BMS format
* **TZGaming** for some tipps about the game's soundfont
* **VGMTrans Team** for their helpful tool that helped analysing the format
* **Carla** for their helpful modular audio plugin host, that allows for great soundfont and effects usage in any daw!
