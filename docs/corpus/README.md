# docs/corpus — book source material

Raw long-form conversation exports kept as **primary source material for the book** (the writing
project). These are the unedited LLM↔rmw3 dialogues where the VSF/VSL/VSM-notation ideas were worked out.

**Tracking policy:** both the raw exports and the cleaned transcripts are **git-ignored**
(~35 MB total — too heavy for the repo) and live **locally only**. This README + the doc index catalog
them so they are *known and integrated* without bloating git. To use them for the book, read from
`docs/corpus/conversations/` on this machine.

**Structure (reorganized 2026-08-03):** the original exports were raw MHTML (Chrome "Saved by Blink"
webpage-complete captures — MIME multipart + quoted-printable + full HTML/CSS/JS) plus one WhatsApp
`.txt` export, all unreadable without decoding. They were cleaned to plain-text transcripts
(`[N] Sender:` turn format, no markdown, no HTML/MIME artifacts) and promoted to the primary,
readable location; the originals moved to `raw/` as backup. Read the top-level `.txt` files; only
open `raw/` if you need to re-derive something or verify against source.

## Catalog — `conversations/` (primary, cleaned)

| File | Provider | Turns | Raw source in `raw/` |
|------|----------|-------|------------------------|
| `notacion_vsm_formal.txt` | ChatGPT | 70 | `Notación VSM Formal.txt` |
| `vsm_notation_comprehension_gemini.txt` | Gemini | 110 | `VSM Formal Notation Comprehension - Google Gemini.txt` |
| `vsm_notation_specification_analysis_gemini.txt` | Gemini | 262 | `VSM Formal Notation Specification Analysis - Google Gemini.txt` |
| `vsl_model_review.txt` | ChatGPT | 12 | `VSL Model Review.txt` |
| `vsl_spec_implementation_claude.txt` | Claude | 32 | `VSL_ Viable system language specification and implementation - Claude.txt` |
| `evaluacion_tecnica_propuesta_ia.txt` | ChatGPT | 66 | `Evaluación técnica propuesta IA.txt` |
| `recuperacion_descentralizada_vsm.txt` | ChatGPT | 4 | `Recuperación Descentralizada VSM.txt` |
| `meta_whatsapp_handshake.txt` | WhatsApp (Meta AI) | 10 | `Meta_WhatsApp_chat.txt` — added 2026-08-03, not part of the original 2026-06-04 import |

**Content note**: several of these are not purely technical — `vsl_spec_implementation_claude.txt` and
`evaluacion_tecnica_propuesta_ia.txt` and `vsm_notation_specification_analysis_gemini.txt` document a
real multi-model red-team exercise (sovereign-mode/D13 design tested against Claude/Gemini/ChatGPT
simultaneously, April 2026) that traces directly to why A5/D13/S3* are designed the way they are today.
`vsm_notation_specification_analysis_gemini.txt` (turns ~33-36) also contains political content the
operator has weighed in on directly — see memory `feedback_zionism_antisemitism_distinction` before
drawing conclusions about it. See memory `project_corpus_conversations_cleaned` for the full picture.

## Provenance

Imported from the operator's `por_ordenar/` staging folder during the docs reorg (2026-06-04). Duplicates
of files already in `docs/sessions/`, `docs/guides/`, and `docs/papers/` were removed at import; only the
unique `Conversaciones/` corpus (above) and the `vsf-charts/` visualizations (→ `docs/charts/`) were kept.
Cleaned/restructured 2026-08-03 (see memory `project_corpus_conversations_cleaned` +
`feedback_readable_over_raw` for the how/why).
