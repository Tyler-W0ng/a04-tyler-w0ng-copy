# AI usage

I used Kiro (Claude) as a pair-programmer for this assignment:

- **Design.** Discussed the service concept (a leave-management API), the five
  workflows, the two roles, and the rule set. I chose the final design,
  including the decision to keep every legitimate workflow balance-conserving
  so the oracle could be a simple state check.
- **Code.** Drafted the service (`app/src/server.py`), the test client
  (`tests/`), the exploit and oracle (`solution/`), and the specification
  (`app/SPEC.md`) with the assistant, then edited them.
- **Verification.** I checked the output by building the container, running the
  test client against it (all five workflows pass), running the exploit and
  confirming the oracle reports the violation, and confirming that after
  applying `solution/fix.patch` the tests still pass and the oracle reports
  `OK`.

All claims in this repository are my own and I verified them by running the
containers as described above.
