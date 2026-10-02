#!/usr/bin/env bash
# deploy_bundle.sh — coordinated redeploy of nucleus + s3-star + g6_sink.
#
# Bundles three deferred deploys into one operator-confirmed movement:
#   - #110: nucleus migrated to vsf_agent (shared CanonicalEvent + nats helper)
#   - #105: s3-star using the shared crate (behaviorally identical)
#   - #112: future chain-format bump (NOT YET implemented in this bundle;
#           placeholder so that we don't forget to pair it)
#   - G6:  g6_algedonic_sink.py + systemd unit on LXC 104
#
# Behaviour:
#   - Default: DRY RUN. Prints every step, modifies nothing.
#   - --execute: actually performs the steps after a final yes/no prompt.
#   - --skip-build: assume target/release binaries are current; just push.
#   - --build-only: sync + build (§1-§2), then stop BEFORE any deploy (§3-§6).
#     Used by covenant ceremony P4: the build's hash must be verified against
#     the P4 gate before P5 moves production. Binaries staged on n02; the
#     subsequent deploy runs with --execute --skip-build.
#
# Operator usage:
#   ./scripts/deploy/deploy_bundle.sh             # see plan
#   ./scripts/deploy/deploy_bundle.sh --execute   # do it
set -euo pipefail

EXECUTE=0
SKIP_BUILD=0
ASSUME_YES=0
BUILD_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --execute) EXECUTE=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    --build-only) BUILD_ONLY=1 ;;
    --yes) ASSUME_YES=1 ;;   # skip the interactive confirm prompt
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"

# D-05: LXC container ids come from the single source of truth —
# system/instance/lxc_topology.json (declared range 101-117 + role anchors).
# set -euo pipefail makes a missing config a hard failure (no silent default).
TOPO_JSON="$REPO/system/instance/lxc_topology.json"
topo_anchor() {
  python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['anchors'][sys.argv[2]])" "$TOPO_JSON" "$1"
}
NUC_LXC="$(topo_anchor nucleus)"
S3S_LXC="$(topo_anchor s3star)"
G6_LXC="$(topo_anchor algedonic)"

# ── SSH ControlMaster for persistent connections to n02 ──
# Speeds up repeated ssh calls (verify steps) by reusing the same TCP socket.
setup_ssh_controlmaster() {
  local config="$HOME/.ssh/config"
  if [ ! -f "$config" ]; then
    mkdir -p "$HOME/.ssh" && touch "$config" && chmod 600 "$config"
  fi
  if grep -q 'Host n02' "$config" 2>/dev/null; then
    echo "  ✓ ControlMaster already configured for Host n02"
  else
    cat >> "$config" <<'SSHCONF'

Host n02
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 60s
SSHCONF
    echo "  ✓ ControlMaster configured for Host n02 in $config"
  fi
}

# ── Retry with exponential backoff for verification steps ──
# Wraps commands (typically ssh/pct verify calls) with up to 3 attempts
# at 2/5/10 second intervals. Deploy commands (push, stop, start) are
# NOT wrapped to avoid double-restarts on retry.
retry_with_backoff() {
  local cmd="$*" max=3 delay=2 i=0
  while (( i < max )); do
    if eval "$cmd"; then
      return 0
    fi
    ((i++))
    if (( i < max )); then
      echo "  retry $i/$max after ${delay}s..."
      sleep "$delay"
      delay=$((delay * 2))
    fi
  done
  echo "  ✗ command failed after $max attempts: $cmd"
  return 1
}

# Source is rsync'd WSL → N02_REPO (host staging) in §1; the actual cargo build
# then runs INSIDE LXC 108 (glibc 2.36 ≡ every runtime LXC). The n02 *host* is
# glibc 2.41 — a host-built binary can acquire GLIBC_2.37+ symbol requirements that
# fail to start on the 2.36 targets (101/107). Building in 108 is correct-by-construction.
N02_REPO="/home/rmw3/vsf"
BUILD_LXC="$(topo_anchor dev_sandbox)"   # glibc 2.36 ≡ runtime; NEVER build on the 2.41 host
# 108 builds incrementally in its PERSISTENT crate trees (/root/<crate>, deps already
# compiled) — a fresh tree would force a cold full-dependency build that does NOT fit
# 108's small rootfs (~7.8G). MIN_FREE_M aborts cleanly rather than wedging the disk.
MIN_FREE_M=1500
NUC_BIN_N02="$N02_REPO/projects/vsf-nucleus/target/release/vsf-nucleus"
S3S_BIN_N02="$N02_REPO/projects/vsf-s3-star/target/release/vsf-s3-star"
G6_PY_N02="$N02_REPO/scripts/algedonic/g6_algedonic_sink.py"
G6_UNIT_N02="$N02_REPO/scripts/vsf-g6-algedonic-sink.service"

# Local sources (read-only on WSL side; pushed via rsync, never built locally).
G6_PY="$REPO/scripts/algedonic/g6_algedonic_sink.py"
G6_UNIT="$REPO/scripts/algedonic/vsf-g6-algedonic-sink.service"

run() {
  echo "  $ $*"
  if [[ "$EXECUTE" -eq 1 ]]; then
    eval "$@"
  fi
}

# record_deploy <component> <target_lxc> <to_sha> <result>
# Pure I/O hook: appends one row to state.db.deploys on n02.
# Silent no-op in DRY-RUN. Failure to record never aborts the deploy.
# wait_active <lxc> <service> [max_tries]
# Polls systemctl is-active up to max_tries (default 6) at 2s intervals.
# Prevents false-abort when service is still starting after stop/start.
wait_active() {
  local lxc=$1 svc=$2 max=${3:-6} i=0
  [[ "$EXECUTE" -eq 1 ]] || return 0
  while (( i < max )); do
    if ssh -o BatchMode=yes root@n02 "pct exec $lxc -- systemctl is-active --quiet $svc" 2>/dev/null; then
      echo "  ✓ $svc active on lxc=$lxc (after ${i}x2s)"
      return 0
    fi
    sleep 2; ((i++))
  done
  echo "  ✗ $svc not active on lxc=$lxc after $((max*2))s"
  return 1
}

record_deploy() {
  local component=$1 lxc=$2 to_sha=$3 result=$4
  [[ "$EXECUTE" -eq 1 ]] || return 0
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  # .timeout 5000: state.db is shared with the n02 state collector, which can
  # hold the write lock mid-insert (SQLITE_BUSY, observed 2026-10-01) — wait
  # for it instead of dropping the deploy record.
  ssh -o BatchMode=yes -o ConnectTimeout=10 root@n02 \
    "sqlite3 -cmd '.timeout 5000' /var/lib/vsf-state/state.db \"INSERT INTO deploys(ts,component,target_lxc,from_sha,to_sha,result) VALUES('$ts','$component',$lxc,NULL,'$to_sha','$result');\"" \
    >/dev/null 2>&1 || echo "  (warn: state.db deploy record failed for $component)"
}

# ── Setup SSH ControlMaster for persistent n02 connections ──
setup_ssh_controlmaster

echo "## deploy_bundle.sh — coordinated redeploy"
echo "## mode: $([[ $EXECUTE -eq 1 ]] && echo EXECUTE || echo DRY-RUN)"
echo

# ---- 1. Sync source WSL → n02 (excluding target/) ----
echo "### 1. Sync source WSL → n02 (excluding target/, .git/)"
run "rsync -az --delete --exclude target --exclude .git '$REPO/projects/vsf-nucleus/' root@n02:'$N02_REPO/projects/vsf-nucleus/'"
run "rsync -az --delete --exclude target --exclude .git --exclude vendor '$REPO/projects/vsf-s3-star/'  root@n02:'$N02_REPO/projects/vsf-s3-star/'"
run "rsync -az --delete --exclude target --exclude .git --exclude vendor '$REPO/projects/vsf-agent/'    root@n02:'$N02_REPO/projects/vsf-agent/'"
# covenant.vsm is hashed by build.rs into COVENANT_SHA256 — sync the canonical copy
# so the in-108 build binds the same hash the runtime covenant check expects.
run "rsync -az '$REPO/docs/governance/covenant.vsm' root@n02:'$N02_REPO/docs/governance/covenant.vsm'"
run "rsync -az '$G6_PY' '$G6_UNIT' root@n02:'$N02_REPO/scripts/'"
echo

# ---- 1b. Vendor s3-star deps on n02 (internet side) if not already present ----
# LXC 108 has no internet access (intentional isolation). vendor/ is excluded from
# the rsync above so an existing vendor/ on n02 is preserved across deploys.
# On first run (or when Cargo.toml changes), vendor/ must be recreated on n02.
echo "### 1b. Vendor s3-star deps on n02 (if vendor/ absent or stale)"
run "ssh root@n02 '[ -d $N02_REPO/projects/vsf-s3-star/vendor ] && echo \"  vendor/ exists — skip\" || (cd $N02_REPO/projects/vsf-s3-star && cargo vendor vendor/ --quiet && echo \"  vendor/ created\")'"
echo

# ---- 1c. Vendor vsf-agent deps on n02 (internet side) if not already present ----
# Same pattern as s3-star: LXC 108 is internet-isolated. vendor/ excluded from rsync.
# GOTCHA: --exclude=*/target in §2 tar also strips vendor/cc/src/target/*.rs (cc crate
# generated files). After extraction we re-copy them from the n02 registry cache.
echo "### 1c. Vendor vsf-agent deps on n02 (if vendor/ absent or stale)"
run "ssh root@n02 '[ -d $N02_REPO/projects/vsf-agent/vendor ] && echo \"  vendor/ exists — skip\" || (cd $N02_REPO/projects/vsf-agent && cargo vendor vendor/ --quiet && echo \"  vendor/ created\")'"
echo

# ---- 2. Build release binaries INSIDE LXC 108 (glibc 2.36 ≡ runtime) ----
# Builds run in 108's PERSISTENT crate trees (/root/<crate>) so compiled deps are
# reused (incremental) and fit the small rootfs. Source crates (top-level names) +
# the canonical covenant are staged via a tarball pct-push'd from $N02_REPO; the
# tarball excludes target/, so each crate's warm target/ is preserved. build.rs in
# /root/vsf-nucleus resolves ../../docs/governance/covenant.vsm = /docs/governance/...
# The 108-built binaries are pct-pull'd back to the host paths §4/§5 push from.
# A disk preflight aborts cleanly if 108 lacks room (a cold s3-star build needs ~3G).
echo "### 2. Build release binaries inside LXC $BUILD_LXC (glibc 2.36 ≡ runtime; not the 2.41 host)"
if [[ "$SKIP_BUILD" -eq 1 ]]; then
  echo "  (skipped via --skip-build — using existing $NUC_BIN_N02 / $S3S_BIN_N02)"
else
  # disk preflight — never wedge 108 at 100% mid-build
  run "ssh root@n02 'avail=\$(pct exec $BUILD_LXC -- df -BM --output=avail / | tail -1 | tr -dc 0-9); echo \"  108 free: \${avail}M (need ≥ $MIN_FREE_M)\"; [ \"\${avail:-0}\" -ge $MIN_FREE_M ] || { echo \"  ABORT: insufficient space on 108. Grow it: pct resize $BUILD_LXC rootfs +20G && pct exec $BUILD_LXC -- resize2fs /dev/<rootdev>. A cold s3-star build needs ~3G; only vsf-nucleus has a warm tree today.\"; exit 3; }'"
  run "ssh root@n02 'cd $N02_REPO/projects && tar czf /tmp/vsf-crates.tgz --exclude=*/target --exclude=.git vsf-nucleus vsf-s3-star vsf-agent'"
  run "ssh root@n02 'pct push $BUILD_LXC /tmp/vsf-crates.tgz /tmp/vsf-crates.tgz'"
  run "ssh root@n02 'pct exec $BUILD_LXC -- tar xzf /tmp/vsf-crates.tgz -C /root'"   # preserves each crate's warm target/
  # GOTCHA: --exclude=*/target strips vendor/cc/src/target/*.rs (generated files that cargo
  # vendor includes but the glob also matches). Re-copy from n02 registry cache after extract.
  # Affects both vsf-s3-star and vsf-agent. cc version may change — detect dynamically.
  run "ssh root@n02 'for crate in vsf-s3-star vsf-agent; do CC_VER=\$(grep \"^version\" \$HOME/vsf/projects/\$crate/vendor/cc/Cargo.toml 2>/dev/null | head -1 | grep -oE \"[0-9]+\\.[0-9]+\\.[0-9]+\"); [ -z \"\$CC_VER\" ] && continue; CC_REG=\$(ls -d /root/.cargo/registry/src/index.crates.io-*/cc-\${CC_VER} 2>/dev/null | head -1); [ -d \"\$CC_REG/src/target\" ] || continue; pct exec $BUILD_LXC -- mkdir -p /root/\$crate/vendor/cc/src/target; for f in generated.rs apple.rs llvm.rs parser.rs; do [ -f \"\$CC_REG/src/target/\$f\" ] && pct push $BUILD_LXC \"\$CC_REG/src/target/\$f\" \"/root/\$crate/vendor/cc/src/target/\$f\"; done; echo \"  cc target/ restored for \$crate (\$CC_VER)\"; done'"
  run "ssh root@n02 'pct push $BUILD_LXC $N02_REPO/docs/governance/covenant.vsm /docs/governance/covenant.vsm'"
  run "ssh root@n02 'pct exec $BUILD_LXC -- bash -lc \"source /root/.cargo/env && cd /root/vsf-nucleus && cargo build --release\"'"
  run "ssh root@n02 'pct exec $BUILD_LXC -- bash -lc \"source /root/.cargo/env && cd /root/vsf-s3-star && cargo build --release --offline\"'"
  # pull 108-built binaries back to the host paths the deploy steps push from
  run "ssh root@n02 'mkdir -p $N02_REPO/projects/vsf-nucleus/target/release $N02_REPO/projects/vsf-s3-star/target/release'"
  run "ssh root@n02 'pct pull $BUILD_LXC /root/vsf-nucleus/target/release/vsf-nucleus $NUC_BIN_N02'"
  run "ssh root@n02 'pct pull $BUILD_LXC /root/vsf-s3-star/target/release/vsf-s3-star $S3S_BIN_N02'"
  # guard: the 108 binary must require ≤ GLIBC_2.36 (else it won't start on 101/107)
  run "ssh root@n02 'maxg=\$(objdump -T $NUC_BIN_N02 2>/dev/null | grep -oE \"GLIBC_[0-9.]+\" | sort -V | tail -1); echo \"  nucleus max symbol: \$maxg\"; case \"\$maxg\" in GLIBC_2.3[0-6]|GLIBC_2.2*|GLIBC_2.1*) : ;; *) echo \"  WARN: \$maxg may exceed runtime glibc 2.36\" ;; esac'"
fi

# Capture SHAs from n02-built binaries (or g6 source). Empty if file missing.
NUC_SHA=$(ssh root@n02 "[[ -x $NUC_BIN_N02 ]] && sha256sum $NUC_BIN_N02 | awk '{print \$1}' || echo ''" 2>/dev/null || echo "")
S3S_SHA=$(ssh root@n02 "[[ -x $S3S_BIN_N02 ]] && sha256sum $S3S_BIN_N02 | awk '{print \$1}' || echo ''" 2>/dev/null || echo "")
G6_SHA=$(ssh  root@n02 "[[ -f $G6_PY_N02  ]] && sha256sum $G6_PY_N02  | awk '{print \$1}' || echo ''" 2>/dev/null || echo "")
if [[ "$EXECUTE" -eq 1 ]] && { [[ -z "$NUC_SHA" ]] || [[ -z "$S3S_SHA" ]]; }; then
  echo "FATAL: n02 binaries missing after build (NUC_SHA='$NUC_SHA' S3S_SHA='$S3S_SHA')" >&2; exit 1
fi
echo

# ---- 2b. Build-only stop (covenant ceremony P4) ----
# Staged binaries + SHAs are exactly what §4/§5 push. Nothing below this
# line has run: no prompt, no pct push, no service restart.
if [[ "$BUILD_ONLY" -eq 1 ]]; then
  echo "### 2b. BUILD-ONLY — stopping before deploy (covenant ceremony P4)"
  echo "  nucleus sha:  ${NUC_SHA:-<none>}"
  echo "  s3-star sha:  ${S3S_SHA:-<none>}"
  echo "  verify the P4 gate (binary reports the promoted covenant hash),"
  echo "  then deploy the staged binaries with:"
  echo "    $0 --execute --skip-build --yes"
  exit 0
fi

# ---- 3. Confirm ----
if [[ "$EXECUTE" -eq 1 ]]; then
  echo "### 3. Final confirmation"
  echo "  Nucleus sha:  $NUC_SHA"
  echo "  S3-star sha:  $S3S_SHA"
  if [[ "$ASSUME_YES" -eq 1 ]]; then
    echo "  (--yes given, proceeding without prompt)"
  else
    # Read from /dev/tty explicitly so pipelines / ssh that consume stdin
    # don't swallow the answer (caused script to block when invoked as
    # `echo yes | ./deploy_bundle.sh --execute | tail -N`).
    read -r -p "  Proceed with prod redeploy? [yes/NO] " ans </dev/tty
    [[ "$ans" == "yes" ]] || { echo "aborted"; exit 1; }
  fi
fi
echo

# ---- 4. Deploy nucleus (LXC $NUC_LXC) ----
# n02-native: pct push directly from n02 host filesystem; no scp step.
echo "### 4. Deploy nucleus → LXC $NUC_LXC (paired with #110)"
run "ssh root@n02 'pct push $NUC_LXC $NUC_BIN_N02 /root/vsf-nucleus-operational.new -perms 755'"
run "retry_with_backoff ssh root@n02 'pct exec $NUC_LXC -- sha256sum /root/vsf-nucleus-operational.new'"
run "ssh root@n02 'pct exec $NUC_LXC -- systemctl stop vsf-nucleus-operational'"
run "ssh root@n02 'pct exec $NUC_LXC -- mv -f /root/vsf-nucleus-operational.new /root/vsf-nucleus-operational'"
run "ssh root@n02 'pct exec $NUC_LXC -- systemctl reset-failed vsf-nucleus-operational; pct exec $NUC_LXC -- systemctl start vsf-nucleus-operational'"
wait_active "$NUC_LXC" vsf-nucleus-operational
record_deploy vsf-nucleus-operational "$NUC_LXC" "$NUC_SHA" ok
# SHA_DRIFT fix: update coupling manifest with new binary SHA
run "python3 $REPO/scripts/shared/update_manifest_sha.py $REPO/scripts/state/coupling_manifests/vsf-nucleus-operational.coupling.json $NUC_SHA"
echo

# ---- 5. Deploy s3-star (LXC $S3S_LXC) ----
echo "### 5. Deploy s3-star → LXC $S3S_LXC (paired with #105 shared-crate binary)"
run "ssh root@n02 'pct push $S3S_LXC $S3S_BIN_N02 /usr/local/bin/vsf-s3-star.new -perms 755'"
run "retry_with_backoff ssh root@n02 'pct exec $S3S_LXC -- sha256sum /usr/local/bin/vsf-s3-star.new'"
run "ssh root@n02 'pct exec $S3S_LXC -- systemctl stop vsf-s3-star'"
run "ssh root@n02 'pct exec $S3S_LXC -- mv -f /usr/local/bin/vsf-s3-star.new /usr/local/bin/vsf-s3-star'"
run "ssh root@n02 'pct exec $S3S_LXC -- systemctl reset-failed vsf-s3-star; pct exec $S3S_LXC -- systemctl start vsf-s3-star'"
wait_active "$S3S_LXC" vsf-s3-star
record_deploy vsf-s3-star "$S3S_LXC" "$S3S_SHA" ok
# SHA_DRIFT fix: update coupling manifest with new binary SHA
run "python3 $REPO/scripts/shared/update_manifest_sha.py $REPO/scripts/state/coupling_manifests/vsf-s3-star.coupling.json $S3S_SHA"
echo

# ---- 6. Deploy g6_sink (LXC $G6_LXC) ----
# Source was rsync'd in §1; pct push directly from N02_REPO/scripts/.
echo "### 6. Deploy G6 algedonic sink → LXC $G6_LXC"
run "ssh root@n02 'pct push $G6_LXC $G6_PY_N02   /usr/local/bin/g6_algedonic_sink.py -perms 755'"
run "ssh root@n02 'pct push $G6_LXC $G6_UNIT_N02 /etc/systemd/system/vsf-g6-algedonic-sink.service'"
run "ssh root@n02 'pct exec $G6_LXC -- mkdir -p /alerts'"
run "ssh root@n02 'pct exec $G6_LXC -- systemctl daemon-reload'"
run "ssh root@n02 'pct exec $G6_LXC -- systemctl enable --now vsf-g6-algedonic-sink.service'"
wait_active "$G6_LXC" vsf-g6-algedonic-sink.service
record_deploy vsf-g6-algedonic-sink "$G6_LXC" "$G6_SHA" ok
echo

# ---- 7. Post-deploy verification ----
echo "### 7. Post-deploy verification"
echo "  - the next event emitted by the nucleus uses shared vsf_agent serialisation"
echo "  - s3-star ingest counter should resume and emit cycle_summary as before"
echo "  - g6 sink should write a line to /alerts/operator_inbox.log on the next algedonic"
echo "  - recovery_exercise.sh can now be run safely against the new binaries"
echo
echo "### 8. Suggested next operator actions"
echo "  ./scripts/s1-kernel/recovery_exercise.py --gate g3   # NATS reconnect probe"
echo "  ./scripts/s1-kernel/recovery_exercise.py --gate g4   # nucleus crash-resume probe"
echo "  ./scripts/s1-kernel/recovery_exercise.py --gate g5   # hot-reload probe"
echo

if [[ "$EXECUTE" -ne 1 ]]; then
  echo "(no changes were made — rerun with --execute to perform)"
fi
