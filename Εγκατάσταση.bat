@echo off
chcp 65001 >nul
title Εγκατάσταση - Αρχείο Αποδείξεων
echo.
echo ============================================================
echo   Αρχείο Αποδείξεων - Εγκατάσταση
echo ============================================================
echo.
echo Δημιουργία περιβάλλοντος και εγκατάσταση προγραμμάτων...
echo (Χρειάζεται μόνο την πρώτη φορά - μπορεί να πάρει 1-2 λεπτά)
echo.

cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo [ΣΦΑΛΜΑ] Δεν βρέθηκε η Python. Εγκαταστήστε την από https://www.python.org/downloads/
  echo και επιλέξτε "Add Python to PATH" κατά την εγκατάσταση.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo.
echo ============================================================
echo   Έτοιμο! Ανοίξτε την εφαρμογή με διπλό κλικ στο
echo   "Άνοιγμα Αρχείου.vbs"
echo ============================================================
echo.
pause
