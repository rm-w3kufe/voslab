# vOSLAB

Experimental workspace for the vOS ecosystem. Built clean per the ratified
vOSLAB plan (`voslab_directory_tree_proposal.vsm`, 2026-08-29).

Build order (P0.1): gate-suite (negative-control "nerves") FIRST, then the
`vsf-common` coupling protocol, then public agnostic packages, then framework
packages. Every package is admitted only after the gate-suite passes its
negative-control harness on it.

Canonical design lives in `~/vsf/child/docs/voslab_*.vsm`.
