# checks/ — claims that can be re-run

A claim is only a claim here if it is executable. Each file is a check that
answers two questions, not one:

    ./checks/<id> pass     exit 0 if the claimed state holds
    ./checks/<id> fail     MUST exit non-zero — a deliberately-false variant

The `fail` mode is the load-bearing half. A proxy measurement satisfies its
positive assertion *and* its negative control, because it cannot tell true from
false. `scripts/vsl/validator/verify_claim.py` rejects such a check as INVALID rather
than passing it — a proxy is not a wrong answer, it is a non-answer.

Every verification failure recorded on 2026-08-10 had exactly that shape:

    grep -qs "$TOK" file        empty TOK  -> matches anything
    git ls-files <path>         blocked commit -> path still listed
    a ✓-printing size check     bc missing -> prints ✓ regardless
    grep ... | head -8          match present -> still shows nothing
    counting a hook's output    valid input -> same line count

None was caught by reading harder. All five are caught by requiring the
negative control.

## Wiring

`scripts/docs/git_commit_msg.sh` (symlinked to `.git/hooks/commit-msg`): if a
commit message claims verification — verified / confirmed / measured / proven,
in English or Spanish — it must carry

    Verified-By: <check-id>[, <check-id>]

and those checks are RUN, negative control included. No trailer, or a failing
check, blocks the commit. Override once with `VSF_SKIP_R4_GATE=1`, and say why
in the message.

This is R4 given a gate. It was the only load-bearing rule in this repo
enforced by intention alone.

## Adding one

Keep it cheap enough to run on every commit that cites it. If a claim cannot be
made executable, that is information: do not make the claim.
