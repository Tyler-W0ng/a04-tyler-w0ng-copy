#!/bin/sh
# Oracle for R6: a request may be cancelled only while PENDING or APPROVED.
#
# Every legitimate operation conserves or reduces the total leave held by
# employees: submitting reserves days, approving is neutral, denying and a
# legitimate cancel return exactly what was reserved, and a transfer moves days
# between employees. No legitimate workflow mints new days. So if the total of
# all current employee balances ever exceeds the total originally seeded, leave
# was created out of nothing, which here can only happen by cancelling a request
# that was not PENDING or APPROVED. The check reads the state directly and does
# not depend on how the extra cancellation was performed.
DB="${DB_PATH:-/data/app.db}"

python3 - "$DB" <<'PY'
import sqlite3
import sys

db = sqlite3.connect(sys.argv[1])
current, seeded = db.execute(
    "SELECT COALESCE(SUM(balance), 0), COALESCE(SUM(initial_balance), 0)"
    " FROM accounts WHERE role = 'employee'"
).fetchone()

if current > seeded:
    print("VIOLATED R6")
else:
    print("OK")
PY
