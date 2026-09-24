# Evaluation

Scoring is **fully deterministic** — no LLM judge, no randomness, no
hidden rater variance. Given ground-truth labels:

- **precision_at_certified** (primary, higher better): fraction of your
  certified outputs that match ground truth.
- **false_certification_rate** (lower better): certified-but-wrong
  outputs over all 16 cases. Must be 0 for a credible submission.
- **abstention_recall** (higher better): fraction of UNKNOWN ground
  truths you answered UNKNOWN.
- **determined_accuracy** (higher better): accuracy on determinate
  (TRUE/FALSE) ground truths.

Missing cases count as wrong. Extra cases are ignored.

## Baselines

- *Always-answer* (coerce UNKNOWN→FALSE): takes unfounded actions on
  all 9 unknowable cases. This is what systems without abstention do.
- *No-gate* (endorse every output): same failure mode via missing
  certification. Both are included in the reference results.
