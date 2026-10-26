#!/usr/bin/env bash
# =============================================================
# run.sh – Build and run Innov8 Java JDBC Report Tool (macOS/Linux)
# =============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check for Java compiler
if ! command -v javac &> /dev/null; then
    # Check common Homebrew location on macOS
    if [ -x "/opt/homebrew/opt/openjdk/bin/javac" ]; then
        export PATH="/opt/homebrew/opt/openjdk/bin:$PATH"
    else
        echo "Error: 'javac' (Java Development Kit) not found."
        echo "Please install OpenJDK (e.g., 'brew install openjdk' or 'sudo apt install default-jdk')."
        exit 1
    fi
fi

# Ensure sqlite-jdbc driver exists
if [ ! -f "lib/sqlite-jdbc.jar" ]; then
    echo "Downloading sqlite-jdbc driver jar..."
    mkdir -p lib
    curl -sSL -o lib/sqlite-jdbc.jar "https://repo1.maven.org/maven2/org/xerial/sqlite-jdbc/3.45.2.0/sqlite-jdbc-3.45.2.0.jar"
fi

echo "[1/2] Compiling ReportTool.java..."
javac -cp "lib/*:." ReportTool.java

echo "[2/2] Running ReportTool..."
GROUP_ID="${1:-1}"
java -cp "lib/*:." ReportTool "$GROUP_ID" "../backend/innov8.db"
