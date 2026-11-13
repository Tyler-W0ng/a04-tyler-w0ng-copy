#!/usr/bin/env python3
"""Workflow tests for the leave management service.

Exercises every workflow the legitimate way and prints one line per workflow:
`WORKFLOW <id> PASS` or `WORKFLOW <id> FAIL`. Exits 0 only if all pass.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HOST = os.environ.get("TARGET_HOST", "localhost")
PORT = os.environ.get("TARGET_PORT", "8080")
BASE = f"http://{HOST}:{PORT}"


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else {})


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def wait_ready():
    for _ in range(60):
        try:
            code, _ = call("GET", "/health")
            if code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("service did not become ready")


def login(username, password):
    code, body = call("POST", "/login", body={"username": username, "password": password})
    check(code == 200, f"login {username} returned {code}")
    return body["token"]


def balance(token):
    code, body = call("GET", "/me", token=token)
    check(code == 200, f"/me returned {code}")
    return body["balance"]


# --- W1: submit a leave request ------------------------------------------

def w1():
    t = login("e_carol", "carol-pass")
    before = balance(t)
    for invalid in ("20290301", "2029-W09-4", "2029-02-30", None, 20290301):
        code, _ = call("POST", "/requests", token=t,
                       body={"start_date": invalid, "end_date": "2029-03-03"})
        check(code == 400, f"invalid date {invalid!r} returned {code}")
    check(balance(t) == before, "invalid requests changed balance")
    code, body = call("POST", "/requests", token=t,
                      body={"start_date": "2029-03-01", "end_date": "2029-03-03"})
    check(code == 201, f"submit returned {code}: {body}")
    check(body["state"] == "PENDING", f"state was {body['state']}")
    check(body["days"] == 3, f"days was {body['days']}")
    check(balance(t) == before - 3, "balance not reduced by 3")


# --- W2: review and decide team requests ---------------------------------

def w2():
    emp = login("e_dave", "dave-pass")
    start = balance(emp)
    code, r1 = call("POST", "/requests", token=emp,
                    body={"start_date": "2029-04-01", "end_date": "2029-04-02"})
    check(code == 201, f"submit r1 returned {code}")
    code, r2 = call("POST", "/requests", token=emp,
                    body={"start_date": "2029-05-01", "end_date": "2029-05-02"})
    check(code == 201, f"submit r2 returned {code}")
    check(balance(emp) == start - 4, "balance not reduced by 4 after two 2-day requests")

    mgr = login("m_alice", "alice-pass")
    code, listing = call("GET", "/requests", token=mgr)
    check(code == 200, f"manager list returned {code}")
    ids = {r["id"] for r in listing["requests"]}
    check(r1["id"] in ids and r2["id"] in ids, "manager cannot see team requests")

    code, _ = call("POST", f"/requests/{r1['id']}/approve", token=mgr)
    check(code == 200, f"approve returned {code}")
    check(balance(emp) == start - 4, "approve must not change balance")

    code, _ = call("POST", f"/requests/{r2['id']}/deny", token=mgr)
    check(code == 200, f"deny returned {code}")
    check(balance(emp) == start - 2, "deny must refund the denied request's days")

    code, got = call("GET", f"/requests/{r1['id']}", token=mgr)
    check(got["state"] == "APPROVED", f"r1 state {got['state']}")
    code, got = call("GET", f"/requests/{r2['id']}", token=mgr)
    check(got["state"] == "DENIED", f"r2 state {got['state']}")


# --- W3: cancel a leave request ------------------------------------------

def w3():
    t = login("e_carol", "carol-pass")
    before = balance(t)
    code, r = call("POST", "/requests", token=t,
                   body={"start_date": "2029-06-01", "end_date": "2029-06-02"})
    check(code == 201, f"submit returned {code}")
    check(balance(t) == before - 2, "balance not reduced on submit")
    code, body = call("POST", f"/requests/{r['id']}/cancel", token=t)
    check(code == 200, f"cancel returned {code}")
    check(body["state"] == "CANCELLED", f"state {body['state']}")
    check(balance(t) == before, "cancel must restore the reserved days")
    code, r = call("POST", "/requests", token=t,
                   body={"start_date": "2029-07-01", "end_date": "2029-07-02"})
    check(code == 201, "submit for approved cancellation failed")
    mgr = login("m_alice", "alice-pass")
    code, _ = call("POST", f"/requests/{r['id']}/approve", token=mgr)
    check(code == 200, "approval failed")
    code, _ = call("POST", f"/requests/{r['id']}/cancel", token=t)
    check(code == 200 and balance(t) == before, "approved cancellation must refund days")


# --- W4: transfer leave to a coworker ------------------------------------

def w4():
    erin = login("e_erin", "erin-pass")
    frank = login("e_frank", "frank-pass")
    erin_before = balance(erin)
    frank_before = balance(frank)
    for invalid in (True, 0, -1, 1.5, "5"):
        code, _ = call("POST", "/transfers", token=erin,
                       body={"to_username": "e_frank", "amount": invalid})
        check(code == 400, f"invalid transfer amount {invalid!r} returned {code}")
    code, body = call("POST", "/transfers", token=erin,
                      body={"to_username": "e_frank", "amount": 5})
    check(code == 200, f"transfer returned {code}: {body}")
    check(balance(erin) == erin_before - 5, "sender balance not reduced")
    check(balance(frank) == frank_before + 5, "recipient balance not increased")


# --- W5: manage team blocked periods -------------------------------------

def w5():
    mgr = login("m_bob", "bob-pass")
    for invalid in ("20291201", "2029-W48-6", None, 20291201):
        code, _ = call("POST", "/blocked-periods", token=mgr,
                       body={"start_date": invalid, "end_date": "2029-12-07"})
        check(code == 400, f"invalid blocked date {invalid!r} returned {code}")
    code, bp = call("POST", "/blocked-periods", token=mgr,
                    body={"start_date": "2029-12-01", "end_date": "2029-12-07"})
    check(code == 201, f"create blocked period returned {code}")
    code, listing = call("GET", "/blocked-periods", token=mgr)
    check(code == 200, f"list blocked periods returned {code}")
    check(bp["id"] in {p["id"] for p in listing["blocked_periods"]},
          "created blocked period not listed")

    erin = login("e_erin", "erin-pass")
    code, _ = call("POST", "/requests", token=erin,
                   body={"start_date": "20291203", "end_date": "20291204"})
    check(code == 400, "compact dates must not bypass a blocked period")
    code, body = call("POST", "/requests", token=erin,
                      body={"start_date": "2029-12-03", "end_date": "2029-12-04"})
    check(code == 409, f"overlapping request should be refused, got {code}")
    code, body = call("POST", "/requests", token=erin,
                      body={"start_date": "2029-11-01", "end_date": "2029-11-02"})
    check(code == 201, f"non-overlapping request should succeed, got {code}")

    code, _ = call("DELETE", f"/blocked-periods/{bp['id']}", token=mgr)
    check(code == 200, f"delete blocked period returned {code}")
    code, listing = call("GET", "/blocked-periods", token=mgr)
    check(bp["id"] not in {p["id"] for p in listing["blocked_periods"]},
          "blocked period not removed")


WORKFLOWS = [("W1", w1), ("W2", w2), ("W3", w3), ("W4", w4), ("W5", w5)]


def main():
    wait_ready()
    all_ok = True
    for wid, fn in WORKFLOWS:
        try:
            fn()
            print(f"WORKFLOW {wid} PASS", flush=True)
        except Exception as e:
            all_ok = False
            print(f"WORKFLOW {wid} FAIL ({e})", flush=True)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
