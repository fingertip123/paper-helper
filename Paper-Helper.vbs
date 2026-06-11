' Paper-Helper 统一入口（Windows，无控制台窗口）
Option Explicit
Dim sh, fso, root, py, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root
sh.Environment("PROCESS")("PAPER_HELPER_GUI") = "1"
py = FindPythonw()
If py = "" Then
  MsgBox "未找到 Python。" & vbCrLf & "请安装 Python 3 并勾选 Add to PATH。" & vbCrLf & "https://www.python.org/downloads/", vbCritical, "Paper-Helper"
  WScript.Quit 1
End If
If LCase(py) = "pyw" Or LCase(py) = "pyw.exe" Then
  cmd = "pyw -3 tools/entry.py"
Else
  cmd =  & py &  & " tools/entry.py"
End If
sh.Run cmd, 0, False

Function FindPythonw()
  Dim wsh, proc, line, candidates, c
  candidates = Array("pythonw.exe", "pyw.exe")
  For Each c In candidates
    On Error Resume Next
    Set wsh = sh.Exec("where " & c)
    If Err.Number = 0 Then
      Do While wsh.Status = 0
        WScript.Sleep 50
      Loop
      line = Trim(wsh.StdOut.ReadLine())
      If line <> "" Then
        FindPythonw = line
        Exit Function
      End If
    End If
    On Error GoTo 0
  Next
  ' py 启动器：尝试 py -3 对应的 pythonw
  On Error Resume Next
  Set wsh = sh.Exec("where py")
  If Err.Number = 0 Then
    Do While wsh.Status = 0
      WScript.Sleep 50
    Loop
    If Trim(wsh.StdOut.ReadLine()) <> "" Then
      FindPythonw = "pyw"
      Exit Function
    End If
  End If
  On Error GoTo 0
  FindPythonw = ""
End Function
