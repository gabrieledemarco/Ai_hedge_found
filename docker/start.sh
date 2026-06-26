#!/bin/bash
# Startup script for the Docker container.
# Conditionally starts IB Gateway if credentials are configured.

set -e

mkdir -p /var/log/supervisor /var/run

# ── IB Gateway ────────────────────────────────────────────────────────────
if [ -n "${IB_ACCOUNT}" ]; then
    echo "[start.sh] IB_ACCOUNT is set — enabling IB Client Portal Gateway"

    # Write credentials to IB Gateway config if provided
    if [ -n "${IB_USERNAME}" ] && [ -n "${IB_PASSWORD}" ]; then
        echo "[start.sh] Writing IB credentials to gateway config"
        cat > /opt/ibkr/clientportal.gw/root/credentials.json <<EOF
{
  "username": "${IB_USERNAME}",
  "password": "${IB_PASSWORD}"
}
EOF
    fi

    # Create a wrapper that starts the gateway
    cat > /opt/ibkr/start_ibkr.sh <<'SCRIPT'
#!/bin/bash
cd /opt/ibkr/clientportal.gw
exec java -jar root/cpwebapi.jar root/conf.yaml
SCRIPT
    chmod +x /opt/ibkr/start_ibkr.sh

    # Enable the ib-gateway supervisor program
    supervisorctl -c /etc/supervisor/conf.d/trading.conf start ib-gateway 2>/dev/null || true

    echo "[start.sh] IB Gateway will start on port 5000 (HTTPS)"
    echo "[start.sh] NOTE: First-time auth requires browser login at https://<host>:5000"
else
    echo "[start.sh] IB_ACCOUNT not set — running in simulation mode (no IB Gateway)"
fi

# ── Launch supervisord ─────────────────────────────────────────────────────
echo "[start.sh] Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/trading.conf
