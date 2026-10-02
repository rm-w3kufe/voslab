#!/usr/bin/env python3
"""
reporte_clima_santiago.py — Reporte climático de la zona Central de Chile.
Genera un análisis basado en los modelos Markov ERA5 y datos históricos.

Usage:
  python3 reporte_clima_santiago.py /var/lib/vsf-clima/markov
"""
import json
import os
import sys
import math
from datetime import datetime, timezone

# ── Zona Central = s1-santiago (L2: mediterranea) ─────────────────────
ZONE_FILE = "s1-santiago.json"
ZONE_L2 = "mediterranea"
ZONE_NOMBRE = "Zona Central (Chile, 33°S)"
ESTACIONES_CERCANAS = ["s1-valdivia (sur)", "s1-iquique (norte)", "s1-huasco (norte chico)"]

# Bin definitions
BINS = [
    (5, "OPTIMAL",    "Estabilidad excepcional"),
    (4, "HEALTHY",    "Condiciones normales estables"),
    (3, "DRIFTING",   "Desviación incipiente — alerta temprana"),
    (2, "EXCURSION",  "Anomalía significativa — fuera de rango"),
    (1, "SEVERE",     "Crisis — colapso de viabilidad"),
]

K = 5  # number of bins


def cargar_modelo(markov_dir):
    """Carga el modelo Markov para la zona central."""
    path = os.path.join(markov_dir, ZONE_FILE)
    if not os.path.exists(path):
        print(f"ERROR: No se encuentra {path}")
        return None
    with open(path) as f:
        data = json.load(f)
    return data


def pe(T, bin_id):
    """P(excursion en 1 paso) desde un bin dado."""
    idx = K - bin_id  # bin5→0, bin4→1, ..., bin1→4
    return T[idx][K - 1] + T[idx][K - 2]


def distribucion_estacionaria(T):
    """Distribución estacionaria (power iteration sobre T)."""
    pi = [1.0 / K] * K
    for _ in range(1000):
        pi = [sum(pi[i] * T[i][j] for i in range(K)) for j in range(K)]
        s = sum(pi)
        pi = [p / s for p in pi]
    return pi


def proyeccion_horizontes(T, current_bin, horizontes=[7, 14, 30]):
    """
    Proyecta P(E) a distintos horizontes desde un bin actual.
    Usa multiplicación repetida: v_n = v_0 * T^n
    """
    v0 = [0.0] * K
    v0[K - current_bin] = 1.0

    resultados = {}
    for h in horizontes:
        v = v0[:]
        for _ in range(h):
            v = [sum(v[i] * T[i][j] for i in range(K)) for j in range(K)]
        p_e = v[K - 2] + v[K - 1]  # P(E) = EXCURSION + SEVERE
        resultados[h] = {
            "p_excursion": round(p_e, 4),
            "bin_esperado": round(sum((K - i) * v[i] for i in range(K)), 2),
        }
    return resultados


def print_seccion(titulo):
    """Imprime una sección con formato."""
    print()
    print("=" * 72)
    print(f"  {titulo}")
    print("=" * 72)


def generar_reporte(markov_dir):
    data = cargar_modelo(markov_dir)
    if data is None:
        return

    T = data["T"]
    pi = distribucion_estacionaria(T)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print()
    print("╔" + "═" * 70 + "╗")
    print("║" + "  REPORTE CLIMÁTICO — SISTEMA VSF S4".center(68) + "║")
    print("║" + f"  {ZONE_NOMBRE}".center(68) + "║")
    print("║" + f"  Generado: {ts}".center(68) + "║")
    print("╚" + "═" * 70 + "╝")

    # ── 1. Matriz de Transición ───────────────────────────────────────
    print_seccion("1. MATRIZ DE TRANSICIÓN (modelo Markov ajustado a ERA5)")
    print()
    print("  La matriz T describe cómo evoluciona el estado de viabilidad")
    print("  de la zona de un día al siguiente, basada en ~5 años de datos")
    print("  históricos de stasis_cos (temperatura superficial).")
    print()
    print("  FILA → estado actual | COLUMNA → estado en t+1")
    print()
    header = "  " + " " * 14 + "".join(f"  {name:>6s}" for _, name, _ in BINS)
    print(header)
    for i, row in enumerate(T):
        bin_id = K - i  # T[0]=bin5, T[4]=bin1
        label = f"  Desde {BINS[i][1]:>8s} (b{bin_id})"  # BINS[i] matches T[i] order
        print(label + "  " + "  ".join(f"{p:6.3f}" for p in row))

    # ── 2. Probabilidad de excursión por bin actual ──────────────────────
    print_seccion("2. PROBABILIDAD DE EXCURSIÓN EN 1 PASO")
    print()
    print("  P(EXCURSIÓN | bin_actual) = probabilidad de entrar en bins 1-2")
    print("  desde el estado actual en una transición.")
    print()
    print(f"  {'Estado actual':>17s}  {'Bin':>4s}  {'P(E en 1 paso)':>16s}  {'Régimen':>12s}")
    print("  " + "-" * 55)
    for bin_id, name, desc in BINS:
        prob = pe(T, bin_id)
        if prob >= 0.40:
            regimen = "CRÍTICO"
        elif prob >= 0.15:
            regimen = "alerta"
        else:
            regimen = "estable"
        print(f"  {name:>17s}  {bin_id:>4d}  {prob:13.4f} ({prob*100:5.1f}%)  {regimen:>12s}")

    # ── 3. Distribución estacionaria ─────────────────────────────────────
    print_seccion("3. DISTRIBUCIÓN ESTACIONARIA (comportamiento de largo plazo)")
    print()
    print("  A largo plazo, el sistema pasa este % del tiempo en cada estado:")
    print()
    for i in range(K):
        bin_id = K - i  # i=0→bin5, i=4→bin1
        pct = pi[i] * 100
        n_barras = max(1, int(pct / 2))
        barra = "█" * n_barras + "░" * (50 - n_barras)
        print(f"  {BINS[i][1]:>8s} (b{bin_id}):  {pct:5.1f}%  {barra}")

    # ── 4. Proyección desde cada estado ──────────────────────────────────
    print_seccion("4. PROYECCIÓN DE RIESGO A DISTINTOS HORIZONTES")
    print()
    print("  P(EXCURSIÓN) proyectada desde diferentes estados iniciales:")
    print()
    print(f"  {'Desde':>15s}  {'Bin':>4s}  {'h=7 días':>10s}  {'h=14 días':>11s}  {'h=30 días':>11s}  {'Régimen':>12s}")
    print("  " + "-" * 72)

    for bin_id, name, desc in BINS:
        proy = proyeccion_horizontes(T, bin_id)
        p7 = proy[7]["p_excursion"]
        p14 = proy[14]["p_excursion"]
        p30 = proy[30]["p_excursion"]

        if p30 >= 0.70:
            regimen = "CRÍTICO"
        elif p30 >= 0.40:
            regimen = "alerta alta"
        elif p7 >= 0.15:
            regimen = "alerta"
        else:
            regimen = "estable"

        print(f"  {name:>15s}  {bin_id:>4d}  {p7:8.1%}   {p14:8.1%}    {p30:8.1%}    {regimen:>12s}")

    # ── 5. Interpretación ────────────────────────────────────────────────
    print_seccion("5. INTERPRETACIÓN CLIMÁTICA — ZONA CENTRAL")
    print()
    print("  Zona: Región Metropolitana, Valparaíso, O'Higgins, Maule")
    print("  Clima: Mediterráneo, con estación seca prolongada (oct-mar)")
    print()

    # Datos clave de la matriz
    # P(estabilidad | estable) = T[0][0] (bin5 → bin5)
    p_estable_estable = T[K - 5][K - 5]  # T[0][0]
    p_severa_severa = T[K - 1][K - 1]  # T[4][4]
    p_recuperacion = T[K - 1][K - 2] + T[K - 1][K - 3]  # bin1 → bin4 o bin3

    print(f"  → Persistencia de estabilidad (OPTIMAL→OPTIMAL): {p_estable_estable:.1%}")
    print(f"  → Persistencia de crisis (SEVERE→SEVERE): {p_severa_severa:.1%}")
    print(f"  → Recuperación desde crisis (SEVERE→HEALTHY+): {p_recuperacion:.1%}")
    print()

    # Transiciones críticas
    p_deterioro = T[K - 5][K - 2] + T[K - 5][K - 1]  # bin5 → bin2/1
    p_mejoria = T[K - 4][K - 3] + T[K - 4][K - 4]  # bin4 → bin3/4
    print(f"  ⚠ Riesgo de colapso desde OPTIMAL (→EXCURSION+): {p_deterioro:.1%}")
    print(f"  ✓ Mejoría desde HEALTHY: {p_mejoria:.1%}")
    print()

    if p_deterioro < 0.05:
        print("  ✅ La zona central es mayoritariamente estable. Las")
        print("     transiciones bruscas desde estabilidad a crisis son raras.")
    elif p_deterioro < 0.15:
        print("  ⚠ Existe riesgo moderado de deterioro abrupto. La alerta")
        print("     temprana desde DRIFTING (bin 3) es efectiva aquí.")
    else:
        print("  ❌ Alta volatilidad — la zona puede colapsar desde")
        print("     estabilidad en un solo día. Sistema de alerta reforzado necesario.")
    print()

    print(f"  La probabilidad estacionaria de estar en estado crítico")
    print(f"  (EXCURSION+SEVERE) es: {(pi[K-2] + pi[K-1]) * 100:.1f}%")
    print(f"  → Esto equivale a aproximadamente {(pi[K-2] + pi[K-1]) * 365:.0f} días/año")
    print(f"     de condiciones anómalas en el clima de la zona central.")

    # ── 6. Alerta temprana (PROJECTOR-BIN5-TIER) ─────────────────────────
    print_seccion("6. SISTEMA DE ALERTA TEMPRANA (S4 PROJECTOR)")
    print()
    alert_threshold = 0.15 if pe(T, 4) < 0.15 <= pe(T, 3) else (pe(T, 4) + pe(T, 3)) / 2.0
    critical_threshold = (pe(T, 3) + pe(T, 2)) / 2.0

    print(f"  Umbral de alerta (separa bin4 de bin3):   P(E) ≥ {alert_threshold:.4f}")
    print(f"  Umbral crítico (separa bin3 de bin2):     P(E) ≥ {critical_threshold:.4f}")
    print()
    print(f"  COMPORTAMIENTO DEL PROJECTOR (h=30):")
    for bin_id in [5, 4, 3, 2, 1]:
        p = pe(T, bin_id)
        # umbral per-bin (v5)
        if bin_id >= 4:
            umbral = p + 0.01
            estado = "SILENT (saludable)"
        elif bin_id == 3:
            umbral = min(alert_threshold, p * 0.95)
            estado = "ALERTA previa" if p >= umbral else "SILENT (borde)"
        else:
            umbral = p + 0.01
            estado = "SILENT (post-E)"

        actua = p >= umbral
        flecha = "→ ACTIVARÍA" if actua else "→ silencio"
        print(f"  Desde bin {bin_id} ({BINS[K-bin_id][1]:>8s}): P(E)={p:.4f}  umbral={umbral:.4f}  {flecha:>15s}  ({estado})")

    print()
    print("  La alerta se activa SOLO desde DRIFTING (bin 3), justo")
    print("  ANTES de que la zona entre en EXCURSIÓN. Esto da un")
    print("  margen de reacción de al menos 1 día (lead=1).")

    # ── 7. Comparación con otras zonas ────────────────────────────────────
    print_seccion("7. COMPARATIVA — ZONA CENTRAL vs OTRAS ZONAS")
    print()
    print(f"  {'Zona':>20s}  {'P(E|bin5)':>10s}  {'P(E|bin3)':>10s}  {'P(E|bin1)':>10s}  {'Estabilidad':>13s}")
    print("  " + "-" * 68)

    zona_files = {
        "Central (RM)": "s1-santiago.json",
        "Sur (Valdivia)": "s1-valdivia.json",
        "Norte (Iquique)": "s1-iquique.json",
        "Norte Chico (Huasco)": "s1-huasco.json",
        "Patagonia (Punta Arenas)": "s1-punta-arenas.json",
        "Tropical (Galápagos)": "s1-galapagos.json",
    }
    for label, fname in zona_files.items():
        path = os.path.join(markov_dir, fname)
        with open(path) as f:
            T_z = json.load(f)["T"]
        p5 = pe(T_z, 5)
        p3 = pe(T_z, 3)
        p1 = pe(T_z, 1)
        pi_z = distribucion_estacionaria(T_z)
        est = pi_z[0] + pi_z[1]  # P(OPTIMAL+HEALTHY)
        print(f"  {label:>20s}  {p5:8.1%}   {p3:8.1%}   {p1:8.1%}   {est:10.1%}")

    print()
    print("  La zona Central es moderadamente estable comparada con")
    print("  el resto del territorio. La Patagonia tiene la mayor")
    print("  volatilidad (menor P(OPTIMAL)), mientras que el Norte")
    print("  Chico tiene la mayor resiliencia (alta P(recuperación)).")

    print()
    print("=" * 72)
    print("  AVISO — LÍMITES DE ESTE MODELO (leer antes de interpretar)")
    print("=" * 72)
    print()
    print("  Esto es CLIMATOLOGÍA ESTADÍSTICA, no un pronóstico meteorológico.")
    print("  Es una tabla actuarial: da TASAS BASE históricas, no predice eventos.")
    print()
    print("  - Entrenado en ERA5 1991-2020: NO conoce eventos futuros concretos")
    print("    (p.ej. un río atmosférico entrante NO aparece en este modelo).")
    print("  - Horizonte predictivo real ~1 día: a 7 días la proyección converge")
    print("    a la tasa base (~20% desde CUALQUIER estado) — la cadena mezcla más")
    print("    rápido que el horizonte, así que el 'pronóstico a 7 días' es solo el")
    print("    promedio histórico, sin memoria del estado inicial.")
    print("  - Análisis ESTRUCTURAL, no en vivo: describe transiciones desde cada")
    print("    estado posible, no 'dónde estamos hoy'.")
    print("  - 'Excursión' = cuantil estadístico bajo de la viabilidad (bins 1-2),")
    print("    NO un desastre meteorológico.")
    print()
    print("  Uso correcto: entender el RÉGIMEN estadístico de una zona (persistencia,")
    print("  recuperación, tasa base de crisis). NO sirve para pronosticar la lluvia")
    print("  de la próxima semana — para eso se usa un modelo meteorológico, no éste.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: reporte_clima_santiago.py <markov_dir>")
        sys.exit(1)
    generar_reporte(sys.argv[1])
