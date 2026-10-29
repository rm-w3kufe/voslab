# vOS / VSF — documentation

> Viable System Framework: a framework for designing and operating viable
> systems, based on Beer's VSM (1972) and Cybersyn patterns (1971).

## Start here

| If you are... | Read |
|---|---|
| New to the project | [concepts](guides/concepts.md) → [VSL guide](guides/human_guide.md) |
| Continuing a session | [DOCS gateway](DOCS.md) → [generated index](INDEX.md) |
| Looking for a term | [glossary](glossary.vsm) |
| Writing a paper | [papers/](papers/) → the paper's `paper_data.vsm` |
| Evaluating the system | [evaluation/](evaluation/) → latest `system_evaluation_*.vsm` |
| Planning work | [active-plan trunk](plans/plan-01/plans_active.vsm) |

## Canon and working docs

- `system/` — normative canon: rules, policies, contracts, invariants.
  Start at `system/INDEX.vsm`.
- `docs/` — working documents. The full map, homes, and legacy areas are in
  [DOCS.md](DOCS.md).
- `docs/INDEX.md` — generated filesystem index (do not hand-edit).
- `docs/canon_mirror/` — verified mirror; authority remains in `system/`.

## Creating a document

The home is policy, not preference. Ask:

```bash
python3 scripts/vsl/classifier/doc_home.py suggest <TYPE> [status] [name]
```

The write-time DOC-HOME gate blocks a new document outside the approved
homes and tells you the canonical path.

## Core references

- Beer, S. (1972). *Brain of the Firm*. Allen Lane.
- Beer, S. (1979). *The Heart of Enterprise*. Wiley.
- Medina, E. (2011). *Cybernetic Revolutionaries*. MIT Press.
- Ashby, W. R. (1956). *An Introduction to Cybernetics*. Chapman & Hall.
- Ott, E., Grebogi, C., Yorke, J. A. (1990). *Controlling Chaos*. PRL 64(11).
