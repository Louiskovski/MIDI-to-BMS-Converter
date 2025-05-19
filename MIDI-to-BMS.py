import sys
import mido
import os
import csv
#import pandas as pd
import math
from mido import MidiFile, MetaMessage
import struct
from collections import defaultdict


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
        raise RuntimeError("Error! Channel " + ChannelNum + " has more than 7 overlapping notes!")
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


def GLOBALMIDIEVENTS_to_BMSDATA(midifile, AllTicks, Loop, ppqn_target=120):
    mid = mido.MidiFile(midifile)
    ppqn_original = mid.ticks_per_beat
    ppqn_scale = ppqn_target / ppqn_original

    events = []
    
    for track in mid.tracks:
        abs_time = 0
        for msg in track:
            scaled_time = int(round(msg.time * ppqn_scale))
            abs_time += scaled_time

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



def MIDITRACK_to_BMSDATA(midifile, target_channel, Loop, ppqn_target=120):
    mid = mido.MidiFile(midifile)
    ppqn_original = mid.ticks_per_beat
    ppqn_scale = ppqn_target / ppqn_original

    events = []
    abs_time = 0

                    
    for track in mid.tracks:
        time_acc = 0
        for msg in track:
            scaled_time = int(round(msg.time * ppqn_scale)) # PPQN
            time_acc += scaled_time

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
                    pitch_bytes = pitch_value.to_bytes(2, byteorder='big', signed=True)
                    output += bytes([0xB9, 0x01]) + pitch_bytes
            ## TODO: E2 command for only changing bank ?
            
    output += bytes([0xFF]) #Ende. Überhaupt notwendig, wenns loopt?
    return output



## HAUPTACTION ##
def START(midifile, Output_BMS, LinearToLogarithmic, PPQNtargetValue=120):
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
        
        ## --- 1. Überkanal und andere bla infos --- ##
        #(zum Festlegen von hauptinfos, children-kanäle)
        #(Läuft aber quasi paralell zu den Tracks: Für BPM Änderungen während des Songs?)
        
        f.write(b"\xC1\x00")                    # Hauptkanal (für Settings wie BPM) start
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
        
        ## ---Global Midievents--- ##
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
            output = MIDITRACK_to_BMSDATA(midifile, chID, Loop)
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
        
        # ##TEST##
        # f.seek(0, 2)
        # f.write(b"\x54\x45\x53\x54")
        # output = GLOBALMIDIEVENTS_to_BMSDATA(midifile, AllTicks, Loop)
        # f.write(output)


### Command line stuff
if __name__ == "__main__":
    Input_MIDI = sys.argv[1]
    Output_BMS = sys.argv[2]
    LinearToLogarithmic = sys.argv[3]
    
    print("--- Midi to BMS v.0.9 ---") # to check Version
    print()
    START(Input_MIDI, Output_BMS, LinearToLogarithmic)
    print()
    print("Done!")
    print()
    print()
    print()