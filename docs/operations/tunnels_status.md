# SSH Tunnels — Operational Status

**Last verified:** 2026-05-25 ~20:47 local (2026-05-26 00:47 UTC)
**Source of config:** `~/.ssh/config`
**Note:** "vsf-tunnels" is NOT a script — it's the collection of `Host` entries
in `~/.ssh/config` that LocalForward LXC services to localhost. To open a
tunnel: `ssh -N -f <host-name>`. To close: `pkill -f "ssh -N -f <host-name>"`.

## Live tunnels (this session)

| Tunnel | Local port | Upstream | Service | Status |
|---|---|---|---|---|
| `n02-all` | 8006, 8080, 19999 | n02 host | Proxmox UI + opsroom + Netdata | ✅ |
| `n02-jupyter` | 8888 | n02:127.0.0.1:8888 | Jupyter | ⚠ tunnel up, server unverified |
| `n02-s5console` | 8090 | LXC 104:8090 | S5 Console dashboard | ✅ |
| `n02-nats` | 4222, 8222 | LXC 106:4222 (NATS) + :8222 (monitor) | NATS broker testbed | ✅ STARTED THIS SESSION |

## Available but not started (start with `ssh -N -f <host>`)

| Host | Forwards | Why you'd use it |
|---|---|---|
| `n02-web` | 8006 → Proxmox | Redundant with `n02-all`, single-port version |
| `n02-opsroom` | 8080 → opsroom dashboard | Only if not using `n02-all` |
| `n02-netdata` | 19999 → Netdata | Only if not using `n02-all` |
| `n02-tunnel` | (jump-host config) | For `ssh -J n02-tunnel` chained access |
| `n02-hop` | (jump-host with ProxyCommand) | Used by `kali`, `bbh-prod` |
| `kali`, `bbh-prod` | jumps through n02-hop | Access LXCs directly |

## Verified upstream services (this session)

| Upstream | LISTEN status | Probed from |
|---|---|---|
| n02:8006 (Proxmox) | ✅ pveproxy active | host ss -tln |
| n02:19999 (Netdata) | ✅ active | host ss -tln |
| LXC 104:8090 (S5 Console) | ✅ active | pct exec 104 ss |
| LXC 106:4222 (NATS) | ✅ active | pct exec 106 ss |
| LXC 106:8222 (NATS monitor) | ✅ active | pct exec 106 ss |
| n02:8080 (opsroom) | ✗ not running | host ss |
| n02:8888 (Jupyter) | ✗ not running | host ss |

## End-to-end smoke test (NATS)

```python
import socket, json, time
s = socket.socket(); s.connect(("127.0.0.1", 4222))
s.recv(4096)  # INFO line
s.sendall(b'CONNECT {"verbose":false}\r\n'); time.sleep(0.1)
payload = json.dumps({"event_type":"phase_complete","system_id":"bbh",
                       "metrics":{"phase":"B2_ACTIVE"}})
s.sendall(f"PUB bbh.smoke.phi_up.phase_complete {len(payload)}\r\n{payload}\r\n".encode())
```

Should appear in LXC 101 `/var/lib/vsf/vsf_nucleus/events.jsonl` within ~1s.
This is the BBH publisher contract validated path.

## How to start/stop a tunnel

```bash
ssh -N -f <host>                              # background
pkill -f "ssh -N -f <host>"                   # stop
ps aux | grep "ssh -N -f" | grep -v grep      # list active
```

## Lifecycle gotchas

- WSL ↔ network bridge can drop tunnels on resume from sleep — re-run `ssh -N -f` if forwards stop.
- `ssh -N -f n02-all` survives WSL hibernation longer than per-tunnel processes.
- Auto-restart: not implemented (could use systemd user units, deferred).

## References

- `~/.ssh/config` — authoritative tunnel definitions
- `bbh_publisher_contract.md` §1 — uses `nats://10.10.20.20:4222` upstream OR local `nats://127.0.0.1:4222` via this tunnel
- `docs/operational/k_measurement_protocol_2026-05-25.md` §2.2 — events.jsonl ingestion path
