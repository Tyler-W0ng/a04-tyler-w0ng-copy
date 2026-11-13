#!/usr/bin/env python3
"""Leave management service.

A small HTTP/JSON service that lets employees request paid time off and lets
managers review those requests for their team. State is kept in SQLite and
reseeded on every start.
"""
import json
import os
import re
import secrets
import sqlite3
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB_PATH = os.environ.get("DB_PATH", "/data/app.db")
PORT = int(os.environ.get("PORT", "8080"))

# username, password, role, team, balance
SEED_ACCOUNTS = [
    ("m_alice", "alice-pass", "manager", "engineering", 0),
    ("m_bob", "bob-pass", "manager", "sales", 0),
    ("e_carol", "carol-pass", "employee", "engineering", 20),
    ("e_dave", "dave-pass", "employee", "engineering", 20),
    ("e_erin", "erin-pass", "employee", "sales", 20),
    ("e_frank", "frank-pass", "employee", "sales", 20),
]

_lock = threading.Lock()
_db = None


def parse_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("expected YYYY-MM-DD")
    return date.fromisoformat(value)


def get_db():
    global _db
    if _db is None:
        _db = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db.row_factory = sqlite3.Row
    return _db


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    db = get_db()
    db.executescript(
        """
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            team TEXT NOT NULL,
            balance INTEGER NOT NULL,
            initial_balance INTEGER NOT NULL
        );
        CREATE TABLE requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days INTEGER NOT NULL,
            state TEXT NOT NULL
        );
        CREATE TABLE blocked_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            created_by INTEGER NOT NULL
        );
        CREATE TABLE sessions (
            token TEXT PRIMARY KEY,
            account_id INTEGER NOT NULL
        );
        """
    )
    for username, password, role, team, balance in SEED_ACCOUNTS:
        db.execute(
            "INSERT INTO accounts (username, password, role, team, balance, initial_balance)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (username, password, role, team, balance, balance),
        )
    db.commit()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    # --- helpers ---------------------------------------------------------

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
            return body if isinstance(body, dict) else None
        except Exception:
            return None

    def current_account(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        token = auth[7:]
        db = get_db()
        return db.execute(
            "SELECT a.* FROM sessions s JOIN accounts a ON a.id = s.account_id WHERE s.token = ?",
            (token,),
        ).fetchone()

    # --- auth ------------------------------------------------------------

    def handle_login(self):
        body = self.read_json()
        if body is None:
            return self.send_json(400, {"error": "invalid json"})
        db = get_db()
        row = db.execute(
            "SELECT * FROM accounts WHERE username = ?", (body.get("username"),)
        ).fetchone()
        if row is None or row["password"] != body.get("password"):
            return self.send_json(401, {"error": "invalid credentials"})
        token = secrets.token_hex(16)
        db.execute(
            "INSERT INTO sessions (token, account_id) VALUES (?, ?)", (token, row["id"])
        )
        db.commit()
        return self.send_json(
            200, {"token": token, "username": row["username"], "role": row["role"]}
        )

    def handle_me(self, account):
        return self.send_json(
            200,
            {
                "username": account["username"],
                "role": account["role"],
                "team": account["team"],
                "balance": account["balance"],
            },
        )

    # --- requests --------------------------------------------------------

    def handle_create_request(self, account):
        if account["role"] != "employee":
            return self.send_json(403, {"error": "only employees can submit requests"})
        body = self.read_json()
        if body is None:
            return self.send_json(400, {"error": "invalid json"})
        try:
            start = parse_date(body.get("start_date"))
            end = parse_date(body.get("end_date"))
        except ValueError:
            return self.send_json(400, {"error": "invalid dates"})
        if end < start:
            return self.send_json(400, {"error": "end_date before start_date"})
        days = (end - start).days + 1
        if days <= 0:
            return self.send_json(400, {"error": "days must be positive"})
        if days > account["balance"]:
            return self.send_json(400, {"error": "insufficient balance"})
        db = get_db()
        overlap = db.execute(
            "SELECT 1 FROM blocked_periods WHERE team = ? AND start_date <= ? AND end_date >= ?",
            (account["team"], body["end_date"], body["start_date"]),
        ).fetchone()
        if overlap is not None:
            return self.send_json(409, {"error": "requested dates overlap a blocked period"})
        db.execute(
            "UPDATE accounts SET balance = balance - ? WHERE id = ?", (days, account["id"])
        )
        cur = db.execute(
            "INSERT INTO requests (employee_id, start_date, end_date, days, state)"
            " VALUES (?, ?, ?, ?, 'PENDING')",
            (account["id"], body["start_date"], body["end_date"], days),
        )
        db.commit()
        return self.send_json(
            201, {"id": cur.lastrowid, "state": "PENDING", "days": days}
        )

    def handle_list_requests(self, account):
        db = get_db()
        if account["role"] == "manager":
            rows = db.execute(
                "SELECT r.* FROM requests r JOIN accounts a ON a.id = r.employee_id"
                " WHERE a.team = ? ORDER BY r.id",
                (account["team"],),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM requests WHERE employee_id = ? ORDER BY id",
                (account["id"],),
            ).fetchall()
        return self.send_json(200, {"requests": [dict(r) for r in rows]})

    def handle_get_request(self, account, req_id):
        db = get_db()
        req = db.execute("SELECT * FROM requests WHERE id = ?", (req_id,)).fetchone()
        if req is None:
            return self.send_json(404, {"error": "request not found"})
        owner = db.execute(
            "SELECT * FROM accounts WHERE id = ?", (req["employee_id"],)
        ).fetchone()
        if account["role"] == "manager":
            if owner["team"] != account["team"]:
                return self.send_json(403, {"error": "not on your team"})
        elif req["employee_id"] != account["id"]:
            return self.send_json(403, {"error": "not your request"})
        return self.send_json(200, dict(req))

    def handle_approve(self, account, req_id):
        if account["role"] != "manager":
            return self.send_json(403, {"error": "only managers can decide requests"})
        db = get_db()
        req = db.execute("SELECT * FROM requests WHERE id = ?", (req_id,)).fetchone()
        if req is None:
            return self.send_json(404, {"error": "request not found"})
        owner = db.execute(
            "SELECT * FROM accounts WHERE id = ?", (req["employee_id"],)
        ).fetchone()
        if owner["team"] != account["team"]:
            return self.send_json(403, {"error": "not on your team"})
        if req["state"] != "PENDING":
            return self.send_json(409, {"error": "request is not pending"})
        db.execute("UPDATE requests SET state = 'APPROVED' WHERE id = ?", (req_id,))
        db.commit()
        return self.send_json(200, {"id": req_id, "state": "APPROVED"})

    def handle_deny(self, account, req_id):
        if account["role"] != "manager":
            return self.send_json(403, {"error": "only managers can decide requests"})
        db = get_db()
        req = db.execute("SELECT * FROM requests WHERE id = ?", (req_id,)).fetchone()
        if req is None:
            return self.send_json(404, {"error": "request not found"})
        owner = db.execute(
            "SELECT * FROM accounts WHERE id = ?", (req["employee_id"],)
        ).fetchone()
        if owner["team"] != account["team"]:
            return self.send_json(403, {"error": "not on your team"})
        if req["state"] != "PENDING":
            return self.send_json(409, {"error": "request is not pending"})
        db.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (req["days"], req["employee_id"]),
        )
        db.execute("UPDATE requests SET state = 'DENIED' WHERE id = ?", (req_id,))
        db.commit()
        return self.send_json(200, {"id": req_id, "state": "DENIED"})

    def handle_cancel(self, account, req_id):
        db = get_db()
        req = db.execute("SELECT * FROM requests WHERE id = ?", (req_id,)).fetchone()
        if req is None:
            return self.send_json(404, {"error": "request not found"})
        if req["employee_id"] != account["id"]:
            return self.send_json(403, {"error": "not your request"})
        db.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (req["days"], req["employee_id"]),
        )
        db.execute("UPDATE requests SET state = 'CANCELLED' WHERE id = ?", (req_id,))
        db.commit()
        return self.send_json(200, {"id": req_id, "state": "CANCELLED"})

    # --- transfers -------------------------------------------------------

    def handle_transfer(self, account):
        if account["role"] != "employee":
            return self.send_json(403, {"error": "only employees can transfer leave"})
        body = self.read_json()
        if body is None:
            return self.send_json(400, {"error": "invalid json"})
        amount = body.get("amount")
        if type(amount) is not int or amount <= 0:
            return self.send_json(400, {"error": "amount must be a positive integer"})
        if amount > account["balance"]:
            return self.send_json(400, {"error": "insufficient balance"})
        db = get_db()
        recipient = db.execute(
            "SELECT * FROM accounts WHERE username = ?", (body.get("to_username"),)
        ).fetchone()
        if recipient is None or recipient["role"] != "employee":
            return self.send_json(400, {"error": "unknown recipient"})
        if recipient["id"] == account["id"]:
            return self.send_json(400, {"error": "cannot transfer to yourself"})
        db.execute(
            "UPDATE accounts SET balance = balance - ? WHERE id = ?",
            (amount, account["id"]),
        )
        db.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (amount, recipient["id"]),
        )
        db.commit()
        return self.send_json(
            200,
            {"from": account["username"], "to": recipient["username"], "amount": amount},
        )

    # --- blocked periods -------------------------------------------------

    def handle_create_blocked(self, account):
        if account["role"] != "manager":
            return self.send_json(403, {"error": "only managers can set blocked periods"})
        body = self.read_json()
        if body is None:
            return self.send_json(400, {"error": "invalid json"})
        try:
            start = parse_date(body.get("start_date"))
            end = parse_date(body.get("end_date"))
        except ValueError:
            return self.send_json(400, {"error": "invalid dates"})
        if end < start:
            return self.send_json(400, {"error": "end_date before start_date"})
        db = get_db()
        cur = db.execute(
            "INSERT INTO blocked_periods (team, start_date, end_date, created_by)"
            " VALUES (?, ?, ?, ?)",
            (account["team"], body["start_date"], body["end_date"], account["id"]),
        )
        db.commit()
        return self.send_json(
            201,
            {
                "id": cur.lastrowid,
                "team": account["team"],
                "start_date": body["start_date"],
                "end_date": body["end_date"],
            },
        )

    def handle_list_blocked(self, account):
        db = get_db()
        rows = db.execute(
            "SELECT * FROM blocked_periods WHERE team = ? ORDER BY id",
            (account["team"],),
        ).fetchall()
        return self.send_json(200, {"blocked_periods": [dict(r) for r in rows]})

    def handle_delete_blocked(self, account, bp_id):
        if account["role"] != "manager":
            return self.send_json(403, {"error": "only managers can remove blocked periods"})
        db = get_db()
        bp = db.execute(
            "SELECT * FROM blocked_periods WHERE id = ?", (bp_id,)
        ).fetchone()
        if bp is None:
            return self.send_json(404, {"error": "blocked period not found"})
        if bp["team"] != account["team"]:
            return self.send_json(403, {"error": "not your team"})
        db.execute("DELETE FROM blocked_periods WHERE id = ?", (bp_id,))
        db.commit()
        return self.send_json(200, {"deleted": bp_id})

    # --- routing ---------------------------------------------------------

    def do_GET(self):
        with _lock:
            path = self.path.split("?")[0]
            if path == "/health":
                return self.send_json(200, {"status": "ok"})
            account = self.current_account()
            if account is None:
                return self.send_json(401, {"error": "authentication required"})
            if path == "/me":
                return self.handle_me(account)
            if path == "/requests":
                return self.handle_list_requests(account)
            m = re.fullmatch(r"/requests/(\d+)", path)
            if m:
                return self.handle_get_request(account, int(m.group(1)))
            if path == "/blocked-periods":
                return self.handle_list_blocked(account)
            return self.send_json(404, {"error": "not found"})

    def do_POST(self):
        with _lock:
            path = self.path.split("?")[0]
            if path == "/login":
                return self.handle_login()
            account = self.current_account()
            if account is None:
                return self.send_json(401, {"error": "authentication required"})
            if path == "/requests":
                return self.handle_create_request(account)
            m = re.fullmatch(r"/requests/(\d+)/approve", path)
            if m:
                return self.handle_approve(account, int(m.group(1)))
            m = re.fullmatch(r"/requests/(\d+)/deny", path)
            if m:
                return self.handle_deny(account, int(m.group(1)))
            m = re.fullmatch(r"/requests/(\d+)/cancel", path)
            if m:
                return self.handle_cancel(account, int(m.group(1)))
            if path == "/transfers":
                return self.handle_transfer(account)
            if path == "/blocked-periods":
                return self.handle_create_blocked(account)
            return self.send_json(404, {"error": "not found"})

    def do_DELETE(self):
        with _lock:
            path = self.path.split("?")[0]
            account = self.current_account()
            if account is None:
                return self.send_json(401, {"error": "authentication required"})
            m = re.fullmatch(r"/blocked-periods/(\d+)", path)
            if m:
                return self.handle_delete_blocked(account, int(m.group(1)))
            return self.send_json(404, {"error": "not found"})


def main():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"leave service listening on {PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
