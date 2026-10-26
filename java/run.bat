@echo off
REM =============================================================
REM run.bat – Build and run Innov8 Java JDBC Report Tool (Windows)
REM =============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

REM Check for Java compiler
where javac >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] 'javac' (Java compiler) was not found in PATH.
    echo Please install JDK 8 or higher from https://adoptium.net/
    exit /b 1
)

REM Check for sqlite-jdbc driver
if not exist "lib\sqlite-jdbc.jar" (
    echo [INFO] Downloading sqlite-jdbc driver jar...
    mkdir lib >nul 2>&1
    powershell -Command "Invoke-WebRequest -Uri 'https://repo1.maven.org/maven2/org/xerial/sqlite-jdbc/3.45.2.0/sqlite-jdbc-3.45.2.0.jar' -OutFile 'lib\sqlite-jdbc.jar'"
)

echo [1/2] Compiling ReportTool.java...
javac -cp "lib\*;." ReportTool.java
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Compilation failed.
    exit /b %ERRORLEVEL%
)

echo [2/2] Running ReportTool...
set GROUP_ID=%1
if "%GROUP_ID%"=="" set GROUP_ID=1

java -cp "lib\*;." ReportTool %GROUP_ID% "..\backend\innov8.db"
