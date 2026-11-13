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

I also used OpenAI Codex (GPT-6) to review the handout and implementation,
identify and repair the oracle's handling of reserved days and Linux line
endings, enforce the documented date format, improve input validation, and add
regression checks. Codex updated the oracle explanation and fix patch location.
Verification used local Docker containers on an isolated internal network:
preflight, all five workflows on vulnerable and patched builds, exploit and
oracle checks on fresh instances, and oracle state fixtures covering violations
hidden by outstanding reservations. These checks were executed by the assistant;
they are not a claim that I independently repeated this later verification.

All submitted claims remain my responsibility.
