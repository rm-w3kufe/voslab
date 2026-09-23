# S3 covenant seed — LXC 107 (s3star-audit)

## What
On-demand covenant evaluator (A0/A0.1 + TRUST + A5) + hourly self-test.
NOT a daemon loop: enforcement capability deployed, invoked per event.

## Layout on 107
- /opt/vsf-covenant/covenant_cli.py — CLI (evaluate/selftest)
- /opt/vsf-covenant/vos_kernel/ — package (stdlib-only, python backend)
- /opt/vsf-covenant/covenant.vsm — policy reference
- /etc/systemd/system/vsf-covenant-selftest.{service,timer}

## Deploy
pct push 107 <file> <dest> (see deploy.sh) + systemctl enable --now timer

## Verify
pct exec 107 -- python3 /opt/vsf-covenant/covenant_cli.py selftest
pct exec 107 -- systemctl is-active vsf-covenant-selftest.timer
pct exec 107 -- journalctl -u vsf-covenant-selftest --no-pager -n 5

## Rollback
pct exec 107 -- systemctl disable --now vsf-covenant-selftest.timer
pct exec 107 -- rm -rf /opt/vsf-covenant /etc/systemd/system/vsf-covenant-selftest.*
