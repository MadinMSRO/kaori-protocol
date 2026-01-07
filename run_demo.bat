@echo off
echo ===========================================
echo Kaori Protocol - Quick Start Demo
echo ===========================================

echo.
echo [1/2] Installing Dependencies (if needed)...
pip install -r requirements.txt

echo.
echo [2/2] Running End-to-End Demo...
python tools/simulation_demo.py

echo.
pause
