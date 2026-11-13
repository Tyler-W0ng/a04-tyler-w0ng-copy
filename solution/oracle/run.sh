#!/bin/sh
# Oracle for R6: a request may be cancelled only while PENDING or APPROVED.
#
# Available balances plus days held in PENDING/APPROVED requests are conserved.
# Cancelling a terminal request creates extra days without releasing a reserve.
# Include reserves so other requests cannot hide even a one-day violation.
DB="${DB_PATH:-/data/app.db}"

python3 - "$DB" <<'PY'
import sqlite3
import sys

db = sqlite3.connect(sys.argv[1])
current, seeded = db.execute(
    "SELECT COALESCE(SUM(balance), 0), COALESCE(SUM(initial_balance), 0)"
    " FROM accounts WHERE role = 'employee'"
).fetchone()

reserved = db.execute(
    "SELECT COALESCE(SUM(days), 0) FROM requests"
    " WHERE state IN ('PENDING', 'APPROVED')"
).fetchone()[0]

if current + reserved > seeded:
    print("VIOLATED R6")
else:
    print("OK")
PY
