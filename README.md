# vOSLAB

Experimental workspace for the vOS ecosystem. Built clean per the ratified
vOSLAB plan (`voslab_directory_tree_proposal.vsm`, 2026-08-29).

Build order (P0.1): gate-suite (negative-control "nerves") FIRST, then the
`vsf-common` coupling protocol, then public agnostic packages, then framework
packages. Every package is admitted only after the gate-suite passes its
negative-control harness on it.

Canonical design lives in `~/vsf/child/docs/voslab_*.vsm`.

## Deploy

Transport is **git**; setup is **`./bootstrap.sh`** (hybrid, R1-safe):

```
git clone <vOSLAB> vOSlab
cd vOSlab
./bootstrap.sh                 # venv + deps + verify gate-suite
./bootstrap.sh --with-packages # also resolve external ~/packages/* pins (pins.toml)
```

`bootstrap.sh` is idempotent and must run **on the target** (e.g. inside an
LXC) — never build on WSL. External durable packages (`~/packages/{public,
framework}`) are declared in `pins.toml` and resolved once their repos exist
(extraction phase).
