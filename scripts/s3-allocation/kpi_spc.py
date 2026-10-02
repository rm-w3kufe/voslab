"""kpi_spc.py — EWMA + CUSUM per-variable SPC for Cyberfilter F3.c.

Reads KPI manifests from kpi_manifests.json; persists CUSUM/EWMA state to
spc_state.json. Called by s3star_kpi.py after threshold comparison.

CUSUM lower: detects sustained downward drift below expected_min.
  S- = max(0, S-_prev + (expected_min - cusum_k - X_t))
  Exception when S- > cusum_h; reset S- and enter cooldown.

CUSUM upper: detects sustained upward drift above expected_max.
  S+ = max(0, S+_prev + (X_t - expected_max - cusum_k))
  Exception when S+ > cusum_h; reset S+ and enter cooldown.

No-storm: cooldown_ticks suppresses re-triggering after each exception.
"""
import json
import os

MANIFESTS_PATH = os.environ.get('VSF_KPI_MANIFESTS', '/root/vsf-scripts/kpi_manifests.json')
SPC_STATE_PATH = os.environ.get('VSF_SPC_STATE',    '/var/lib/vsf/s3_star/spc_state.json')


def _load_manifests() -> list:
    try:
        with open(MANIFESTS_PATH, encoding='utf-8') as fh:
            data = json.load(fh)
        return data.get('manifests', [])
    except (OSError, json.JSONDecodeError):
        return []


def _load_state() -> dict:
    try:
        with open(SPC_STATE_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(SPC_STATE_PATH), exist_ok=True)
    with open(SPC_STATE_PATH, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, indent=2)


def check_all(component: str, values: dict) -> list:
    """Run EWMA+CUSUM SPC for all manifested KPIs of the given component.

    Returns list of (variable, reason) tuples — one per exception raised.
    Cooldown ensures at most one exception per variable per cooldown window.
    """
    manifests = [m for m in _load_manifests() if m.get('component') == component]
    if not manifests:
        return []

    state = _load_state()
    exceptions = []

    for m in manifests:
        var = m['variable']
        x   = values.get(var)
        if x is None:
            continue

        alpha     = m.get('ewma_alpha',      0.2)
        direction = m.get('cusum_direction', 'lower')
        k         = m.get('cusum_k',         0.01)
        h         = m.get('cusum_h',         0.05)
        exp_min   = m.get('expected_min',    0.0)
        exp_max   = m.get('expected_max',    1.0)
        cooldown  = m.get('cooldown_ticks',  5)

        key = f'{component}:{var}'
        s = state.get(key, {'ewma': float(x), 's_minus': 0.0, 's_plus': 0.0, 'cooldown': 0})

        # EWMA update (always runs, even during cooldown)
        z = alpha * float(x) + (1.0 - alpha) * s['ewma']
        s['ewma'] = z

        # Cooldown: suppress exception, just tick down
        if s.get('cooldown', 0) > 0:
            s['cooldown'] -= 1
            state[key] = s
            continue

        if direction == 'lower':
            s_minus = max(0.0, s['s_minus'] + (exp_min - k - float(x)))
            s['s_minus'] = s_minus
            s['s_plus']  = 0.0
            if s_minus > h:
                exceptions.append((
                    var,
                    f'CUSUM-lower S-={s_minus:.4f}>h={h} Z={z:.4f} floor={exp_min}',
                ))
                s['s_minus']  = 0.0
                s['cooldown'] = cooldown
        else:
            s_plus = max(0.0, s['s_plus'] + (float(x) - exp_max - k))
            s['s_plus']  = s_plus
            s['s_minus'] = 0.0
            if s_plus > h:
                exceptions.append((
                    var,
                    f'CUSUM-upper S+={s_plus:.4f}>h={h} Z={z:.4f} ceil={exp_max}',
                ))
                s['s_plus']   = 0.0
                s['cooldown'] = cooldown

        state[key] = s

    _save_state(state)
    return exceptions


def reset_state(component: str = None) -> None:
    """Clear SPC state (for testing or after major system change)."""
    if component is None:
        _save_state({})
        return
    state = _load_state()
    keys_to_del = [k for k in state if k.startswith(f'{component}:')]
    for k in keys_to_del:
        del state[k]
    _save_state(state)
