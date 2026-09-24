# Governed Autonomy Honesty

Task benchmarks saturate while ignoring whether an agent *should have
acted at all*. This benchmark measures **certified abstention under
uncertainty**: given trivalent evaluation cases (TRUE/FALSE/UNKNOWN
with certification flags), can a governed system withhold confident
answers where evidence is insufficient?

## Format

16 adversarial cases across three classes:

- **D (decidable, 6)**: complete evidence → determinate certified verdict.
- **I (ignorance, 5)**: missing fields, non-numeric values → UNKNOWN,
  uncertified. The honest answer is abstention.
- **C (conflict, 5)**: contradictory evidence, hung juries, quorum
  failures → UNKNOWN with or without certification, per exact rules.

Each case provides a decision tree + context in plain JSON using only
deterministic predicates (`type_prefix`, `gt/lt/eq`, `ctx_has`,
`AND/OR/NOT`, `JURY`, `DIALECTICAL_AND`). No model, no API, no judge
needed to attempt it.

## Submission

Upload `answers.json`: a list of `{case_id, truth, certified}` where
`truth` is one of `TRUE/FALSE/UNKNOWN` and `certified` is boolean.

## Reference row

The organizers' own control plane (socratic-engine, trivalent +
certified-UNKNOWN doctrine) scores precision@certified 1.0 with zero
false certifications. Beat it — or show where it fails.
