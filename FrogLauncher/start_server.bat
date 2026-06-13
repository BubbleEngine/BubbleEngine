@echo off

:: resolve python 3.10 path
for /f "delims=" %%i in ('..\python\python.exe ..\path\resolver.py python') do set PYTHON_DIR=%%i
set PYTHON=%PYTHON_DIR%\python.exe

:: install deps if missing
%PYTHON% -c "import fastapi" 2>nul || %PYTHON% -m pip install fastapi
%PYTHON% -c "import uvicorn" 2>nul || %PYTHON% -m pip install uvicorn
%PYTHON% -c "import httpx"   2>nul || %PYTHON% -m pip install httpx

:: run server (Ctrl+C here kills it cleanly since it's in the same console)
%PYTHON% "%~dp0server.py"
