' HeadStart launcher: (re)starts the server in the background and opens the
' browser. No terminal window. A server already running is stopped first, so
' clicking the launcher always runs the latest code.
Option Explicit
Dim sh, fso, dir, url, i
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
url = "http://localhost:5000"

Function IsUp()
    Dim http
    IsUp = False
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP")
    http.setTimeouts 500, 500, 1000, 1000
    http.Open "GET", url, False
    http.Send
    If Err.Number = 0 Then IsUp = (http.Status = 200)
    On Error GoTo 0
End Function

If IsUp() Then
    sh.Run "cmd /c for /f ""tokens=5"" %p in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do taskkill /F /PID %p", 0, True
    For i = 1 To 20
        If Not IsUp() Then Exit For
        WScript.Sleep 250
    Next
End If

If Not IsUp() Then
    If Not fso.FolderExists(dir & "\out") Then fso.CreateFolder dir & "\out"
    sh.CurrentDirectory = dir
    sh.Run "cmd /c "".venv\Scripts\python.exe"" app.py > out\server.log 2>&1", 0, False
    For i = 1 To 40
        WScript.Sleep 500
        If IsUp() Then Exit For
    Next
End If

sh.Run url
