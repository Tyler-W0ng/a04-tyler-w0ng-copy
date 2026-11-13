"""Run with Python inside Linux; verifies the oracle against state fixtures."""
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile


def check(name, balance, requests, expected):
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "state.db")
        with sqlite3.connect(path) as db:
            db.executescript(
                "CREATE TABLE accounts (role TEXT, balance INTEGER, initial_balance INTEGER);"
                "CREATE TABLE requests (days INTEGER, state TEXT);"
            )
            db.execute("INSERT INTO accounts VALUES ('employee', ?, 80)", (balance,))
            db.executemany("INSERT INTO requests VALUES (?, ?)", requests)
        result = subprocess.run(
            ["sh", str(Path(__file__).with_name("run.sh"))],
            env={**os.environ, "DB_PATH": path}, text=True, capture_output=True, check=True,
        )
        assert result.stdout.strip() == expected, (name, result.stdout, result.stderr)
        print(f"ORACLE {name} PASS")


check("fresh", 80, [], "OK")
check("pending-and-approved", 65, [(10, "PENDING"), (5, "APPROVED")], "OK")
check("legitimate-terminal", 80, [(1, "CANCELLED"), (5, "DENIED")], "OK")
check("repeat-cancel-hidden-by-reserve", 71,
      [(10, "PENDING"), (1, "CANCELLED")], "VIOLATED R6")
check("denied-then-cancelled", 76,
      [(5, "APPROVED"), (1, "CANCELLED")], "VIOLATED R6")
check("fabricated-days-reserved-again", 60,
      [(21, "PENDING"), (1, "CANCELLED")], "VIOLATED R6")
