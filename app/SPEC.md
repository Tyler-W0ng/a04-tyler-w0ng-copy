# Leave management service — specification

## 1. Purpose and roles

The service tracks paid time off for a small company. Employees request leave
from a personal balance of days; their manager reviews those requests. The
service is an HTTP/JSON API. All state is held in an embedded SQLite database
that is recreated and reseeded every time the service starts, so a restart
returns it to the initial state below.

There are two roles:

- **Employee** — owns a leave balance (a whole number of days). Submits leave
  requests, cancels their own requests, and transfers days to a coworker.
- **Manager** — leads one team. Reviews the leave requests of employees on
  that team (approve or deny) and defines periods during which that team may
  not take leave. A manager does not hold a leave balance and does not submit
  leave requests.

Every account belongs to exactly one **team**. A manager can act only on the
employees of the team they lead.

## 2. Seed data

The following accounts exist after every start. Passwords are fixed so that a
client can log in deterministically.

| Username  | Password     | Role     | Team        | Balance |
|-----------|--------------|----------|-------------|--------:|
| m_alice   | alice-pass   | manager  | engineering |       0 |
| m_bob     | bob-pass     | manager  | sales       |       0 |
| e_carol   | carol-pass   | employee | engineering |      20 |
| e_dave    | dave-pass    | employee | engineering |      20 |
| e_erin    | erin-pass    | employee | sales       |      20 |
| e_frank   | frank-pass   | employee | sales       |      20 |

There are no leave requests and no blocked periods at start. The total of all
employee balances at start is 80.

## 3. Data model

- **Account**: `username`, `role` (`employee` or `manager`), `team`,
  `balance` (days currently available; employees only).
- **Request**: `id`, `employee_id` (the owner), `start_date`, `end_date`
  (inclusive, ISO `YYYY-MM-DD`), `days` (number of calendar days in the
  range, inclusive), `state` (one of `PENDING`, `APPROVED`, `DENIED`,
  `CANCELLED`).
- **Blocked period**: `id`, `team`, `start_date`, `end_date` (inclusive).

### Request state machine

```
            approve
 (new) ───► PENDING ─────────► APPROVED
              │  │                 │
         deny │  │ cancel          │ cancel
              ▼  ▼                 ▼
          DENIED  CANCELLED    CANCELLED
```

`DENIED` and `CANCELLED` are terminal: no transition leaves them.

### Balance effects

- Submitting a request reserves its `days`: the owner's balance decreases by
  `days`.
- Approving a request does not change any balance (the reserved days are now
  committed to leave that will be taken).
- Denying a request returns its `days` to the owner's balance.
- Cancelling a request returns its `days` to the owner's balance.
- Transferring moves `amount` days from the sender to the recipient.

## 4. Authentication

`POST /login` returns an opaque bearer token. Every endpoint except
`GET /health` and `POST /login` requires the header
`Authorization: Bearer <token>`. A missing or unknown token is answered with
`401`. A token identifies one account and carries that account's role and
team.

## 5. Interface

All request and response bodies are JSON. Dates are ISO `YYYY-MM-DD`.
Common error responses: `400` (malformed input), `401` (not authenticated),
`403` (not allowed), `404` (no such object), `409` (conflicts with the
object's current state).

### `GET /health`
Liveness probe. No authentication. → `200 {"status": "ok"}`.

### `POST /login`
Body `{"username", "password"}`.
- `200 {"token", "username", "role"}` on success.
- `401 {"error"}` if the username is unknown or the password is wrong.

### `GET /me`
Returns the caller's account.
→ `200 {"username", "role", "team", "balance"}`.

### `POST /requests`
Submit a leave request (employee only). Body `{"start_date", "end_date"}`.
`days` is computed as the inclusive number of days between the two dates.
- `201 {"id", "state": "PENDING", "days"}` on success; the caller's balance
  decreases by `days`.
- `400` if the dates are malformed, `end_date` precedes `start_date`, or
  `days` exceeds the caller's current balance.
- `403` if the caller is a manager.
- `409` if the range overlaps a blocked period for the caller's team.

### `GET /requests`
List requests. For an employee, their own requests. For a manager, all
requests of employees on the manager's team.
→ `200 {"requests": [ {request}, ... ]}`.

### `GET /requests/{id}`
Return one request. Allowed for the request's owner, or for the manager of the
owner's team.
- `200 {request}`.
- `403` if the caller is neither the owner nor the owning team's manager.
- `404` if no such request.

### `POST /requests/{id}/approve`
Approve a request (manager only). No body.
- `200 {"id", "state": "APPROVED"}`.
- `403` if the caller is not a manager, or the request's owner is not on the
  caller's team.
- `404` if no such request.
- `409` if the request is not `PENDING`.

### `POST /requests/{id}/deny`
Deny a request (manager only). No body. Returns the request's `days` to the
owner's balance.
- `200 {"id", "state": "DENIED"}`.
- `403` if the caller is not a manager, or the request's owner is not on the
  caller's team.
- `404` if no such request.
- `409` if the request is not `PENDING`.

### `POST /requests/{id}/cancel`
Cancel a request (the request's owner only). No body. Returns the request's
`days` to the owner's balance.
- `200 {"id", "state": "CANCELLED"}`.
- `403` if the caller is not the request's owner.
- `404` if no such request.
- `409` if the request is not `PENDING` or `APPROVED`.

### `POST /transfers`
Transfer leave to a coworker (employee only). Body `{"to_username", "amount"}`.
- `200 {"from", "to", "amount"}`; `amount` days move from the caller to the
  recipient.
- `400` if `amount` is not a positive integer, exceeds the caller's balance,
  the recipient does not exist or is not an employee, or the recipient is the
  caller.
- `403` if the caller is a manager.

### `POST /blocked-periods`
Create a blocked period for the manager's team (manager only). Body
`{"start_date", "end_date"}`.
- `201 {"id", "team", "start_date", "end_date"}`.
- `400` if the dates are malformed or `end_date` precedes `start_date`.
- `403` if the caller is not a manager.

### `GET /blocked-periods`
List the blocked periods for the caller's team.
→ `200 {"blocked_periods": [ {blocked period}, ... ]}`.

### `DELETE /blocked-periods/{id}`
Remove a blocked period (manager only; must belong to the manager's team).
- `200 {"deleted": id}`.
- `403` if the caller is not a manager, or the period belongs to another team.
- `404` if no such period.

## 6. Workflows

- **W1 — Submit a leave request.** An employee logs in, reads their balance
  (`GET /me`), and submits a request with `POST /requests`. The request is
  `PENDING` and the balance drops by the requested days.
- **W2 — Review and decide team requests.** A manager logs in, lists their
  team's requests with `GET /requests`, and approves or denies each pending
  one with `POST /requests/{id}/approve` or `/deny`. A denial returns the days
  to the employee.
- **W3 — Cancel a leave request.** An employee logs in and cancels one of
  their own pending or approved requests with `POST /requests/{id}/cancel`.
  The days return to their balance.
- **W4 — Transfer leave to a coworker.** An employee logs in and moves part of
  their balance to another employee with `POST /transfers`.
- **W5 — Manage team blocked periods.** A manager logs in, creates a blocked
  period with `POST /blocked-periods`, confirms it with `GET /blocked-periods`,
  and may remove it with `DELETE /blocked-periods/{id}`. While a blocked
  period exists, a team member's request overlapping it is refused (W1).

## 7. Rules

- **R1.** Every endpoint except `GET /health` and `POST /login` requires a
  valid bearer token; requests without one are refused.
- **R2.** An employee may read and act on only their own requests; a manager
  may read and act on only the requests of employees on their own team.
- **R3.** Only a manager may approve or deny a request.
- **R4.** A manager may approve or deny a request only when the request's
  owner is on the manager's team.
- **R5.** A request may be approved or denied only while it is `PENDING`.
- **R6.** A request may be cancelled only while it is `PENDING` or `APPROVED`.
- **R7.** Only the employee who created a request may cancel it.
- **R8.** Submitting a request requires a whole number of days greater than
  zero that does not exceed the employee's current balance, and reserves
  exactly that many days from the balance.
- **R9.** Denying a request returns exactly its reserved days to the owner's
  balance; approving a request changes no balance.
- **R10.** Cancelling a request returns exactly its reserved days to the
  owner's balance and sets the request to `CANCELLED`.
- **R11.** A transfer requires an amount greater than zero that does not
  exceed the sender's balance, and a recipient who is a different, existing
  employee; it moves exactly that many days from sender to recipient.
- **R12.** Only a manager may create or remove a blocked period, and only for
  their own team; a request whose dates overlap a blocked period for the
  employee's team is refused.
