#!/usr/bin/env python3
"""
Reporte climático comparativo: Isla de Pascua y Galápagos.
"""
import json, os, sys
from datetime import datetime, timezone

MARKOV_DIR = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/vsf-clima/markov"
K = 5
BINS = ["OPTIMAL", "HEALTHY", "DRIFTING", "EXCURSION", "SEVERE"]

ZONAS = [
    ("Isla de Pascua (Rapa Nui, 27°S)", "s1-easter-island.json"),
    ("Galápagos (Ecuador, 0°S)", "s1-galapagos.json"),
]


def pe(T, bin_id):
    idx = K - bin_id
    return T[idx][K - 1] + T[idx][K - 2]


def distribucion_estacionaria(T):
    pi = [1.0 / K] * K
    for _ in range(1000):
        pi = [sum(pi[i] * T[i][j] for i in range(K)) for j in range(K)]
        s = sum(pi)
        pi = [p / s for p in pi]
    return pi


def proyeccion(T, current_bin, h):
    v = [0.0] * K
    v[K - current_bin] = 1.0
    for _ in range(h):
        v = [sum(v[i] * T[i][j] for i in range(K)) for j in range(K)]
    return v[K - 2] + v[K - 1]


ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

print()
print("╔" + "═" * 70 + "╗")
print("║" + "  REPORTE CLIMÁTICO — ISLAS DEL PACÍFICO".center(68) + "║")
print("║" + f"  Generado: {ts}".center(68) + "║")
print("╚" + "═" * 70 + "╝")

for zona_nombre, fname in ZONAS:
    path = os.path.join(MARKOV_DIR, fname)
    if not os.path.exists(path):
        print(f"\n  ⚠ No se encuentra {fname}")
        continue

    with open(path) as f:
        T = json.load(f)["T"]

    pi = distribucion_estacionaria(T)
    
    # Datos de la diagonal
    p_opt_opt = T[K - 5][K - 5]
    p_sev_sev = T[K - 1][K - 1]
    p_recup = T[K - 1][K - 2] + T[K - 1][K - 3]
    p_deterioro = T[K - 5][K - 2] + T[K - 5][K - 1]
    p_mejoria = T[K - 4][K - 3] + T[K - 4][K - 4]
    p_critico = pi[K - 2] + pi[K - 1]  # EXCURSION + SEVERE

    print()
    print("=" * 72)
    print(f"  {zona_nombre}")
    print("=" * 72)

    # Matriz T
    print(f"\n  Matriz de Transición (5 estados):")
    print(f"  {'':>12s}  {'→b5':>7s} {'→b4':>7s} {'→b3':>7s} {'→b2':>7s} {'→b1':>7s}")
    for i, row in enumerate(T):
        print(f"  Desde {BINS[i]:>9s} (b{K-i})  " + " ".join(f"{p:7.4f}" for p in row))

    # P(E) por bin
    print(f"\n  P(Excursión en 1 paso):")
    for bin_id in [5, 4, 3, 2, 1]:
        p = pe(T, bin_id)
        print(f"    {BINS[K-bin_id]:>9s} (b{bin_id}):  {p:.1%}")

    # Distribución estacionaria
    print(f"\n  Distribución estacionaria (% del tiempo):")
    for i in range(K):
        pct = pi[i] * 100
        barra = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
        print(f"    {BINS[i]:>9s} (b{K-i}):  {pct:5.1f}%  {barra}")

    # Proyección
    print(f"\n  Proyección P(E) a distintos horizontes:")
    print(f"    {'Desde':>12s}  {'h=1':>7s}  {'h=7':>7s}  {'h=30':>7s}")
    for bin_id in [5, 4, 3, 2, 1]:
        p1 = pe(T, bin_id)
        p7 = proyeccion(T, bin_id, 7)
        p30 = proyeccion(T, bin_id, 30)
        print(f"    {BINS[K-bin_id]:>9s} (b{bin_id}):  {p1:.1%}  {p7:.1%}  {p30:.1%}")

    # Interpretación
    print(f"\n  Interpretación:")
    print(f"    Persistencia OPTIMAL→OPTIMAL:   {p_opt_opt:.1%}")
    print(f"    Persistencia SEVERE→SEVERE:     {p_sev_sev:.1%}")
    print(f"    Recuperación SEVERE→HEALTHY+:   {p_recup:.1%}")
    print(f"    Colapso OPTIMAL→EXCURSIÓN+:     {p_deterioro:.1%}")
    print(f"    Mejoría desde HEALTHY:           {p_mejoria:.1%}")
    print(f"    Días/año en crisis (estacionario): {p_critico * 365:.0f} días")

    # Interpretación climática
    print()
    if "Pascua" in zona_nombre:
        print(f"  Clima: Subtropical oceánico. Temperaturas moderadas todo el año")
        print(f"  (18-28°C). Fuertemente influenciado por la corriente de Humboldt")
        print(f"  y los vientos alisios del SE. La variabilidad climática está")
        print(f"  dominada por la Oscilación del Sur (ENSO).")
    elif "Galápagos" in zona_nombre:
        print(f"  Clima: Ecuatorial oceánico, con influencia de 3 corrientes:")
        print(f"  Humboldt (fría), Cromwell (subsuperficial fría), y Panamá (cálida).")
        print(f"  La temperatura varía poco (~22-30°C), pero las lluvias son")
        print(f"  fuertemente moduladas por ENOS (El Niño → lluvias intensas).")

    if p_deterioro < 0.05:
        print(f"  ✅ Muy estable: casi nunca colapsa desde OPTIMAL.")
    elif p_deterioro < 0.10:
        print(f"  ⚠ Estabilidad moderada: ocasionalmente puede caer abruptamente.")
    else:
        print(f"  ❌ Alta volatilidad: colapsos frecuentes desde estabilidad.")

    if p_recup > 0.60:
        print(f"  ✅ Alta resiliencia: se recupera rápido desde crisis.")
    elif p_recup > 0.40:
        print(f"  ⚠ Resiliencia media: tarda en recuperarse de crisis.")
    else:
        print(f"  ❌ Baja resiliencia: tiende a permanecer en crisis.")

# Comparación
print()
print("=" * 72)
print("  COMPARATIVA: PASCUA vs GALÁPAGOS vs ZONA CENTRAL")
print("=" * 72)
print(f"  {'Métrica':>35s}  {'Pascua':>8s}  {'Galápagos':>8s}  {'Central':>8s}")
print(f"  {'-'*35}  {'-'*8}  {'-'*8}  {'-'*8}")

for label, fnames in [
    ("P(E|OPTIMAL)",     ["s1-easter-island.json", "s1-galapagos.json", "s1-santiago.json"]),
    ("P(E|DRIFTING)",    ["s1-easter-island.json", "s1-galapagos.json", "s1-santiago.json"]),
    ("P(E|SEVERE)",      ["s1-easter-island.json", "s1-galapagos.json", "s1-santiago.json"]),
    ("% tiempo crítico", ["s1-easter-island.json", "s1-galapagos.json", "s1-santiago.json"]),
]:
    vals = []
    for fn in fnames:
        with open(os.path.join(MARKOV_DIR, fn)) as f:
            T = json.load(f)["T"]
        if "P(E" in label:
            bin_id = 5 if "OPTIMAL" in label else (3 if "DRIFTING" in label else 1)
            vals.append(f"{pe(T, bin_id):.1%}")
        else:
            pi = distribucion_estacionaria(T)
            vals.append(f"{(pi[K-2] + pi[K-1])*100:.0f}%")
    print(f"  {label:>35s}  {vals[0]:>8s}  {vals[1]:>8s}  {vals[2]:>8s}")

print()
print("=" * 72)
print("  AVISO — LÍMITES DE ESTE MODELO (leer antes de interpretar)")
print("=" * 72)
print()
print("  Esto es CLIMATOLOGÍA ESTADÍSTICA, no un pronóstico meteorológico.")
print("  Es una tabla actuarial: da TASAS BASE históricas, no predice eventos.")
print()
print("  - Entrenado en ERA5 1991-2020: NO conoce eventos futuros concretos")
print("    (un El Niño o un evento de lluvia entrante NO aparece en este modelo).")
print("  - Horizonte predictivo real ~1 día: a 7 días la proyección converge a la")
print("    tasa base (~20% desde CUALQUIER estado) — la cadena mezcla más rápido")
print("    que el horizonte, así que el 'pronóstico a 7 días' es solo el promedio")
print("    histórico, sin memoria del estado inicial.")
print("  - Análisis ESTRUCTURAL, no en vivo: transiciones desde cada estado posible,")
print("    no 'dónde estamos hoy'.")
print("  - 'Excursión' = cuantil estadístico bajo de la viabilidad (bins 1-2), NO un")
print("    desastre meteorológico.")
print()
print("  Uso correcto: entender el RÉGIMEN estadístico ENOS de una zona. NO sirve")
print("  para pronosticar la lluvia de la próxima semana — para eso, un modelo")
print("  meteorológico, no éste.")
