' ============================================================
'  Αρχείο Αποδείξεων — εκκίνηση χωρίς παράθυρο κονσόλας
'  Κάντε διπλό κλικ εδώ για να ανοίξετε την εφαρμογή.
' ============================================================
Dim fso, shell, here, pyw, appPath
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = fso.BuildPath(here, ".venv\Scripts\pythonw.exe")
appPath = fso.BuildPath(here, "app.py")

If Not fso.FileExists(pyw) Then
  MsgBox "Δεν βρέθηκε το περιβάλλον Python (.venv)." & vbCrLf & _
         "Εκτελέστε πρώτα το αρχείο 'Εγκατάσταση.bat'.", vbCritical, "Αρχείο Αποδείξεων"
  WScript.Quit
End If

shell.CurrentDirectory = here
shell.Run """" & pyw & """ """ & appPath & """", 0, False
