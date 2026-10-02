#!/usr/bin/env bash
# commit-msg hook — R4(.1) gate (versioned source; .git/hooks/commit-msg symlinks here).
#
# R4 ("a claim of success is not evidence of success") was recorded 2026-08-03
# and was the only load-bearing rule in this repo with no gate. On 2026-08-10
# it failed five times in one session — including a live credential committed
# to main inside the very command that claimed to prove such a commit was
# blocked. Prose claims were never checkable; now they are.
#
# R4.1 (2026-08-11): the wording trigger has its own loophole — reword the
# message to drop the trigger word, the gate stays silent. So it now also
# fires structurally, independent of wording: closing a [S]-dispatched
# TASKS.vsm task as done/closed requires the same Verified-By evidence,
# whatever the message says. rmw3: "el hoyo por el que hemos caido desde el
# comienzo" — closing dispatched work on the deliverer's own report, with
# nothing structural requiring the closer to have re-run anything.
#
# If a commit message claims verification, OR closes dispatched work, it must
# name checks, and they must run clean — including each check's negative
# control. See scripts/vsl/validator/verify_claim.py for why the negative control is
# the load-bearing part: a proxy satisfies its positive assertion and its
# negative one too.
[ -n "${VSF_SKIP_R4_GATE:-}" ] && exit 0
exec python3 "$(git rev-parse --show-toplevel)/scripts/vsl/validator/verify_claim.py" --trailers "$1"
