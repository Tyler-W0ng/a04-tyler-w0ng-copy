# A04: A network service with a logic vulnerability

**Individual.** Read [the submission guide](SUBMISSION.md) first. Dates are
on the course schedule.

Most automated vulnerability detection looks for broken code: memory
errors, injections, crashes. A **logic vulnerability** is different. Every
line of the code may be fine, yet the application does something its
designers never intended: it lets a user act on another user's data, skip a
step of a workflow, or apply a discount twice. You can only see it if you
know what the application is *supposed* to do.

You will build a small but realistic network service, write a precise
specification of its intended behavior, and plant one logic vulnerability
that violates a rule of that specification. Your service may become one
of the targets of A06, where groups build agents that hunt for logic
vulnerabilities starting from specifications like yours.

---

## 1. The application

- **One container**, providing a network service: a web application, a JSON
  API, or a text or binary protocol over TCP. Any language. Use an embedded
  datastore such as SQLite or in-memory state, not a second container.
- **Self-contained**: no internet access at run time, no external services.
  It starts in under 60 seconds on `linux/amd64`, and the image is under 1 GB.
- **Deterministic start**: every start seeds the same initial data
  (accounts, items, and so on). Restarting the container resets the
  service.
- **Not too simple.** It implements **at least five workflows**: distinct
  user-level tasks that each take more than one request and change state.
  For example: browsing and buying items; leaving and moderating reviews;
  checking out a cart; managing an account; messaging other users. Two
  workflows must interact (for example, only buyers may review). There are at
  least **two roles** with different permissions (for example customer and
  administrator).

## 2. The specification

`app/SPEC.md` describes the intended behavior for someone who has never
seen your code: an analyst, or an agent. It contains:

- the purpose of the service and its roles;
- the interface: every endpoint or message, with its parameters, responses,
  and errors, precise enough to write a client from;
- each workflow, step by step;
- the **rules**: numbered statements of what must and must not happen,
  such as *R7: a coupon can be applied to at most one order*, or *R12: only
  the author of a review or an administrator can delete it*. Write at least
  ten rules, covering authorization, workflow order, quantities, and
  ownership.

The specification must be **correct for the intended behavior** and must
**not hint** at the vulnerability. The rule your vulnerability violates is
one rule among many, written like the others.

## 3. The vulnerability

Plant **exactly one** logic vulnerability:

- It **violates one rule** of `SPEC.md`.
- It is reachable through the normal network interface by a user with an
  ordinary role, and it has a **security consequence**: someone gains an
  advantage, data, or capability the rules deny them.
- It is a **logic flaw**: a missing check, a wrong order of operations, an
  ownership mix-up, or a state machine that allows a forbidden transition.
  Memory-safety bugs, injections, hard-coded credentials, debug back doors,
  and vulnerable dependencies do not count.
- It is **plausible**: a mistake a competent developer could make. It must
  not be signposted by names or comments, and the code around it is written
  with the same care as the rest.

## 4. Tests, exploit, oracle, and fix

Your repository also proves that the application works and that the
vulnerability is real:

- `tests/`: a client container that exercises **every workflow** the
  legitimate way and checks the results. It exits with 0 only if all tests
  pass, and prints one line per workflow: `WORKFLOW <id> PASS` or
  `WORKFLOW <id> FAIL`.
- `solution/exploit/`: a client container that triggers the vulnerability
  against a freshly started service.
- `solution/oracle/`: a script, `run.sh`, that the grader copies into the
  running application container and executes there after the exploit. It
  inspects the application's **state** directly (for example by querying the
  database) and prints `VIOLATED R<n>` if the state breaks rule R<n>, or `OK`
  otherwise. The oracle checks the rule itself, not traces of your specific
  exploit: it must detect a violation of that rule however it was reached.
- `solution/fix.patch`: a minimal patch to `app/` that removes the
  vulnerability without breaking any workflow.

The client containers receive the service's address in the environment
variables `TARGET_HOST` and `TARGET_PORT`.

## 5. Repository layout

```text
submission.toml       assignment = "A04", members, rule = "R7"
app/
    Dockerfile
    app.toml          port, protocol, readiness check, workflow ids and names, rule ids
    SPEC.md
    src/ ...
tests/
    Dockerfile
solution/
    VULNERABILITY.md  the rule, the root cause (file and lines), the impact, why it is plausible
    exploit/Dockerfile
    oracle/run.sh
    fix.patch
AI_USAGE.md
.cs279/               course tools (do not modify)
```

`app/` must make sense on its own: if A06 uses your service, its groups
receive `app/` and nothing else. Keep anything that hints at the solution
out of `app/`, including comments, file names, and seed data.

An example `app.toml`:

```toml
port = 8080
protocol = "http"                 # http | tcp
ready = "http:/health"            # or "tcp"
workflows = [
  { id = "W1", name = "Register and log in" },
  { id = "W2", name = "Browse and add items to the cart" },
  { id = "W3", name = "Check out" },
  { id = "W4", name = "Review a purchased item" },
  { id = "W5", name = "Message another user" },
]
rules = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10"]
```

Feedback runs: **3 for the whole assignment**.

## 6. Grading

The grader builds `app/` and starts it. It runs `tests/`, then the exploit
followed by the oracle. It then applies `fix.patch`, rebuilds, and runs the
tests and the exploit with the oracle again. Each run uses a fresh
container.

| Criterion | Points | How |
|---|---:|---|
| The service builds, starts, and becomes ready | 5 | automated |
| At least 5 workflows declared, all passing in `tests/` | 15 | automated |
| Exploit, then oracle, reports `VIOLATED` for the declared rule on the vulnerable service; the oracle reports `OK` after the tests alone | 15 | automated |
| After `fix.patch`: all workflows still pass and the oracle reports `OK` after the exploit | 15 | automated |
| **Specification**: complete and precise interface, workflows, and rules; correct for the intended behavior; no hints | 15 | AI-assessed |
| **Vulnerability**: a genuine logic flaw violating the declared rule, with a real security consequence, plausible and not signposted; a sound oracle | 20 | AI-assessed |
| **Application**: realistic, non-trivial workflows and roles that interact | 10 | AI-assessed |
| `VULNERABILITY.md` and AI disclosure | 5 | AI-assessed |
