#!/bin/bash
# design: docs/plans/ergo_batches_adopted.vsm
# route: cli/manual — ssh batch defaults (DISTILL batch-1 adopted)
# Wrapper con defaults por invocacion; NO escribe ~/.ssh/config global.
# usage: sshq.sh <host> [command...]
# e.g. verify remota rapida: sshq.sh n02 "systemctl is-active ssh"
exec ssh -o BatchMode=yes -o ConnectTimeout=15 "$@"
