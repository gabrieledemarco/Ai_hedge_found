# AI Hedge Fund — Docker image for Render deployment
#
# Runs two processes via supervisord:
#   1. IB Client Portal Gateway (Java, port 5000) — only if IB_ACCOUNT is set
#   2. Python trading scheduler   (Flask, port 8080)
#
# Required environment variables on Render:
#   IB_ACCOUNT          IB paper account ID   (e.g. DU1234567)
#   IB_GATEWAY_URL      set to https://localhost:5000
#   TIINGO_API_KEY
#   ALPHA_VANTAGE_KEY
#   TELEGRAM_TOKEN
#   TELEGRAM_CHAT_ID
#
# Optional (IB credentials for auto-login):
#   IB_USERNAME
#   IB_PASSWORD

FROM python:3.11-slim

# ── System dependencies ────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        default-jre-headless \
        wget \
        unzip \
        curl \
        supervisor \
        git \
    && rm -rf /var/lib/apt/lists/*

# ── IB Client Portal Gateway ───────────────────────────────────────────────
# Download the official IB Client Portal Gateway (no auth required)
ENV IBKR_GW_DIR=/opt/ibkr/clientportal.gw

RUN mkdir -p ${IBKR_GW_DIR} && \
    wget -q "https://download2.interactivebrokers.com/portal/clientportal.gw.zip" \
        -O /tmp/cp.gw.zip && \
    unzip -q /tmp/cp.gw.zip -d ${IBKR_GW_DIR} && \
    rm /tmp/cp.gw.zip

# IB Gateway configuration
COPY docker/ibkr/conf.yaml ${IBKR_GW_DIR}/root/conf.yaml

# ── Python app ─────────────────────────────────────────────────────────────
WORKDIR /app

COPY requirements.txt requirements-scheduler.txt ./
RUN pip install --no-cache-dir \
        -r requirements.txt \
        -r requirements-scheduler.txt

# Copy source
COPY scripts/   ./scripts/
COPY data/      ./data/
COPY docs/      ./docs/

# ── Supervisord ────────────────────────────────────────────────────────────
COPY docker/supervisord.conf /etc/supervisor/conf.d/trading.conf
COPY docker/start.sh         /start.sh
RUN chmod +x /start.sh

EXPOSE 5000 8080

CMD ["/start.sh"]
