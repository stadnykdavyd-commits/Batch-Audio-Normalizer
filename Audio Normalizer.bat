@echo off
rem Drag a folder (or audio file) onto this file, or double-click to pick a folder.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\run.ps1" %*
