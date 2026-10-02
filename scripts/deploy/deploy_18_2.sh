#!/usr/bin/env bash
# deploy_18_2.sh — ITEM_18.2: scale EXP-S1-CLIMA-01 to 80 nodes
# Runs from WSL against n02/LXC 112.
# Steps: push files → reload l2_zone → enable 68 new l3 services → launch calibration
set -euo pipefail

LXC=112
SRC=/opt/vsf-clima/src
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== ITEM_18.2 deploy: 80-node scale ==="
echo

# 1. Push new node_registry.py
echo "[1/5] deploying node_registry.py (80 nodes)..."
scp "$SCRIPTS_DIR/node_registry_v2.py" root@n02:/tmp/node_registry_v2.py
ssh root@n02 "pct push $LXC /tmp/node_registry_v2.py $SRC/node_registry.py"

# 2. Push debounce-patched l2_zone.py
echo "[2/5] deploying l2_zone.py (debounce v2)..."
scp "$SCRIPTS_DIR/l2_zone_v2_patch.py" root@n02:/tmp/l2_zone_v2.py
ssh root@n02 "pct push $LXC /tmp/l2_zone_v2.py $SRC/l2_zone.py"

# 3. Restart all L2 zone services (picks up new node_registry + debounce)
echo "[3/5] restarting L2 zone services..."
ssh root@n02 "pct exec $LXC -- bash -c '
  systemctl restart vsf-clima-l2@tropical-arida.service
  systemctl restart vsf-clima-l2@semiarida.service
  systemctl restart vsf-clima-l2@mediterranea.service
  systemctl restart vsf-clima-l2@templada-humeda.service
  systemctl restart vsf-clima-l2@subpolar.service
  systemctl restart vsf-clima-l2@humboldt.service
  systemctl restart vsf-clima-l2@enso-tropical.service
  systemctl restart vsf-clima-l2@pacifico-sur-medio.service
  echo "L2 zones restarted"
'"

# 4. Enable + start 68 new L3 services
echo "[4/5] enabling 68 new L3 node services..."
NEW_NODES=(
  s1-iquique s1-tocopilla s1-calama s1-taltal s1-copiapo
  s1-huasco s1-diego-almagro s1-chanaral
  s1-ovalle s1-coquimbo s1-illapel s1-vicuna s1-combarbala
  s1-salamanca s1-los-vilos s1-petorca s1-ligua
  s1-rancagua s1-san-fernando s1-curico s1-talca s1-linares
  s1-chillan s1-los-angeles s1-temuco
  s1-osorno s1-la-union s1-castro s1-ancud s1-rio-negro
  s1-maullin s1-panguipulli s1-villarrica
  s1-cochrane s1-chile-chico s1-puerto-aysen s1-villa-ohiggins
  s1-puerto-natales s1-porvenir s1-tortel s1-puerto-williams
  s1-hum-22s-73w s1-hum-25s-74w s1-hum-28s-73w s1-hum-31s-74w
  s1-hum-35s-75w s1-hum-38s-74w s1-hum-40s-76w s1-hum-43s-77w s1-hum-18s-72w
  s1-enso-0s-100w s1-enso-2s-100w s1-enso-5s-100w
  s1-enso-0s-120w s1-enso-2s-120w s1-enso-5s-120w
  s1-enso-0s-140w s1-enso-10s-110w
  s1-pso-25s-90w s1-pso-30s-90w s1-pso-30s-100w s1-pso-35s-95w s1-pso-35s-105w
  s1-pso-40s-95w s1-pso-40s-110w s1-pso-43s-90w s1-pso-45s-105w s1-pso-20s-100w
)

ENABLE_CMD="systemctl enable --now"
for node in "${NEW_NODES[@]}"; do
  ENABLE_CMD="$ENABLE_CMD vsf-clima-l3@${node}.service"
done

ssh root@n02 "pct exec $LXC -- bash -c '$ENABLE_CMD 2>&1 | tail -5 && echo \"${#NEW_NODES[@]} L3 services enabled\"'"

# 5. Launch omega batch calibration in background (non-blocking)
echo "[5/5] launching omega calibration for 68 new nodes (background)..."
NEW_NODES_STR="${NEW_NODES[*]}"
ssh root@n02 "pct exec $LXC -- bash -c '
  nohup /opt/vsf-clima/bin/python /opt/vsf-clima/src/omega_calibrate.py \
    --nodes $NEW_NODES_STR \
    > /var/log/vsf-clima/omega_calibrate_18_2.log 2>&1 &
  echo "Calibration PID: \$!"
'"

echo
echo "=== deploy complete ==="
echo "  80 L3 nodes registered"
echo "  68 new L3 services started (omega_calibrated=False until calibration finishes)"
echo "  L2 zones restarted with debounce (${DEBOUNCE_S:-5}s window)"
echo "  Calibration running → /var/log/vsf-clima/omega_calibrate_18_2.log"
echo
echo "Monitor:"
echo "  ssh root@n02 'pct exec $LXC -- journalctl -u vsf-clima-l2@mediterranea -f'"
echo "  ssh root@n02 'pct exec $LXC -- tail -f /var/log/vsf-clima/omega_calibrate_18_2.log'"
