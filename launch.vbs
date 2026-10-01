Dim path
path = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
CreateObject("WScript.Shell").Run "cmd /c cd /d """ & path & """ && py main.py", 0, False
