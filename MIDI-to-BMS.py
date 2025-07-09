import sys
import mido
import os
import csv
#import pandas as pd
import math
from mido import MidiFile, MetaMessage
import struct
from collections import defaultdict
from mido import Message


def Generate_TimingNotes(Takt=0):
    sequence = []

    def add_notes(start_time, pitch, count, length, spacing, first_velocity):
        events = []
        time = start_time
        for i in range(count):
            velocity = first_velocity if i == 0 else 110
            events.append((time, Message('note_on', note=pitch, velocity=velocity, time=0)))
            events.append((time + length, Message('note_off', note=pitch, velocity=0, time=0)))
            time += spacing
        return events

    # MIDI Notezahlen
    note_C2 = 24        # 1 Takt Note
    note_Fs2 = 30       # Halbe Takt Note
    note_Eb2 = 27       # Vierteltakt Note
    note_Db2 = 25       # Achteltaktnoten, mit Abstand. (Positionen zum Abspielen der Melodien ??)


    #Takt = 1 #TEST

    # Alle Reihen sollen bei Tick 0 starten
    if Takt == 0: #(4/4 Takt)
        sequence += add_notes(0, note_C2, 4, 120, 120, 13)
        sequence += add_notes(0, note_Fs2, 8, 60, 60, 16)
        sequence += add_notes(0, note_Eb2, 16, 30, 30, 22)
        sequence += add_notes(0, note_Db2, 32, 13, 15, 34)

    if Takt == 1:  #(3/4 Takt)
        sequence += add_notes(0, note_C2, 3, 120, 120, 13)
        sequence += add_notes(0, note_Fs2, 6, 60, 60, 16)
        sequence += add_notes(0, note_Eb2, 12, 30, 30, 22)
        sequence += add_notes(0, note_Db2, 24, 13, 15, 34)
    
    
    # Nach Zeit sortieren, damit sie korrekt verarbeitet werden können
    sequence.sort(key=lambda e: e[0])

    return sequence

def get_note_name(note_number, no_octave=False):
    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F',
                  'F#', 'G', 'G#', 'A', 'A#', 'B']
    name = note_names[note_number % 12]
    if no_octave:
        return name  # nur Buchstabe (zb. "D")
    octave = (note_number // 12) - 1
    return f"{name}{octave}"
    
def get_note_byte(note_number):
    #print("test")
    return note_number % 12



def LogarithmicCalculate(value): # Recalculate linear volume values to logarithmic ones
    if value == 0:
        return 0
    gain = 127 / (40 * math.log10(1 + 1))  #Normalise to 127
    return max(1, min(127, int(gain * 40 * math.log10(1 + value / 127))))


def Get_BPM(filename):
    mid = MidiFile(filename)
    for track in mid.tracks:
        for msg in track:
            if msg.type == 'set_tempo':
                bpm = round(60000000 / msg.tempo)
                bpm_hex = f"{bpm:02X}"
                return bpm, bpm_hex
    return None, None  #Kein Tempo gefunden


def Get_UsedChannels(midi_path):
    mid = MidiFile(midi_path)
    used_channels = set()

    for track in mid.tracks:
        for msg in track:
            if msg.type in ['note_on', 'note_off', 'control_change', 'program_change'] and hasattr(msg, 'channel'): 
                used_channels.add(msg.channel)

    return sorted(used_channels)


def Find_Marker_Position(filename, target_name="LoopStart"):
    mid = mido.MidiFile(filename)

    for track in mid.tracks:
        tick_position = 0
        for msg in track:
            tick_position += msg.time
            if msg.type == 'marker' and msg.text == target_name:
                return tick_position  # Sofort zurückgeben wenns gefunden

    return None  # Falls kein Marker mit dem namen gefunden wurde


def Get_Last_Note_Tick(filename):
    mid = mido.MidiFile(filename)
    last_tick = 0

    for track in mid.tracks:
        current_tick = 0
        for msg in track:
            current_tick += msg.time
            if msg.type in ['note_off', 'note_on'] and msg.velocity == 0:
                last_tick = max(last_tick, current_tick)
        
    return last_tick



def ENCODE_VLQ(value): # VLQ-Kodierung (wenn größer als 80 Zeugs) für den F0-Command  (Duration)
    bytes_out = []
    while True:
        byte = value & 0x7F
        bytes_out.insert(0, byte)
        value >>= 7
        if value == 0:
            break
    for i in range(len(bytes_out) - 1):
        bytes_out[i] |= 0x80  #Fortsetzungsbit setzen
    return bytes_out




## VOICE MECHANIC ## ---------

MAX_VOICES = 7   # in case more are possible, change this
free_voices = list(range(1, MAX_VOICES + 1))
note_to_voice = {}
voice_to_note = {}

def assign_voice(note, ChannelNum):
    if note in note_to_voice:
        return note_to_voice[note]
    if not free_voices:
        raise RuntimeError(" --- Error! Channel " + str(ChannelNum) + " has more than 7 overlapping notes! ---")
    voice = free_voices.pop(0)
    note_to_voice[note] = voice
    voice_to_note[voice] = note
    return voice

def release_voice(note):
    voice = note_to_voice.pop(note, None)
    if voice:
        voice_to_note.pop(voice, None)
        free_voices.insert(0, voice)  #reuse lowest first
    return voice

## VOICE MECHANIC END ## ---------



from collections import defaultdict

def NOTES_to_BMSDATA(notedata, AllTicks, ppqn_original=120, ppqn_target=120): #Nur für Taktzeug
    ppqn_scale = ppqn_target / ppqn_original

    # Zeit skalieren
    scaled_events = []
    for abs_time, msg in notedata:
        scaled_time = int(round(abs_time * ppqn_scale))
        scaled_events.append((scaled_time, msg))

    # Events nach Zeitstempel gruppieren
    grouped_events = defaultdict(list)
    for time, msg in scaled_events:
        grouped_events[time].append(msg)

    current_time = 0
    output = bytearray()
    last_bank = None

    for timestamp in sorted(grouped_events.keys()):
        delta = timestamp - current_time
        current_time = timestamp

        if delta > 0:
            output += bytes([0xF0] + ENCODE_VLQ(delta))

        for msg in grouped_events[timestamp]:

            if isinstance(msg, mido.Message):
                ## NOTES ##
                if msg.type == 'note_on' and msg.velocity > 0:
                    voice = assign_voice(msg.note, msg.channel)
                    velocity = msg.velocity
                    if LinearToLogarithmic == True:
                        velocity = LogarithmicCalculate(msg.velocity)
                    output += bytes([
                        msg.note & 0xFF,
                        voice & 0xFF,
                        velocity & 0xFF
                    ])

                elif msg.type in ['note_off', 'note_on'] and msg.velocity == 0:
                    if msg.note in note_to_voice:
                        voice = release_voice(msg.note)
                        if voice is not None:
                            output += bytes([0x80 | (voice & 0x0F)])

                ## MIDI CC ##
                elif msg.type == 'control_change':
                    if msg.control == 0:
                        last_bank = msg.value
                    elif msg.control == 32:
                        last_bank = msg.value
                    else:
                        ## CHANGE CHORD AND MELODIE
                        if msg.control == 1:
                            output += bytes([0xE2, msg.value & 0xFF, 0xE3, msg.value & 0xFF])
                        ## Enter Loop Start Placeholder
                        if msg.control == 2:
                            output += bytes([0x77, 0x77, 0x77, 0x01])
                        ## Enter Loop End Placeholder
                        if msg.control == 3:
                            if msg.value == -1:        ## Letztes E1 Kommand erneut (wegen loop)
                                output += bytes([0xE2, 0x00, 0xE3, 0x00])
                            else:
                                output += bytes([0xE2, msg.value & 0xFF, 0xE3, msg.value & 0xFF])
                            output += bytes([0x77, 0x77, 0x77, 0x02])
                            
                        #!! E1 GEHT BEI CHORD NICHT! Nimm E2 und E3!
    return output


def GLOBALMIDIEVENTS_to_BMSDATA(midifile, AllTicks, Loop, ppqn_target=120):
    mid = mido.MidiFile(midifile)
    ppqn_original = mid.ticks_per_beat
    ppqn_scale = ppqn_target / ppqn_original

    events = []
    
    for track in mid.tracks:
        abs_time_real = 0.0  #float für genauere ppqn umrechnung
        abs_time = 0 
        for msg in track:
            #scaled_time = int(round(msg.time * ppqn_scale))
            #abs_time += scaled_time
            abs_time_real += msg.time * ppqn_scale
            abs_time = int(round(abs_time_real))

            # Marker für LoopStart und LoopEnd
            if msg.type == 'marker':
                if msg.text == 'LoopStart':
                    events.append((abs_time, 'LoopStart'))
                elif msg.text == 'LoopEnd':
                    events.append((abs_time, 'LoopEnd'))
                continue

            # Nur Tempo-Events berücksichtigen
            if msg.type == 'set_tempo':
                events.append((abs_time, msg))

    # Events sortieren nach Zeit
    events.sort(key=lambda e: e[0])

    current_time = 0
    output = bytearray()

    for timestamp, msg in events:
        delta = timestamp - current_time
        current_time = timestamp

        # Pausen als Delay kodieren
        if delta > 0:
            output += bytes([0xF0] + ENCODE_VLQ(delta))

        if isinstance(msg, mido.MetaMessage) and msg.type == 'set_tempo':
            bpm = round(mido.tempo2bpm(msg.tempo))
            output += bytes([0xE0,0x00, bpm & 0xFF])

        elif isinstance(msg, str):
            if Loop == True:
                if msg == 'LoopStart':
                    output += bytes([0x77, 0x77, 0x77, 0x01])  # Platzhalter für Loop Start
                elif msg == 'LoopEnd':
                    output += bytes([0x77, 0x77, 0x77, 0x02])  # Platzhalter für Loop End
    
    
    # Restdauer, falls es nicht loopen soll
    if Loop == False:
        remaining = int(round(AllTicks * ppqn_target / ppqn_original)) - current_time
        if remaining > 0:
            output += bytes([0xF0] + ENCODE_VLQ(remaining))
    
    
    #output += bytes([0xFF])  # Nein! Legen wir in der Hauptaction fest
    return output

from mido import MidiFile
import mido

def note_number_to_name(note):
    """Wandelt MIDI-Notennummer in Namen wie C4, D#4 um"""
    return mido.get_note_name(note)

def MIDICHANNEL_to_TIMINGandCHORD(midifile, target_channel=1, Takt=0, LoopAtAll=False):
    trigger_range = range(48, 60)  # C3–H3          BASS NOTE
    upper_octave_range = range(60, 72)  # C4–H4     AKKORD NOTEN
    melodie_octave_range = range(72, 84)  # C5–H5   MELODIE NOTEN
    loop_start_markers = []
    loop_end_markers = []

    #mid = MidiFile(midifile)
    #ppqn_scale = 1
    
    mid = mido.MidiFile(midifile)
    ppqn_original = mid.ticks_per_beat
    ppqn_scale = 120 / ppqn_original          #PPQN MUSS 120 sein! Sonst geht der Timingstuff nicht!
    
    

    trigger_events = []  # [(tick, note)]           BASS NOTE
    upper_octave_events = []  # [(tick, note)]      AKKORD NOTEN
    melodie_octave_events = []  # [(tick, note)]    MELODIE NOTEN


    TriggernoteCounter_forLoop = -1

    DEBUG = False

    print("------------------------------------")
    print()
    print()
    print("--- 🎹 CHORD and 🎼 MUSICAL SCALE GENERATION (CIT) ---")
    print()

    # Taktnoten generieren 
    if Takt == 0:
        print("   Beat: Fourth quarter beat")
        bereich_groesse=480
    
    if Takt == 1:
        print("   Beat: Three quarter beat")
        bereich_groesse=360

    print()


    Taktblock = Generate_TimingNotes(Takt) #Anscheinend spackt die Variable manchmal ?!

    BassNotes = []
    ChordNotes = []
    MelodieNotes = []

    
    C3CallBytesAtAll = False
    
    Looping = False
    LoopingErrorCounter1 = 0
    LoopingErrorCounter2 = 0
    output = bytearray()
    CIToutput = bytearray()
    
    CITBassnotes_ByteList = bytearray()




    # Events sammeln:
    for track in mid.tracks:
    
        time_acc_real = 0.0   # float für exakte Berechnung
        time_acc = 0
        for msg in track:
            #time_acc += int(round(msg.time * ppqn_scale))
            time_acc_real += msg.time * ppqn_scale
            time_acc = int(round(time_acc_real))  # jetzt sauber gerundet
            
            if msg.type == 'note_on' and msg.velocity > 0 and hasattr(msg, "channel") and msg.channel == target_channel:
                if msg.note in trigger_range:
                    trigger_events.append((time_acc, msg.note))
                    
                    
                    # Triggernoten zählen bis LoopStart
                    if not loop_start_markers or time_acc < loop_start_markers[0]:
                        TriggernoteCounter_forLoop += 1
                    
                elif msg.note in upper_octave_range:
                    upper_octave_events.append((time_acc, msg.note))
                elif msg.note in melodie_octave_range:
                    melodie_octave_events.append((time_acc, msg.note))
                    
            if msg.type in ['note_off', 'note_on'] and msg.velocity == 0:
                last_tick = max(0, time_acc) #Um letzten Tick des Tracks zu kriegen (für Akkordstuff und falls kein Loop)
            ##NEU:
            if msg.type == 'marker':
                if msg.text == 'LoopStart':
                    loop_start_markers.append(time_acc)
                    LoopingErrorCounter1 = LoopingErrorCounter1 +1
                elif msg.text == 'LoopEnd':
                    loop_end_markers.append(time_acc)
                    LoopingErrorCounter2 = LoopingErrorCounter2 +1
    if not trigger_events:
        sys.exit("❌ ERROR: No bass note found!")
        return


    if LoopingErrorCounter1 >= 1 or LoopingErrorCounter2 >= 1:
        Looping = True
        
        # print("Anzahlo----------------------------------")
        # print(TriggernoteCounter_forLoop)







    # 1. Triggeranalyse pro Bereich
    #max_tick = max(t for t, _ in trigger_events) #ne sonst werden Bereiche nach letzter TriggernoteOn ignoriert!
    if Looping == True:
        if LoopingErrorCounter1 == 1 and LoopingErrorCounter2 == 1:
            max_tick = max(loop_end_markers)
        else:
            if LoopingErrorCounter1 >= 2:
                sys.exit("❌ ERROR: You have more than one 'LoopStart' marker!")
                return
            elif LoopingErrorCounter1 <= 0:
                sys.exit("❌ ERROR: You don't have 'LoopStart' marker!")
                return
            elif LoopingErrorCounter2 >= 2:
                sys.exit("❌ ERROR: You have more than one 'LoopEnd' marker!")
                return
            elif LoopingErrorCounter2 <= 0:
                sys.exit("❌ ERROR: You don't have 'LoopEnd' marker!")
                return
    else:
        max_tick = last_tick  

    bereich_index = 1
    tick = 0

    TriggerNoteE1_AllCounter = -1 #Das erste fängt bei 0 an!

    #print("\n--- TaktBereichsanalyse ---")
    while tick <= max_tick + bereich_groesse:
        next_tick = tick + bereich_groesse
        
        # Trigger
        trigger_in_range = [(t, n) for t, n in trigger_events if tick <= t < next_tick]
        trigger_at_start = any(t == tick for t, _ in trigger_in_range)

        # Loop-Marker
        loopstart_at_start = any(t == tick for t in loop_start_markers)
        loopstart_in_range = any(tick <= t < next_tick for t in loop_start_markers)

        loopend_at_start = any(t == tick for t in loop_end_markers)
        loopend_in_range = any(tick <= t < next_tick for t in loop_end_markers)

        #Debug Beschreibung aufbauen
        beschreibung = f"- BAR {bereich_index}:"
        teile = []


        #Bools
        Bool_Trigger_AtStart = False
        Bool_Trigger_InRange = False
        Bool_LOOPstart_AtStart = False
        Bool_LOOPstart_InRange = False
        Bool_LOOPend_AtStart = False
        Bool_LOOPend_InRange = False
        
        Bool_Trigger_Multiple = False
        TriggerNoteTICKlist = []

        TriggerNoteCounter = 0

        TriggerNoteE1_list = []


        if trigger_at_start:
            #teile.append("✅ Trigger direkt am Anfang")
            Bool_Trigger_AtStart = True
        elif trigger_in_range:
            #teile.append("✅ Trigger im Bereich")
            Bool_Trigger_InRange = True
            
        if loopstart_at_start:
            #teile.append("🟢 Loop Start direkt am Anfang")
            Bool_LOOPstart_AtStart = True
        elif loopstart_in_range:
            #teile.append("🟢 Loop Start im Bereich")
            Bool_LOOPstart_InRange = True

        if loopend_at_start:
            #teile.append("🔴 Loop End direkt am Anfang")
            Bool_LOOPend_AtStart = True
        elif loopend_in_range:
            #teile.append("🔴 Loop End im Bereich")
            Bool_LOOPend_InRange = True

        # if teile:
            # print(f"{beschreibung} {' and '.join(teile)}. (tick {tick} - {next_tick - 1})")
        # else:
            # print(f"{beschreibung} no notes and marker. (tick {tick} - {next_tick - 1})")

        # Debugprint: Positionen der Marker und Trigger
        for t in loop_start_markers:
            if tick <= t < next_tick:
                #print(f"   Loop Start (tick {t})")
                LoopStartTICK = t - tick #Tickposition per Taktbereich bekommen
                
                ## Beat Info Stuff
                IntoBeat = t / 120 #120 Ticks = 1 Beat
                IntoBeatTick = t #für loop end merken
                #print(f"    IntoBeat: {IntoBeat}")
                IntoBeatFullNumber = IntoBeat.is_integer() #Checken ob es eine ganze Zahl ist. Wenn nicht, Warnung geben!
                #print(IntoBeatFullNumber)
        for t in loop_end_markers:
            if tick <= t < next_tick:
                #print(f"   Loop End (tick {t})")
                LoopEndTICK = t - tick
                
                ## Beat Info Stuff
                LoopBeat = (t - IntoBeatTick) / 120 #120 Ticks = 1 Beat
                #print(f" IntoBeat: {LoopBeat}")
                LoopBeatFullNumber = LoopBeat.is_integer() #Checken ob es eine ganze Zahl ist. Wenn nicht, Warnung geben!
                #print(LoopBeatFullNumber)
                
        for t, n in trigger_in_range:
            #print(f"   Bassnote {get_note_name(n)} (tick {t})")
            #print("dududu")
            #print(n)
            
            # - CIT Stuff merken - #
            
            #CIToutput += bytes([get_note_byte(n)])                          # Bassnote writen
            #CIToutput += bytes([0x7F, 0x7F, 0x7F, 0x7F, 0x7F, 0x7F, 0x7F])  # Leere Akkordnoten writen
            
            CITBassnotes_ByteList += bytes([get_note_byte(n)])               # Bassnote merken
            
            
            
            # - Triggernote - #
            TriggerNoteTICK = t - tick # t(Globale Tickposition der Note) - tick(Starttick des Bereiches) = Tickposition der Note INNERHALB des Bereichs
            TriggerNoteE1_AllCounter = TriggerNoteE1_AllCounter + 1  #Global gespeichert, welche ID für den E1 command
            TriggerNoteE1 = TriggerNoteE1_AllCounter #ID für den E1 command (wenns nur eine Triggernote ist)
            
            # Bei mehreren Triggernoten in einem Bereich
            TriggerNoteCounter = TriggerNoteCounter +1 #Zum Checken wenn mehreren Triggernoten in einem Bereich
            
            TriggerNoteTICKlist.append(TriggerNoteTICK) # Ticks als Liste statt einzelnd speichern. -> NUR bei mehreren Triggernoten!
            TriggerNoteE1_list.append(TriggerNoteE1_AllCounter) # ID für E1 command als Liste speichern -> NUR bei mehreren Triggernoten!
            
            
            
            
        if TriggerNoteCounter > 1:
            Bool_Trigger_Multiple = True
        


        

        
        ### -- WRITE BYTES -- ###
        
        
        
        #da diese timingnoten so megaviel speicher in Anspruch nehmen obwohl die per taktbereich gleich sind, nehmen
        #wir C3 Caller zu einem taktbereich stattdessen. Da aber die E1 commands zum Wechseln von Akkord und MelodieNotes
        #glorreicherweise AUCH in dem track sein müssen (mehrere Tracks auf einem Channel nicht möglich..), müssen wir blöd
        #umdenken und checken, welcher taktbereich einfach C5 Call nehemn soll, und welche normal generiert mit den commands, und Loop!
        
        
        
        
        ##  Kombis bei: mehrere Triggernoten im Bereich 

        if Bool_Trigger_Multiple == True and Bool_LOOPstart_AtStart == True:
            if DEBUG == True:
                print("TEST: Mehrere Trigger und LoopStart Am Start!")
                print(LoopStartTICK)
                print("Bei welchen Ticks?:")
                print(TriggerNoteTICKlist)#Bei welchen Ticks die E1 commands
                print("Welche IDs für E1?:")
                print(TriggerNoteE1_list) #Welche ID für die E1 commands
            
            
            output += bytes([0x77, 0x77, 0x77, 0x01]) ## LoopStart

            ## Taktbla mit mehreren Triggernoten drin:
            E1CommandCounter = TriggerNoteE1_list[0] # Erste E1 ID nehmen, um dann einfach hochzählen 
            TaktblockMitZusatz = Generate_TimingNotes(Takt)#Taktblock
            for Ticki in TriggerNoteTICKlist:
                TaktblockMitZusatz.append((Ticki, Message('control_change', control=1, value=E1CommandCounter))) # E1 in Taktblock einfügen
                E1CommandCounter = E1CommandCounter + 1
                
            output += NOTES_to_BMSDATA(TaktblockMitZusatz, bereich_groesse)
            
        
        elif Bool_Trigger_Multiple == True and Bool_LOOPstart_InRange == True:
            if DEBUG == True:
                print("TEST: Mehrere Trigger und LoopStart im Bereich!")
                print(LoopStartTICK)
                print("Bei welchen Ticks?:")
                print(TriggerNoteTICKlist)#Bei welchen Ticks die E1 commands
                print("Welche IDs für E1?:")
                print(TriggerNoteE1_list) #Welche ID für die E1 commands
               
            ## Taktbla mit mehreren Triggernoten drin:
            E1CommandCounter = TriggerNoteE1_list[0] # Erste E1 ID nehmen, und dann einfach hochzählen 
            TaktblockMitZusatz = Generate_TimingNotes(Takt)#Taktblock
            for Ticki in TriggerNoteTICKlist:
                TaktblockMitZusatz.append((Ticki, Message('control_change', control=1, value=E1CommandCounter))) # E1 in Taktblock einfügen
                E1CommandCounter = E1CommandCounter + 1
            
            TaktblockMitZusatz.append((LoopStartTICK, Message('control_change', control=2, value=1))) # Loop Start
            
            output += NOTES_to_BMSDATA(TaktblockMitZusatz, bereich_groesse) # Zu BMS Data umwandeln und schreiben

        
        
        elif Bool_Trigger_Multiple == True:
            if DEBUG == True:
                print("TEST: NUR mehrere Trigger!")
                print("Bei welchen Ticks?:")
                print(TriggerNoteTICKlist)#Bei welchen Ticks die E1 commands
                print("Welche IDs für E1?:")
                print(TriggerNoteE1_list) #Welche ID für die E1 commands
            
            ## Taktbla mit mehreren Triggernoten drin:
            E1CommandCounter = TriggerNoteE1_list[0] # Erste E1 ID nehmen, und dann einfach hochzählen 
            TaktblockMitZusatz = Generate_TimingNotes(Takt)#Taktblock
            for Ticki in TriggerNoteTICKlist:
                TaktblockMitZusatz.append((Ticki, Message('control_change', control=1, value=E1CommandCounter))) # E1 in Taktblock einfügen
                E1CommandCounter = E1CommandCounter + 1
            output += NOTES_to_BMSDATA(TaktblockMitZusatz, bereich_groesse) # Zu BMS Data umwandeln und schreiben
            
        
        ##  Kombis bei: einzelnen Triggernoten im Bereich 
        
        elif Bool_Trigger_AtStart == True and Bool_LOOPstart_AtStart == True:
            if DEBUG == True:
                print("TEST: Trigger und LoopStart Am Start!")
                print(LoopStartTICK)
                print("Trigger bei Tick: " + str(TriggerNoteTICK))
                print("Trigger Comand E1: " + str(TriggerNoteE1))
            
            C3CallBytesAtAll = True

            
            output += bytes([0x77, 0x77, 0x77, 0x01]) ## LoopStart / Adresse einfach merken
            output += bytes([0xE2, TriggerNoteE1 & 0xFF, 0xE3, TriggerNoteE1 & 0xFF]) ## E1 Trigger
            output += bytes([0xC3, 0x77, 0x88, 0x99])## C3 CALLER ZU TAKT BLA
            
            
        elif Bool_Trigger_AtStart == True and Bool_LOOPstart_InRange == True:
            if DEBUG == True:
                print("TEST: Trigger am Start, und LoopStart im Bereich!")
                print(LoopStartTICK)
                print("Trigger bei Tick: " + str(TriggerNoteTICK))
                print("Trigger Comand E1: " + str(TriggerNoteE1))
            
            
            output += bytes([0xE2, TriggerNoteE1 & 0xFF, 0xE3, TriggerNoteE1 & 0xFF]) ## E1 Trigger
            ## Taktbla mit LoopStart drin:
            TaktblockMitZusatz = Generate_TimingNotes(Takt)#Taktblock
            TaktblockMitZusatz.append((LoopStartTICK, Message('control_change', control=2, value=1)))
            output += NOTES_to_BMSDATA(TaktblockMitZusatz, bereich_groesse)
            
            
            
        elif Bool_Trigger_InRange == True and Bool_LOOPstart_AtStart == True:
            if DEBUG == True:
                print("TEST: Trigger im Bereich, und LoopStart am Start!")
                print(LoopStartTICK)
                print("Trigger bei Tick: " + str(TriggerNoteTICK))
                print("Trigger Comand E1: " + str(TriggerNoteE1))
            
            output += bytes([0x77, 0x77, 0x77, 0x01]) ## LoopStart
            ## Taktbla mit E1 Trigger drin:
            TaktblockMitZusatz = Generate_TimingNotes(Takt)#Taktblock
            TaktblockMitZusatz.append((TriggerNoteTICK, Message('control_change', control=1, value=TriggerNoteE1)))
            output += NOTES_to_BMSDATA(TaktblockMitZusatz, bereich_groesse)
            
        elif Bool_Trigger_AtStart == True and Bool_LOOPend_AtStart == True:
            if DEBUG == True:
                print("TEST: Trigger und LoopEnd Am Start!")
                print(LoopEndTICK)
                print("Trigger bei Tick: " + str(TriggerNoteTICK))
                print("Trigger Comand E1: " + str(TriggerNoteE1))
            
            #output += bytes([0xE1, TriggerNoteE1 & 0xFF, TriggerNoteE1 & 0xFF]) ## E1 Trigger ##NEE, wegen Loop
            output += bytes([0xE2, TriggernoteCounter_forLoop & 0xFF, 0xE3, TriggernoteCounter_forLoop & 0xFF]) ## E1 Trigger wegen Loop
            output += bytes([0x77, 0x77, 0x77, 0x02]) ## Loop End##########
            output += bytes([0xC3, 0x77, 0x88, 0x99])## C3 CALLER ZU TAKT BLA
            
            
        elif Bool_Trigger_AtStart == True and Bool_LOOPend_InRange == True:
            if DEBUG == True:
                print("TEST: Trigger am Start, und LoopEnd im Bereich!")
                print(LoopEndTICK)
                print("Trigger bei Tick: " + str(TriggerNoteTICK))
                print("Trigger Comand E1: " + str(TriggerNoteE1))
            
            output += bytes([0xE2, TriggerNoteE1 & 0xFF, 0xE3, TriggerNoteE1 & 0xFF]) ## E1 Trigger
            ## Taktbla mit LoopEnd drin:
            TaktblockMitZusatz = Generate_TimingNotes(Takt)#Taktblock
            TaktblockMitZusatz.append((LoopEndTICK, Message('control_change', control=3, value=TriggernoteCounter_forLoop)))
            output += NOTES_to_BMSDATA(TaktblockMitZusatz, bereich_groesse)
            
            
        elif Bool_Trigger_InRange == True and Bool_LOOPend_AtStart == True:
            if DEBUG == True:
                print("TEST: Trigger im Bereich, und LoopEnd am Start!")
                print(LoopEndTICK)
                print("Trigger bei Tick: " + str(TriggerNoteTICK))
                print("Trigger Comand E1: " + str(TriggerNoteE1))
            
            output += bytes([0xE2, TriggernoteCounter_forLoop & 0xFF, 0xE3, TriggernoteCounter_forLoop & 0xFF]) ## E1 Trigger wegen loop
            output += bytes([0x77, 0x77, 0x77, 0x02]) ## Loop End
            ## Taktbla mit LoopEnd drin:
            TaktblockMitZusatz = Generate_TimingNotes(Takt)#Taktblock
            TaktblockMitZusatz.append((LoopEndTICK, Message('control_change', control=3, value=TriggernoteCounter_forLoop)))
            output += NOTES_to_BMSDATA(TaktblockMitZusatz, bereich_groesse)
            
            
        
        
        ##  Kombis bei: einzelnen Triggernoten ohne alles 
        
        elif Bool_Trigger_AtStart == True:
            if DEBUG == True:
                print("TEST: Trigger Am Start!")
                print("Trigger bei Tick: " + str(TriggerNoteTICK))
                print("Trigger Comand E1: " + str(TriggerNoteE1))
                
                
            C3CallBytesAtAll = True
            
            output += bytes([0xE2, TriggerNoteE1 & 0xFF, 0xE3, TriggerNoteE1 & 0xFF]) ## E1 Trigger
            output += bytes([0xC3, 0x77, 0x88, 0x99])## C3 CALLER ZU TAKT BLA
            
            

            
        elif Bool_Trigger_InRange == True:
            if DEBUG == True:
                print("TEST: Trigger im Bereich!")
                print("Trigger bei Tick: " + str(TriggerNoteTICK))
                print("Trigger Comand E1: " + str(TriggerNoteE1))
            
            ## E1 Trigger in Taktdings einfügen:
            TaktblockMitZusatz = Generate_TimingNotes(Takt)#Taktblock
            TaktblockMitZusatz.append((TriggerNoteTICK, Message('control_change', control=1, value=TriggerNoteE1)))
            output += NOTES_to_BMSDATA(TaktblockMitZusatz, bereich_groesse)
            
            
            
        ##  Kombis bei: nur Loop ohne alles
            
        elif Bool_LOOPstart_AtStart == True:
            if DEBUG == True:
                print("TEST: Loop Start Am Start!")
                print(LoopStartTICK)
            
            C3CallBytesAtAll = True
            
            output += bytes([0x77, 0x77, 0x77, 0x01])## LoopStart
            output += bytes([0xC3, 0x77, 0x88, 0x99])## C3 CALLER ZU TAKT BLA
            
            
            
        elif Bool_LOOPstart_InRange == True:
            if DEBUG == True:
                print("TEST: Loop Start im Bereich!")
                print(LoopStartTICK)
            
            ## LoopStart in Taktdings einfügen:
            TaktblockMitZusatz = Generate_TimingNotes(Takt)#Taktblock
            TaktblockMitZusatz.append((LoopStartTICK, Message('control_change', control=2, value=1))) # Loop Start in Taktblock einfügen
            output += NOTES_to_BMSDATA(TaktblockMitZusatz, bereich_groesse)
            
            
        elif Bool_LOOPend_AtStart == True:
            if DEBUG == True:
                print("TEST: Loop End Am Start!")
                print(LoopEndTICK)
            
            output += bytes([0xE1, TriggernoteCounter_forLoop & 0xFF, TriggernoteCounter_forLoop & 0xFF]) ## E1 Trigger wegen loop
            output += bytes([0x77, 0x77, 0x77, 0x02])## Loop End
            # output += bytes([0xFF])## FF
            
        elif Bool_LOOPend_InRange == True:
            if DEBUG == True:
                print("TEST: Loop End im Bereich!")
                print(LoopEndTICK)
            
            ## Loop End in Taktdings einfügen:
            TaktblockMitZusatz = Generate_TimingNotes(Takt)#Taktblock
            TaktblockMitZusatz.append((LoopEndTICK, Message('control_change', control=3, value=TriggernoteCounter_forLoop))) # Loop End in Taktblock einfügen
            output += NOTES_to_BMSDATA(TaktblockMitZusatz, bereich_groesse)
            
            
            
            
        ## Kombis: Bei nichts!
        
        else:
            if DEBUG == True:
                print("TEST: Taktblock ohne alles")
                
            C3CallBytesAtAll = True
            output += bytes([0xC3, 0x77, 0x88, 0x99])## C3 CALLER ZU TAKT BLA




        tick = next_tick
        bereich_index += 1


    
    
    ### TAKTBLOCK FÜR C3 Command GENERIEREN  ###
    # GANZ ZUM SCHLUSS!
    
    if C3CallBytesAtAll == True:
        #C3GotoAdress = f.tell() ## Adresse merken für alle C3 Commands!
        C3Taktblock = bytearray()
        C3Taktblock += NOTES_to_BMSDATA(Taktblock, bereich_groesse)## TAKTDINGS BYTES OHNE ALLES writen
        C3Taktblock += bytes([0xC5]) ## C5 zum Beenden des Calls um zurückzuspringen
        
        ## Nun bei den geschriebenen Bytes die Goto Adresse bei allen C3 Commands einfügen!
        
        #output = output.replace(b'\xC3\x77\x88\x99', b'\xC3' + (C3GotoAdress.to_bytes(3, byteorder='big'))     )
        
    else:
        C3Taktblock = None


    #output += bytes([0xFF])## zu guter letzt

###----------------------------------------------------------------

    ## CIT ###
    
    CIToutput += bytes([0x00, 0x00, 0x00, 0x00, 0x43, 0x49, 0x54, 0x53])    #Header
    CIToutput += bytes([0x22, 0x33, 0x44, 0x55])                            #Filesize Platzhalter
    ChordNumber = len(trigger_events) #-1 #len zählt mit 1 als Start, nicht als 0!
    CIToutput +=  bytes(ChordNumber.to_bytes(2, byteorder='big'))            #Akkord Anzahl
    CIToutput +=  bytes(ChordNumber.to_bytes(2, byteorder='big'))            #Melodie Anzahl
    
    
    print("   Number of chords and scale note pairs: " + str(ChordNumber))
    print()
    
    ## 1. Offsets
    
    #start bei 0x chord+  offsetgrößen (4+4) x Chordanzahl 
    ChordOffset = 16   + (8 * (ChordNumber)) #Startoffset
    #print(hex(ChordOffset))
    for i in range(ChordNumber):                                                   #Akkord Offsets
        CIToutput += bytes(ChordOffset.to_bytes(4, byteorder='big'))
        ChordOffset += 8 #chordEintrag ist 8 bytes lang
        #print(hex(ChordOffset))
        
    MelodieOffset = ChordOffset #+ 8
    for i in range(ChordNumber):                                                   #Melodie Offsets
        #print(i)
        CIToutput += bytes(MelodieOffset.to_bytes(4, byteorder='big'))
        MelodieOffset += 20 #Melodie Eintrag is 20 bytes lang (eig 32 aber wir machens anders)
    
    
    
    # 2. Akkorde
    
    
    print("-- 🎹 Chords 🎹 --")
    
    #print("Total: " + str(len(trigger_events)))
    trigger_events.append((last_tick, 0)) #Füge letzten Tick als Fake Note hinzu, da wir nur Abstand zwischen NoteOn Events checken und wir so verhindern dass letzter Bereich ignoriert wird!
    #print(len(trigger_events))
    
    Chordcounters = 0
    
    for i in range(len(trigger_events)- 1):
        start_tick, trigger_note = trigger_events[i]
        end_tick, _ = trigger_events[i + 1]
            
        notes_in_range = [(t, n) for t, n in upper_octave_events if start_tick <= t < end_tick]
        print(f"\n{Chordcounters+1}. Chord (tick {start_tick} - {end_tick}):"
        f"\n   Bass Note {get_note_name(trigger_note, True)}")
        
        # print(Chordcounters)
        # print(CITBassnotes_ByteList[Chordcounters])
        
        CIToutput += bytes([CITBassnotes_ByteList[Chordcounters]])          ##Bassnote hinzufügen
        Chordcounters += 1 #welchen eintrag in der Bassnotesliste nehmen
        
        if notes_in_range:
            # print("Testotesto")
            # print()
            RestNoten = 7 # zum Füllen der restlichen Noten mit 7F (keine Note)
           
            for t, n in notes_in_range:
                RestNoten -= 1
                #print(f"   -Tick {t}: Note {get_note_name(n)}")
                print(f"   Note {get_note_name(n, True)}")
                CIToutput += bytes([get_note_byte(n)])                    ##Akkordnoten hinzufügen
            
            if not RestNoten == 0:                                         ##restplatz mit 7f füllen
                for nix in range(RestNoten):
                    CIToutput += bytes([0x7F])   
                
        else:
            print("   ⚠️ No chord note found!")


    # 3. Melodien
    print("\n-- 🎼 Musical Scales 🎼 --")
    
    MelodieWeitererOffset = len(CIToutput)
    MelodieWeitererOffset += 8
    
 
    
    for i in range(len(trigger_events) - 1):
        start_tick, trigger_note = trigger_events[i]
        end_tick, _ = trigger_events[i + 1]

        notes_in_range = [(t, n) for t, n in melodie_octave_events if start_tick <= t < end_tick]
        #print(f"\nZwischen Trigger bei Tick {start_tick} ({get_note_name(trigger_note)}) und Tick {end_tick}:")
        print(f"\n{i+1}. Musical Scale (Tick {start_tick} - {end_tick}, Bass Note {get_note_name(trigger_note, True)}):")
        
        CIToutput += bytes(MelodieWeitererOffset.to_bytes(4, byteorder='big')) ##Indiv. offset bla reinschreiben
        CIToutput += bytes(MelodieWeitererOffset.to_bytes(4, byteorder='big')) ##''
        MelodieWeitererOffset += 20 #Eintrag is 20 bytes lang
        
        
        if notes_in_range:
            RestNoten = 12 # zum Füllen der restlichen Noten mit 7F (keine Note)
            for t, n in notes_in_range:
                RestNoten -= 1
                #print(f"   Note {get_note_name(n, True)} (Tick {t})")
                print(f"   Note {get_note_name(n, True)}")
                CIToutput += bytes([get_note_byte(n)])                          ## Melodienoten hinzufügen
                
            if not RestNoten == 0:                                         ##restplatz mit 7f füllen
                for nix in range(RestNoten):
                    CIToutput += bytes([0x7F])  
        else:
            print("   ⚠️ No musical scale notes found!")




    # 4. Filesize
    CITfilesize = len(CIToutput)
    CIToutput[8:12] = bytes(CITfilesize.to_bytes(4, byteorder='big'))           #Filesize einfügen


    # 5. print Info for Multi MBGM Sheet
    print()
    print()
    if LoopAtAll == True:
        print("✏️ Enter these into the MultiBgmInfo sheet:")
        print("-IntoBeat: " + str(int(IntoBeat)))
        print("-LoopBeat: " + str(int(LoopBeat)))
        print("-Ratio: 1.0") #was macht das??
        print()
        if IntoBeatFullNumber == False:
            print("⚠️ Warning! The loop does not start exactly on the beat!")
            print("Set the LoopStart marker so that it matches the beat! (Every 120th tick)")


        elif LoopBeatFullNumber == False:
            print("⚠️ Warning! The loop does not end exactly on the beat!")
            print("Set the LoopEnd marker so that it matches the beat! (Every 120th tick)")
    else:
        print("❕No loop set in the midi.")
        print("This may be necessary if you use a MBGM with a streamed AST song that loops.")
        print()
        print("If intended, add this to the MultiBgmInfo sheet:")
        print("-IntoBeat: 0")
        print("-LoopBeat: 0")
        print("-Ratio: 1.0")
        print()
        print("If your song does not use an additional AST stream, you do not need to do anything else.")
        print()
        

    print()
    print()
    print("------------------------------------") #ist halt übersichtlicher, ne?


    return output, CIToutput, C3Taktblock



def MIDICHANNEL_to_BMSDATA(midifile, target_channel, Loop, ppqn_target=120):
    mid = mido.MidiFile(midifile)
    ppqn_original = mid.ticks_per_beat
    ppqn_scale = ppqn_target / ppqn_original

    events = []
    abs_time = 0

                    
    for track in mid.tracks:
        time_acc_real = 0.0 # float für exakte ppqn umrechnung
        time_acc = 0
        for msg in track:
            #scaled_time = int(round(msg.time * ppqn_scale)) # PPQN
            #time_acc += scaled_time
            time_acc_real += msg.time * ppqn_scale
            time_acc = int(round(time_acc_real))

            #Marker für LoopStart und LoopEnd aufspüren
            if msg.type == 'marker':
                if msg.text == 'LoopStart':
                    events.append((time_acc, 'LoopStart'))
                elif msg.text == 'LoopEnd':
                    events.append((time_acc, 'LoopEnd'))
                continue

            # Checken: Ist die Message relevant für uns?
            if msg.type == 'control_change' and msg.control == 0:
                # Immer merken,auch außerhalb target_channel!
                events.append((time_acc, msg))
            
            # Den ganzen Stuff in events speichern
            elif msg.type in ['note_on', 'note_off', 'control_change', 'program_change', 'pitchwheel']:
                if hasattr(msg, 'channel') and msg.channel == target_channel:
                    events.append((time_acc, msg))

    # Events nach Zeit sortieren
    events.sort(key=lambda e: e[0])

    # Events nach Zeitstempel Gruppieren
    grouped_events = defaultdict(list)
    for time, msg in events:
        grouped_events[time].append(msg)

    current_time = 0
    output = bytearray()
    note_stack = {}
    last_bank = None

    for timestamp in sorted(grouped_events.keys()):
        delta = timestamp - current_time
        current_time = timestamp

        # Falls Wartezeit bis zu diesem Zeitpunkt: schreibe Delay
        if delta > 0:
            output += bytes([0xF0] + ENCODE_VLQ(delta))

        for msg in grouped_events[timestamp]:
        
            ## LOOP STUFF ##
            if isinstance(msg, str):
                if Loop == True:
                    if msg == 'LoopStart':
                        output += bytes([0x77, 0x77, 0x77, 0x01]) #Platzhalter Loop Start
                    elif msg == 'LoopEnd':
                        output += bytes([0x77, 0x77, 0x77, 0x02]) #Platzhalter Loop Ende
        
            elif isinstance(msg, mido.Message):
            
                ## NOTES ##
                if msg.type == 'note_on' and msg.velocity > 0:
                    voice = assign_voice(msg.note, target_channel)
                    if LinearToLogarithmic == True:
                        velocity = LogarithmicCalculate(msg.velocity)
                    output += bytes([
                        msg.note & 0xFF,
                        voice & 0xFF,
                        msg.velocity & 0xFF
                    ])

                elif msg.type in ['note_off', 'note_on'] and msg.velocity == 0:
                    if msg.note in note_to_voice:
                        voice = release_voice(msg.note)
                        if voice is not None:
                            output += bytes([0x80 | (voice & 0x0F)])  # 81-87 (1-7), Bis zu 7 Voices möglich

                
                ## Midievents ##
                
                elif msg.type == 'control_change':
                    # Bank Select MSB
                    if msg.control == 0:            
                        last_bank = msg.value #Note down for later use
                        #print(last_bank)#test
                    # Bank Select LSB
                    elif msg.control == 32:         
                        last_bank = msg.value #Note down for later use
                        #print(last_bank)#test
                    elif msg.channel == target_channel:
                        # Channel Volume
                        if msg.control == 7:        
                            if LinearToLogarithmic == True:
                                volume = LogarithmicCalculate(msg.value)
                            output += bytes([0xB8, 0x00, msg.value & 0xFF])
                        # Pan
                        elif msg.control == 10:     
                            output += bytes([0xB8, 0x03, msg.value & 0xFF])
                        # Reverb
                        elif msg.control == 91:     
                            output += bytes([0xB8, 0x02, msg.value & 0xFF])
                        # Vibrato Strenght
                        elif msg.control == 1:     
                            output += bytes([0xD8, 0x6E, 0x00, msg.value & 0xFF])
                        # Vibrato Rate (if strenght is used but not this event, it will be auto set to 50%)
                        elif msg.control == 2:     
                            output += bytes([0xD8, 0x71, 0x00, msg.value & 0xFF])
                        # Tremollo Strenght
                        elif msg.control == 92:     
                            output += bytes([0xD8, 0x70, 0x00, msg.value & 0xFF])
                        # Tremollo Rate (if strenght is used but not this event, it will be auto set to 50%)
                        elif msg.control == 93:     
                            output += bytes([0xD8, 0x72, 0x00, msg.value & 0xFF])

                
                # Patch and Bank Stuff #
                elif msg.type == 'program_change':
                    if last_bank is not None:
                        output += bytes([0xE1, last_bank & 0xFF, msg.program & 0xFF]) #E1 command (combines patch and bank select) # Note: BMS_DEC tool has problems with that
                        last_bank = None
                    else:
                        output += bytes([0xE3, msg.program & 0xFF]) # E3 command: Only for patch change 
            
            
            
                # Pitch Wheel #
                elif msg.type == 'pitchwheel': #and msg.channel == target_channel:
                    #Umrechnen: durch 8 teilen
                    pitch_value = msg.pitch >> 3  # Int-Division durch 8, inklusive Vorzeichen
                    pitch_bytes = pitch_value.to_bytes(1, byteorder='big', signed=True)
                    output += bytes([0xB8, 0x01]) + pitch_bytes
            ## TODO: E2 command for only changing bank ?
            
    output += bytes([0xFF]) #Ende. Überhaupt notwendig, wenns loopt?
    return output



## HAUPTACTION ##
def START(midifile, Output_BMS, LinearToLogarithmic=False, PPQNtargetValue=120):
    with open(Output_BMS, "w+b") as f:
        
        # Infos sammeln
        mid = mido.MidiFile(midifile)
        ppqn = mid.ticks_per_beat
        ppqn_hex = f"{ppqn:02X}"
        print(f"PPQN: {ppqn} (Hex:{ppqn_hex})")
        ppqn_bytes = ppqn.to_bytes(2, byteorder='big') #Value zu Hex umwandeln
        target_ppqn = PPQNtargetValue
        PPQNoriginal = mid.ticks_per_beat
        ppqn_original = PPQNoriginal
        
        AllTicks = (Get_Last_Note_Tick(midifile))                        # Anzahl aller Ticks merken ()
        AllTicks_inVLQ = bytes(ENCODE_VLQ(Get_Last_Note_Tick(midifile))) # und in VLQ umwandeln
        
        ##### ----- START WRITING ------ ######
        
        ## --- 1. Überkanal: Tempospur --- ##
        #(auch zum Festlegen von hauptinfos, children-kanäle)
        #(Läuft aber quasi paralell zu den Tracks wie Tempospur bei Midis: Für BPM Änderungen während des Songs.)
        
        f.write(b"\xC1\x00")                    # Hauptkanal/Tempospur (für Settings wie BPM) start
        POS_PointerToMainChannels = f.tell()    # Position merken für später, um 777 da unten zu ersetzen:
        f.write(b"\x77\x77\x77")                # 77 Platzhalter. später mit pointer zum ersten Kanalersteller ersetzen!
        
        f.write(b"\xD8\x62")                    # PPQN start

        #f.write(ppqn_bytes)                     # PPQN Value einfügen
        f.write(b"\x00\x78")                    #NE: Wir wandeln in dieser Version erstmal nur zu 120


        

        
        
        ## ---Loop Check--- ##
        # Checken ob es loopen soll
        loop_start_tick = Find_Marker_Position(midifile, "LoopStart") # Nach Loop Marker in Midi suchen
        if loop_start_tick is not None:
            loop_start_tick_scaled = int(loop_start_tick * (target_ppqn / ppqn_original))
            print(f"LOOP: Loop Start at Tick: {loop_start_tick}")
            Loop = True
        else:
            Loop = False
            LoopAllCommand = Find_Marker_Position(midifile, "LoopAll") # Nach LoopAll Marker in Midi suchen
            if LoopAllCommand is None:
                LoopAll = False
                print("LOOP: Do not loop")
            else:
                LoopAll = True
                print("LOOP: Entire Song")
                
        ## ---LinearToLogarithmic Check--- ##
        if LinearToLogarithmic == True:
            print("Volumes will be converted from linear to logarithmic.")
        
        ## ---Timing Channel Check--- ##
        TaktMarker = Find_Marker_Position(midifile, "BEAT_4/4") # Nach Beat Marker in Midi suchen
        if TaktMarker is not None:
            TimingChannel = True
            Takt = 0
        else:
            TaktMarker = Find_Marker_Position(midifile, "BEAT_3/4")
            if TaktMarker is not None:
                TimingChannel = True
                Takt = 1
            else:
                TimingChannel = False
        
        ## ---Global Midievents ("Tempotrack")--- ##
        output = GLOBALMIDIEVENTS_to_BMSDATA(midifile, AllTicks, Loop)
        f.write(output)
        
        # LOOP (for global Midievents) #
        if Loop == True:
            f.seek(0)  # Zum Anfang zurückspringen
            data = f.read() # um dann die gesamte Datei in Variable data zu saven
            loop_start_marker = b'\x77\x77\x77\x01' 
            loop_end_marker   = b'\x77\x77\x77\x02'
            
            # Loop-Start dann in data suchen
            start_index = data.find(loop_start_marker)
            end_index   = data.find(loop_end_marker)
                
            if start_index != -1 and end_index != -1:
                # 1.Zieladresse berechnen -> wo der Loop wieder hinspringen soll
                goto_address = start_index
                goto_bytes = bytes([0xC7]) + goto_address.to_bytes(3, byteorder='big')

                # 2.Loop Start Marker löschen
                f.seek(start_index)
                f.write(b'\xF0\x00\xF0\x00')  # oder einfach leer überschreiben ? python ist da echt fies TODO for next Update: Diese 4 Bytes Löschen!

                # 3.Loop End Marker durch C7 + Adresse ersetzen
                f.seek(end_index)
                f.write(goto_bytes)
                
                # 4.Zurück zum Ende der File hüpfen, damit alles normalo weitergeht
                f.seek(0, 2)
                
            f.seek(0, 2) # fail safe
            
        else:
            if LoopAll == True:
                f.write(b"\xC7\x00\x00\x00")    #Springe einfach zurück zum Parentkanal fürn simplen Restart (NUR FÜR HAUPTKANAL)
            else:
                f.write(b"\xFF")                #beendet alles!
        
        

            

        ## ---- 2. Kanalersteller erstellen ---- ##
        
        
        PointerToChannelCreators = f.tell() #Position merken, um später beim Hauptkanal einzufügen (7777)
        channels = Get_UsedChannels(midifile) #Anzahl und IDs der Kanäle kriegen
        channel_bytes = bytes(channels)  # Jeder Channel als 1 Byte
        print()
        print("Convert Channels:")
        
        for chID in channel_bytes: 
            f.write(b"\xC1")                        # OpCode identifier
            print(str(chID))
            f.write(struct.pack(">B", chID))        # Kanal ID.  Deci, also Kanal 1 = 0 !!
        
            # Kanalerstelladressen merken, um später Pointer einzufügen:
            if chID == 0:
                ChannelCreatorPointerCH0 = f.tell()
            if chID == 1:
                ChannelCreatorPointerCH1 = f.tell()
            if chID == 2:
                ChannelCreatorPointerCH2 = f.tell()
            if chID == 3:
                ChannelCreatorPointerCH3 = f.tell()
            if chID == 4:
                ChannelCreatorPointerCH4 = f.tell()
            if chID == 5:
                ChannelCreatorPointerCH5 = f.tell()
            if chID == 6:
                ChannelCreatorPointerCH6 = f.tell()
            if chID == 7:
                ChannelCreatorPointerCH7 = f.tell()
            if chID == 8:
                ChannelCreatorPointerCH8 = f.tell()
            if chID == 9:
                ChannelCreatorPointerCH9 = f.tell()
            if chID == 10:
                ChannelCreatorPointerCH10 = f.tell()
            if chID == 11:
                ChannelCreatorPointerCH11 = f.tell()
            if chID == 12:
                ChannelCreatorPointerCH12 = f.tell()
            if chID == 13:
                ChannelCreatorPointerCH13 = f.tell()
            if chID == 14:
                ChannelCreatorPointerCH14 = f.tell()
            if chID == 15:
                ChannelCreatorPointerCH15 = f.tell()
            
            f.write(b"\x88\x88\x88")        # Platzhalter-Pointer zu Notendata
        
        
        # --- LOOP [ChannelCreator-Section] (for global Midievents) --- #
        
        # Loop Stuff für Kanalersteller (so wie Hauptkanalstuff läufts auch parallel zu den Tracks, aber wen juckts hier??)
        # MUSS GENAU GLEICH WIE BEIM KANALERSTELLER SEIN (sonst buggst) !!
        
        
        ChannelCreator_GlobalEventsStartAdress = f.tell()
        output = GLOBALMIDIEVENTS_to_BMSDATA(midifile, AllTicks, Loop)
        f.write(output)
        
        ## LOOP ##
        if Loop == True:
            f.seek(0)  # Zum Anfang zurückspringen
            data = f.read() # um dann die gesamte Datei in Variable data zu saven
            loop_start_marker = b'\x77\x77\x77\x01' 
            loop_end_marker   = b'\x77\x77\x77\x02'
            
            # Loop-Start dann in data suchen
            start_index = data.find(loop_start_marker)
            end_index   = data.find(loop_end_marker)
                
            if start_index != -1 and end_index != -1:
                # 1.Zieladresse berechnen -> wo der Loop wieder hinspringen soll
                goto_address = start_index
                goto_bytes = bytes([0xC7]) + goto_address.to_bytes(3, byteorder='big')

                # 2.Loop Start Marker löschen
                f.seek(start_index)
                f.write(b'\xF0\x00\xF0\x00')  # oder einfach leer überschreiben ? python ist da echt fies TODO for next Update: Diese 4 Bytes Löschen!

                # 3.Loop End Marker durch C7 + Adresse ersetzen
                f.seek(end_index)
                f.write(goto_bytes)
                
                # 4.Zurück zum Ende der File hüpfen, damit alles normalo weitergeht
                f.seek(0, 2)
            f.seek(0, 2) # fail save
            
        else:
            if LoopAll == True:
                f.write(b"\xC7")
                f.write(ChannelCreator_GlobalEventsStartAdress.to_bytes(3, byteorder='big')) #Springe zurück zum Start (?)
            else:
                f.write(b"\xFF")                #beendet alles!
        
            
            
            
        ## 3. ---- Noten und Events ------ ##
        for chID in channels:
            #ChannelpointerCH + chID = f.tell() #geht net....
            # Kanalpointer notieren:
            if chID == 0:
                ChannelpointerCH0 = f.tell()
            if chID == 1:
                ChannelpointerCH1 = f.tell()
            if chID == 2:
                ChannelpointerCH2 = f.tell()
            if chID == 3:
                ChannelpointerCH3 = f.tell()
            if chID == 4:
                ChannelpointerCH4 = f.tell()
            if chID == 5:
                ChannelpointerCH5 = f.tell()
            if chID == 6:
                ChannelpointerCH6 = f.tell()
            if chID == 7:
                ChannelpointerCH7 = f.tell()
            if chID == 8:
                ChannelpointerCH8 = f.tell()
            if chID == 9:
                ChannelpointerCH9 = f.tell()
            if chID == 10:
                ChannelpointerCH10 = f.tell()
            if chID == 11:
                ChannelpointerCH11 = f.tell()
            if chID == 12:
                ChannelpointerCH12 = f.tell()
            if chID == 13:
                ChannelpointerCH13 = f.tell()
            if chID == 14:
                ChannelpointerCH14 = f.tell()
            if chID == 15:
                ChannelpointerCH15 = f.tell()
            
            ### --- Schreibe Noten und Events in Datei ---
            
            ## Timing and Chord Channel ##
            if TimingChannel == True and chID == 0:
                print()
                print("Timing Channel included. ")# + str(chID))
                output, CIToutput, C3Taktblock = MIDICHANNEL_to_TIMINGandCHORD(midifile, chID, Takt, Loop)
                
                # ---- C3 Goto Stuff ----
                if not C3Taktblock == None:
                    SizeOfFileCurrent = f.tell()
                    outputSize = len(output)
                    C3GotoAdress = SizeOfFileCurrent + outputSize + 1 #die 1 wegen der kommenden FF Abgrenzung

                    output = output.replace(b'\xC3\x77\x88\x99', b'\xC3' + (C3GotoAdress.to_bytes(3, byteorder='big'))     )
                    f.write(output)
                    f.write(b"\xFF") ##überhaupt notwendig?
                    f.write(C3Taktblock)
                    f.write(b"\xFF")
            else:
                output = MIDICHANNEL_to_BMSDATA(midifile, chID, Loop)
            f.write(output)
            
            ## ---- LOOP ---- ##
            f.seek(0)  # Zum Anfang zurückspringen
            data = f.read() # um dann die gesamte Datei in Variable data zu saven
            loop_start_marker = b'\x77\x77\x77\x01' 
            loop_end_marker   = b'\x77\x77\x77\x02'
            
            # Loop-Start dann in data suchen
            start_index = data.find(loop_start_marker)
            end_index   = data.find(loop_end_marker)
                
            if start_index != -1 and end_index != -1:

                # 1.Zieladresse berechnen -> wo der Loop wieder hinspringen soll
                goto_address = start_index
                goto_bytes = bytes([0xC7]) + goto_address.to_bytes(3, byteorder='big')
                #print(goto_bytes)
                # 2.Loop Start Marker löschen
                f.seek(start_index)
                f.write(b'\xF0\x00\xF0\x00')  # oder einfach leer überschreiben ? python ist da echt fies TODO for next Update: Diese 4 Bytes Löschen!

                # 3.Loop End Marker durch C7 + Adresse ersetzen
                f.seek(end_index)
                f.write(goto_bytes)
                
                # 4.Zurück zum Ende der File hüpfen, damit alles normalo weitergeht
                f.seek(0, 2)
        
            ##DOPPELTEST:
            ## ---- LOOP ---- ##
            f.seek(0)  # Zum Anfang zurückspringen
            data = f.read() # um dann die gesamte Datei in Variable data zu saven
            loop_start_marker = b'\x77\x77\x77\x01' 
            loop_end_marker   = b'\x77\x77\x77\x02'
            
            # Loop-Start dann in data suchen
            start_index = data.find(loop_start_marker)
            end_index   = data.find(loop_end_marker)
                
            if start_index != -1 and end_index != -1:

                # 1.Zieladresse berechnen -> wo der Loop wieder hinspringen soll
                goto_address = start_index
                goto_bytes = bytes([0xC7]) + goto_address.to_bytes(3, byteorder='big')
                #print(goto_bytes)
                # 2.Loop Start Marker löschen
                f.seek(start_index)
                f.write(b'\xF0\x00\xF0\x00')  # oder einfach leer überschreiben ? python ist da echt fies TODO for next Update: Diese 4 Bytes Löschen!

                # 3.Loop End Marker durch C7 + Adresse ersetzen
                f.seek(end_index)
                f.write(goto_bytes)
                
                # 4.Zurück zum Ende der File hüpfen, damit alles normalo weitergeht
                f.seek(0, 2)
        
        
        
        ## Pointer bei den Kanalerstellern einfügen
        for chID in channels:
            if chID == 0:
                f.seek(ChannelCreatorPointerCH0) # Gehe zu diesen Offset
                #f.write(struct.pack(">iii", ChannelpointerCH0))
                f.write(ChannelpointerCH0.to_bytes(3, byteorder='big'))
            if chID == 1:
                f.seek(ChannelCreatorPointerCH1)
                f.write(ChannelpointerCH1.to_bytes(3, byteorder='big'))
            if chID == 2:
                f.seek(ChannelCreatorPointerCH2)
                f.write(ChannelpointerCH2.to_bytes(3, byteorder='big'))
            if chID == 3:
                f.seek(ChannelCreatorPointerCH3)
                f.write(ChannelpointerCH3.to_bytes(3, byteorder='big'))
            if chID == 4:
                f.seek(ChannelCreatorPointerCH4)
                f.write(ChannelpointerCH4.to_bytes(3, byteorder='big'))
            if chID == 5:
                f.seek(ChannelCreatorPointerCH5)
                f.write(ChannelpointerCH5.to_bytes(3, byteorder='big'))
            if chID == 6:
                f.seek(ChannelCreatorPointerCH6)
                f.write(ChannelpointerCH6.to_bytes(3, byteorder='big'))
            if chID == 7:
                f.seek(ChannelCreatorPointerCH7)
                f.write(ChannelpointerCH7.to_bytes(3, byteorder='big'))
            if chID == 8:
                f.seek(ChannelCreatorPointerCH8)
                f.write(ChannelpointerCH8.to_bytes(3, byteorder='big'))
            if chID == 9:
                f.seek(ChannelCreatorPointerCH9)
                f.write(ChannelpointerCH9.to_bytes(3, byteorder='big'))
            if chID == 10:
                f.seek(ChannelCreatorPointerCH10)
                f.write(ChannelpointerCH10.to_bytes(3, byteorder='big'))
            if chID == 11:
                f.seek(ChannelCreatorPointerCH11)
                f.write(ChannelpointerCH11.to_bytes(3, byteorder='big'))
            if chID == 12:
                f.seek(ChannelCreatorPointerCH12)
                f.write(ChannelpointerCH12.to_bytes(3, byteorder='big'))
            if chID == 13:
                f.seek(ChannelCreatorPointerCH13)
                f.write(ChannelpointerCH13.to_bytes(3, byteorder='big'))
            if chID == 14:
                f.seek(ChannelCreatorPointerCH14)
                f.write(ChannelpointerCH14.to_bytes(3, byteorder='big'))
            if chID == 15:
                f.seek(ChannelCreatorPointerCH15)
                f.write(ChannelpointerCH15.to_bytes(3, byteorder='big'))
        
        ## Enter Pointer to Main child Channels on Parent Channel 
        f.seek(POS_PointerToMainChannels)
        f.write(PointerToChannelCreators.to_bytes(3, byteorder='big'))
        
        
        
        ## Write CIT File ##
        if TimingChannel > 0:
            with open(Output_BMS + ".cit", "wb") as CIT:
                # Write bytes to file
                CIT.write(CIToutput)
        


### Command line stuff
if __name__ == "__main__":
    Input_MIDI = sys.argv[1]
    Output_BMS = sys.argv[2]
    LinearToLogarithmic = sys.argv[3]
    
    print("--- 🎵 Midi to BMS v.0.9.7.5 🎶 ---") # to check Version
    print()
    START(Input_MIDI, Output_BMS, LinearToLogarithmic)#TimingChannel=None, LinearToLogarithmic=False, PPQNtargetValue=120)
    print()
    print("✅ Done!")
    print()
    print()
    print()
