@echo off
set Yaz0EncPath="C:\Tools\yaz0enc.exe"

python %~dp0MIDI-to-BMS.py "%~1" "%~1.bms" True

%Yaz0EncPath% "%~1.bms"

pause
