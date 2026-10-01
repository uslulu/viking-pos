' Launches updater.py (checks for updates, then starts main.py itself).
' Uses 'py' in a hidden window (style 0) instead of pythonw:
' pythonw from Microsoft Store Python is unreliable.
' Keep this file ASCII-only: wscript reads it in the ANSI code page.
Option Explicit
Dim sh, fso, path, script
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
path = fso.GetParentFolderName(WScript.ScriptFullName)
script = "updater.py"
If Not fso.FileExists(path & "\updater.py") Then script = "main.py"
sh.CurrentDirectory = path
sh.Run "cmd /c cd /d """ & path & """ && py " & script, 0, False
