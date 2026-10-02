"""
node_registry.py — single source of truth for all VSM nodes (L0-L3).
v2: 87 L3 nodes (originally 10 per zone × 8 zones = 80, +7 added 2026-07-13).

Level counts: 87 L3 + 8 L2 + 2 L1 + 1 L0 = 98 nodes total.
Original 12 nodes (v1) preserved exactly.
"""

# ── L3 stations ───────────────────────────────────────────────────────────────
L3_NODES: dict[str, dict] = {

    # ── ZONE: tropical-arida (10 nodes) ───────────────────────────────────────
    # Atacama Desert + hyper-arid coast
    "s1-arica":        {"lat": -18.48, "lon": -70.33, "type": "continental", "regime": "hiperarido",          "zone": "tropical-arida"},
    "s1-antofagasta":  {"lat": -23.65, "lon": -70.40, "type": "continental", "regime": "desertico",           "zone": "tropical-arida"},
    "s1-iquique":      {"lat": -20.21, "lon": -70.15, "type": "continental", "regime": "nublado_costero",     "zone": "tropical-arida"},
    "s1-tocopilla":    {"lat": -22.09, "lon": -70.20, "type": "continental", "regime": "desertico",           "zone": "tropical-arida"},
    "s1-calama":       {"lat": -22.47, "lon": -68.93, "type": "continental", "regime": "desertico_altiplano", "zone": "tropical-arida"},
    "s1-taltal":       {"lat": -25.40, "lon": -70.47, "type": "continental", "regime": "desertico_costero",   "zone": "tropical-arida"},
    "s1-copiapo":      {"lat": -27.37, "lon": -70.33, "type": "continental", "regime": "desertico_periferico","zone": "tropical-arida"},
    "s1-huasco":       {"lat": -28.47, "lon": -71.22, "type": "continental", "regime": "desertico_transicion","zone": "tropical-arida"},
    "s1-diego-almagro":{"lat": -26.37, "lon": -70.06, "type": "continental", "regime": "desertico",           "zone": "tropical-arida"},
    "s1-chanaral":     {"lat": -26.35, "lon": -70.62, "type": "continental", "regime": "desertico_costero",   "zone": "tropical-arida"},

    # ── ZONE: semiarida (11 nodes, was 10 + 1 added 2026-07-13) ──────────────
    # Norte Chico — semi-arid scrub, fog oases
    "s1-la-serena":    {"lat": -29.90, "lon": -71.25, "type": "continental", "regime": "semiarido",           "zone": "semiarida"},
    "s1-ovalle":       {"lat": -30.60, "lon": -71.19, "type": "continental", "regime": "semiarido_interior",  "zone": "semiarida"},
    "s1-coquimbo":     {"lat": -29.96, "lon": -71.34, "type": "continental", "regime": "semiarido_costero",   "zone": "semiarida"},
    "s1-illapel":      {"lat": -31.63, "lon": -71.17, "type": "continental", "regime": "semiarido_transversal","zone": "semiarida"},
    "s1-vicuna":       {"lat": -30.03, "lon": -70.71, "type": "continental", "regime": "semiarido_interior",  "zone": "semiarida"},
    "s1-combarbala":   {"lat": -31.18, "lon": -71.02, "type": "continental", "regime": "semiarido_med",       "zone": "semiarida"},
    "s1-salamanca":    {"lat": -31.77, "lon": -70.97, "type": "continental", "regime": "semiarido_montano",   "zone": "semiarida"},
    "s1-los-vilos":    {"lat": -31.91, "lon": -71.51, "type": "continental", "regime": "semiarido_costero",   "zone": "semiarida"},
    "s1-petorca":      {"lat": -32.25, "lon": -70.93, "type": "continental", "regime": "semiarido_transicion","zone": "semiarida"},
    "s1-ligua":        {"lat": -32.45, "lon": -71.24, "type": "continental", "regime": "semiarido_transicion","zone": "semiarida"},
    "s1-pichidangui":  {"lat": -32.14, "lon": -71.53, "type": "continental", "regime": "semiarido_costero",   "zone": "semiarida"},  # added 2026-07-13

    # ── ZONE: mediterranea (13 nodes, was 10 + 3 added 2026-07-13) ───────────
    # Central valley — Mediterranean climate
    "s1-santiago":         {"lat": -33.45, "lon": -70.67, "type": "continental", "regime": "mediterraneo",          "zone": "mediterranea"},
    "s1-concepcion":       {"lat": -36.83, "lon": -73.05, "type": "continental", "regime": "humedo",                "zone": "mediterranea"},
    "s1-rancagua":         {"lat": -34.17, "lon": -70.74, "type": "continental", "regime": "mediterraneo",          "zone": "mediterranea"},
    "s1-san-fernando":     {"lat": -34.59, "lon": -70.96, "type": "continental", "regime": "mediterraneo",          "zone": "mediterranea"},
    "s1-curico":           {"lat": -34.98, "lon": -71.23, "type": "continental", "regime": "mediterraneo",          "zone": "mediterranea"},
    "s1-talca":            {"lat": -35.43, "lon": -71.66, "type": "continental", "regime": "mediterraneo",          "zone": "mediterranea"},
    "s1-linares":          {"lat": -35.85, "lon": -71.60, "type": "continental", "regime": "mediterraneo",          "zone": "mediterranea"},
    "s1-chillan":          {"lat": -36.61, "lon": -72.10, "type": "continental", "regime": "mediterraneo",          "zone": "mediterranea"},
    "s1-los-angeles":      {"lat": -37.47, "lon": -72.35, "type": "continental", "regime": "mediterraneo_humedo",   "zone": "mediterranea"},
    "s1-temuco":           {"lat": -38.74, "lon": -72.60, "type": "continental", "regime": "humedo_transicion",     "zone": "mediterranea"},
    "s1-domingo":          {"lat": -33.63, "lon": -71.66, "type": "continental", "regime": "mediterraneo_costero",  "zone": "mediterranea"},  # added 2026-07-13
    "s1-nacimiento":       {"lat": -37.50, "lon": -71.98, "type": "continental", "regime": "mediterraneo_humedo",   "zone": "mediterranea"},  # added 2026-07-13
    "s1-padre-las-casas":  {"lat": -38.77, "lon": -72.60, "type": "continental", "regime": "humedo_transicion",     "zone": "mediterranea"},  # added 2026-07-13

    # ── ZONE: templada-humeda (12 nodes, was 10 + 2 added 2026-07-13) ────────
    # Araucanía + Lakes — oceanic/temperate humid
    "s1-valdivia":     {"lat": -39.81, "lon": -73.24, "type": "continental", "regime": "lluvioso",            "zone": "templada-humeda"},
    "s1-puerto-montt": {"lat": -41.47, "lon": -72.94, "type": "continental", "regime": "oceanico",            "zone": "templada-humeda"},
    "s1-osorno":       {"lat": -40.57, "lon": -73.14, "type": "continental", "regime": "oceanico",            "zone": "templada-humeda"},
    "s1-la-union":     {"lat": -40.29, "lon": -73.08, "type": "continental", "regime": "oceanico",            "zone": "templada-humeda"},
    "s1-castro":       {"lat": -42.48, "lon": -73.77, "type": "continental", "regime": "oceanico_insular",    "zone": "templada-humeda"},
    "s1-ancud":        {"lat": -41.87, "lon": -73.83, "type": "continental", "regime": "oceanico_insular",    "zone": "templada-humeda"},
    "s1-rio-negro":    {"lat": -40.79, "lon": -73.22, "type": "continental", "regime": "oceanico",            "zone": "templada-humeda"},
    "s1-maullin":      {"lat": -41.63, "lon": -73.60, "type": "continental", "regime": "oceanico_costero",    "zone": "templada-humeda"},
    "s1-panguipulli":  {"lat": -39.64, "lon": -72.34, "type": "continental", "regime": "lluvioso_lacustre",   "zone": "templada-humeda"},
    "s1-villarrica":   {"lat": -39.28, "lon": -72.23, "type": "continental", "regime": "lluvioso_lacustre",   "zone": "templada-humeda"},
    "s1-lago-ranco":   {"lat": -40.41, "lon": -72.39, "type": "continental", "regime": "lluvioso_lacustre",   "zone": "templada-humeda"},  # added 2026-07-13
    "s1-pucon":        {"lat": -39.27, "lon": -72.23, "type": "continental", "regime": "lluvioso_lacustre",   "zone": "templada-humeda"},  # added 2026-07-13

    # ── ZONE: subpolar (11 nodes, was 10 + 1 added 2026-07-13) ──────────────
    # Patagonia + Magallanes
    "s1-coyhaique":    {"lat": -45.57, "lon": -72.07, "type": "continental", "regime": "patagonico",          "zone": "subpolar"},
    "s1-punta-arenas": {"lat": -53.16, "lon": -70.91, "type": "continental", "regime": "subpolar",            "zone": "subpolar"},
    "s1-cochrane":     {"lat": -47.25, "lon": -72.56, "type": "continental", "regime": "patagonico",          "zone": "subpolar"},
    "s1-chile-chico":  {"lat": -46.53, "lon": -71.73, "type": "continental", "regime": "patagonico_estepa",   "zone": "subpolar"},
    "s1-puerto-aysen": {"lat": -45.40, "lon": -72.70, "type": "continental", "regime": "patagonico",          "zone": "subpolar"},
    "s1-villa-ohiggins":{"lat": -48.47,"lon": -72.57, "type": "continental", "regime": "subpolar",            "zone": "subpolar"},
    "s1-puerto-natales":{"lat": -51.73,"lon": -72.50, "type": "continental", "regime": "subpolar",            "zone": "subpolar"},
    "s1-porvenir":     {"lat": -53.29, "lon": -70.37, "type": "continental", "regime": "subpolar",            "zone": "subpolar"},
    "s1-tortel":       {"lat": -47.79, "lon": -73.53, "type": "continental", "regime": "subpolar_humedo",     "zone": "subpolar"},
    "s1-puerto-williams":{"lat": -54.93,"lon": -67.62,"type": "continental", "regime": "subpolar_austral",    "zone": "subpolar"},
    "s1-magallanes":   {"lat": -53.15, "lon": -70.92, "type": "continental", "regime": "subpolar",            "zone": "subpolar"},  # added 2026-07-13

    # ── ZONE: humboldt (10 nodes) ─────────────────────────────────────────────
    # Humboldt Current — oceanic cold upwelling
    "s1-juan-fernandez": {"lat": -33.65, "lon": -78.83, "type": "oceanic", "regime": "oceanico_templado",   "zone": "humboldt"},
    "s1-hum-22s-73w":  {"lat": -22.0,  "lon": -73.0,  "type": "oceanic", "regime": "humboldt_costero",    "zone": "humboldt"},
    "s1-hum-25s-74w":  {"lat": -25.0,  "lon": -74.0,  "type": "oceanic", "regime": "humboldt_costero",    "zone": "humboldt"},
    "s1-hum-28s-73w":  {"lat": -28.0,  "lon": -73.0,  "type": "oceanic", "regime": "humboldt_costero",    "zone": "humboldt"},
    "s1-hum-31s-74w":  {"lat": -31.0,  "lon": -74.0,  "type": "oceanic", "regime": "humboldt_central",    "zone": "humboldt"},
    "s1-hum-35s-75w":  {"lat": -35.0,  "lon": -75.0,  "type": "oceanic", "regime": "humboldt_sur",        "zone": "humboldt"},
    "s1-hum-38s-74w":  {"lat": -38.0,  "lon": -74.0,  "type": "oceanic", "regime": "humboldt_austral",    "zone": "humboldt"},
    "s1-hum-40s-76w":  {"lat": -40.0,  "lon": -76.0,  "type": "oceanic", "regime": "subantartico",        "zone": "humboldt"},
    "s1-hum-43s-77w":  {"lat": -43.0,  "lon": -77.0,  "type": "oceanic", "regime": "subantartico",        "zone": "humboldt"},
    "s1-hum-18s-72w":  {"lat": -18.0,  "lon": -72.0,  "type": "oceanic", "regime": "humboldt_norte",      "zone": "humboldt"},

    # ── ZONE: enso-tropical (10 nodes) ────────────────────────────────────────
    # ENSO drivers — Niño zones 3, 3.4, 4
    "s1-easter-island":  {"lat": -27.15, "lon": -109.43,"type": "oceanic", "regime": "subtropical_pacifico", "zone": "enso-tropical"},
    "s1-galapagos":      {"lat": -0.90,  "lon": -89.60, "type": "oceanic", "regime": "ecuatorial_pacifico",  "zone": "enso-tropical"},
    "s1-enso-0s-100w": {"lat":  0.0,   "lon": -100.0, "type": "oceanic", "regime": "nino3_ecuatorial",    "zone": "enso-tropical"},
    "s1-enso-2s-100w": {"lat": -2.0,   "lon": -100.0, "type": "oceanic", "regime": "nino3_ecuatorial",    "zone": "enso-tropical"},
    "s1-enso-5s-100w": {"lat": -5.0,   "lon": -100.0, "type": "oceanic", "regime": "nino3_ecuatorial",    "zone": "enso-tropical"},
    "s1-enso-0s-120w": {"lat":  0.0,   "lon": -120.0, "type": "oceanic", "regime": "nino34_central",      "zone": "enso-tropical"},
    "s1-enso-2s-120w": {"lat": -2.0,   "lon": -120.0, "type": "oceanic", "regime": "nino34_central",      "zone": "enso-tropical"},
    "s1-enso-5s-120w": {"lat": -5.0,   "lon": -120.0, "type": "oceanic", "regime": "nino34_central",      "zone": "enso-tropical"},
    "s1-enso-0s-140w": {"lat":  0.0,   "lon": -140.0, "type": "oceanic", "regime": "nino4_oeste",         "zone": "enso-tropical"},
    "s1-enso-10s-110w":{"lat": -10.0,  "lon": -110.0, "type": "oceanic", "regime": "nino3_subtropical",   "zone": "enso-tropical"},

    # ── ZONE: pacifico-sur-medio (10 nodes) ───────────────────────────────────
    # South Pacific gyre — subtropical anticyclone region (previously 0 nodes)
    "s1-pso-25s-90w":  {"lat": -25.0,  "lon": -90.0,  "type": "oceanic", "regime": "subtropical_anticiclon","zone": "pacifico-sur-medio"},
    "s1-pso-30s-90w":  {"lat": -30.0,  "lon": -90.0,  "type": "oceanic", "regime": "subtropical_anticiclon","zone": "pacifico-sur-medio"},
    "s1-pso-30s-100w": {"lat": -30.0,  "lon": -100.0, "type": "oceanic", "regime": "subtropical_pacifico", "zone": "pacifico-sur-medio"},
    "s1-pso-35s-95w":  {"lat": -35.0,  "lon": -95.0,  "type": "oceanic", "regime": "subtropical_sur",      "zone": "pacifico-sur-medio"},
    "s1-pso-35s-105w": {"lat": -35.0,  "lon": -105.0, "type": "oceanic", "regime": "subtropical_sur",      "zone": "pacifico-sur-medio"},
    "s1-pso-40s-95w":  {"lat": -40.0,  "lon": -95.0,  "type": "oceanic", "regime": "subantartico_transicion","zone": "pacifico-sur-medio"},
    "s1-pso-40s-110w": {"lat": -40.0,  "lon": -110.0, "type": "oceanic", "regime": "subantartico_transicion","zone": "pacifico-sur-medio"},
    "s1-pso-43s-90w":  {"lat": -43.0,  "lon": -90.0,  "type": "oceanic", "regime": "subantartico",          "zone": "pacifico-sur-medio"},
    "s1-pso-45s-105w": {"lat": -45.0,  "lon": -105.0, "type": "oceanic", "regime": "subantartico",          "zone": "pacifico-sur-medio"},
    "s1-pso-20s-100w": {"lat": -20.0,  "lon": -100.0, "type": "oceanic", "regime": "subtropical_anticiclon","zone": "pacifico-sur-medio"},
}

# ── L2 zones ──────────────────────────────────────────────────────────────────
# Derived from L3_NODES — each zone lists its children by ID
def _zone_children(zone: str) -> list[str]:
    return [nid for nid, cfg in L3_NODES.items() if cfg["zone"] == zone]


L2_ZONES: dict[str, dict] = {
    "tropical-arida":     {"system": "continental", "children": _zone_children("tropical-arida"),
                           "kernel_dim": 32, "timescale": "days-weeks"},
    "semiarida":          {"system": "continental", "children": _zone_children("semiarida"),
                           "kernel_dim": 32, "timescale": "days-weeks"},
    "mediterranea":       {"system": "continental", "children": _zone_children("mediterranea"),
                           "kernel_dim": 32, "timescale": "days"},
    "templada-humeda":    {"system": "continental", "children": _zone_children("templada-humeda"),
                           "kernel_dim": 32, "timescale": "hours-days"},
    "subpolar":           {"system": "continental", "children": _zone_children("subpolar"),
                           "kernel_dim": 32, "timescale": "hours-days"},
    "humboldt":           {"system": "marino",      "children": _zone_children("humboldt"),
                           "kernel_dim": 32, "timescale": "weeks-months"},
    "enso-tropical":      {"system": "marino",      "children": _zone_children("enso-tropical"),
                           "kernel_dim": 32, "timescale": "months-years"},
    "pacifico-sur-medio": {"system": "marino",      "children": _zone_children("pacifico-sur-medio"),
                           "kernel_dim": 32, "timescale": "weeks-months"},
}

# ── L1 systems ────────────────────────────────────────────────────────────────
L1_SYSTEMS: dict[str, dict] = {
    "continental": {"parent": "l0", "kernel_dim": 64,
                    "children": ["tropical-arida", "semiarida", "mediterranea",
                                 "templada-humeda", "subpolar"],
                    "mechanism": "frontal",
                    "propagation_direction": "S→N"},
    "marino":      {"parent": "l0", "kernel_dim": 64,
                    "children": ["humboldt", "enso-tropical", "pacifico-sur-medio"],
                    "mechanism": "enso",
                    "propagation_direction": "W→E"},
}

# ── L0 system ─────────────────────────────────────────────────────────────────
L0_SYSTEM = {
    "id": "pacifico-sur-americano",
    "kernel_dim": 128,
    "children": ["continental", "marino"],
    "timescale": "seasonal-interannual",
}

# ── NATS subjects ─────────────────────────────────────────────────────────────
def phi_up_subject(node_id: str) -> str:
    return f"vsf.clima.{node_id}.phi_up"

def algedonic_subject() -> str:
    return "vsf.alpha.algedonic"

# ── Variables per node type ───────────────────────────────────────────────────
# Q8 resolved: ℝ³² = 4 blocks × 8 dims
# block_A [0..7]:  thermodynamic — temp, humidity
# block_B [8..15]: hydric        — precip, pressure
# block_C [16..23]: dynamic      — wind speed, wind direction
# block_D [24..31]: forcing      — cloud/radiation, SST/ONI, seasonal sin/cos

CONTINENTAL_DAILY_VARS = [
    "temperature_2m_mean",
    "relative_humidity_2m_mean",
    "precipitation_sum",
    "pressure_msl_mean",
    "wind_speed_10m_max",
    "wind_direction_10m_dominant",
    "cloud_cover_mean",
    "shortwave_radiation_sum",
]

OCEANIC_DAILY_VARS = CONTINENTAL_DAILY_VARS  # same base; SST from Marine API

MARINE_DAILY_VAR = "sea_surface_temperature_mean"

ERA5_START = "1991-01-01"
ERA5_END   = "2020-12-31"
ERA5_PERCENTILE_LO = 5
ERA5_PERCENTILE_HI = 95
