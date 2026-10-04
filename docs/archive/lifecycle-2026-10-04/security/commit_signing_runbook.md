# Commit Signing Runbook — closes pre-deploy checklist Z2 + Z4
> **STATUS: historical_record** — consumido por fuse INFRA-OPS → infra_ops.vsm (Z2/Z4, 6 refs) · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

> Status: DONE 2026-06-13 — Path B (GPG) executed. Key ed25519:4DB8803749D523AF [SC] exp 2028-06-12.
> Two UIDs: "Luis Pineda <rmw3kufe@proton.me>" + "rmw3kufe <rmw3kufe@users.noreply.github.com>".
> Probe commit 2b74844 verified "Good signature". Z2+Z4 PASS.
> OPERATOR: upload /tmp/vsf_gpg_pubkey.asc → GitHub Settings → SSH and GPG keys → New GPG key.
> Source task: `TASKS.vsm task(Z)` Z2 (signed commits) + Z4 (signed release tags).
> Goal (XZ-lessons): every commit + release tag carries a cryptographic author proof
> verifiable on GitHub, so a forged/injected commit is detectable.

The machine has **no GPG key** today but **does** have SSH keys (`~/.ssh/github_vsf`,
`vsf_n01`, …). Git ≥ 2.34 can sign with **either** GPG or an SSH key. Pick ONE method
below — both satisfy Z2/Z4 and both show "Verified" on GitHub.

---

## DECISION: SSH signing (recommended) vs GPG

| | SSH signing | GPG |
|---|---|---|
| Key | reuse/generate an **ed25519 SSH** key | generate an **ed25519 GPG** key |
| Ceremony | minimal (no keyring/passphrase agent dance) | keyring + agent + expiry mgmt |
| GitHub | upload pubkey as a **Signing Key** | upload ASCII-armored public key |
| Checklist literal | satisfies intent of Z2/Z4 | matches Z2 wording verbatim |
| Portability | git/GitHub/Gitea | broadest (also email, releases elsewhere) |

Recommendation for a solo private→public repo: **SSH signing**, reusing an ed25519
key. Less to maintain, same verification guarantee. GPG only if you want the broader
ecosystem (signed email, non-GitHub release infra).

First check whether `github_vsf` is ed25519 (preferred) or RSA:
```bash
ssh-keygen -lf ~/.ssh/github_vsf.pub      # look for "ED25519"; if "RSA", generate a fresh ed25519 below
```

---

## Path A — SSH signing (recommended)

```bash
# 0. (only if github_vsf is NOT ed25519) generate a dedicated signing key:
ssh-keygen -t ed25519 -C "vsf-signing rmw3kufe@proton.me" -f ~/.ssh/vsf_signing

# 1. point git at the signing key (use github_vsf.pub if it is ed25519, else vsf_signing.pub)
SIGNKEY=~/.ssh/github_vsf.pub
git config --global gpg.format ssh
git config --global user.signingkey "$SIGNKEY"
git config --global commit.gpgsign true
git config --global tag.gpgsign true

# 2. local verification db (so `git log --show-signature` validates your own commits)
mkdir -p ~/.config/git
echo "rmw3kufe@proton.me $(cat "$SIGNKEY")" >> ~/.config/git/allowed_signers
git config --global gpg.ssh.allowedSignersFile ~/.config/git/allowed_signers

# 3. GitHub → Settings → SSH and GPG keys → New SSH key → Key type: **Signing Key**
#    (this is SEPARATE from your auth key, even if the key value is the same)

# 4. verify
git commit --allow-empty -m "test: signed commit probe"
git log --show-signature -1        # expect: "Good \"git\" signature for rmw3kufe@proton.me"
```

## Path B — GPG (checklist-literal)

```bash
# 1. generate an ed25519 GPG key (choose "ECC sign+encrypt", curve 25519, identity rmw3kufe@proton.me)
gpg --full-generate-key

# 2. find the long key id
gpg --list-secret-keys --keyid-format=long      # KEYID = the 16 hex after "ed25519/"

# 3. configure git
git config --global user.signingkey <KEYID>
git config --global commit.gpgsign true
git config --global tag.gpgsign true

# 4. export public key → GitHub → Settings → SSH and GPG keys → New GPG key
gpg --armor --export <KEYID>

# 5. verify
git commit --allow-empty -m "test: signed commit probe"
git log --show-signature -1
```

---

## Z4 — signed release tags (either method)

Once signing is configured, tags are signed automatically (`tag.gpgsign true`), or
explicitly:
```bash
git tag -s v1.0 -m "VSF v1.0"
git tag --verify v1.0
```

## Key storage note (consistency with the offline S5 CA)

The S5 CA root lives on WSL + USB (memory `project_s5_ca`). The commit-signing key is a
DIFFERENT, lower-criticality key (author proof, not a trust root) — WSL `~/.ssh` is
fine; no USB ceremony needed. Do NOT reuse the S5 CA root for commit signing.

## After execution — close the checklist

Update `TASKS.vsm task(Z)`: Z2 + Z4 → PASS, and note the method + key fingerprint in
`docs/security/pre_deploy_checklist.vsm`. Then the only remaining public-release gates
are Z5 (cargo-audit) + Z8 + the BFG history review (task G public).
