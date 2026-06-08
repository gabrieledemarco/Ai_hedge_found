import os
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


def send_telegram_message(
    text: str,
    session: str,
    has_trades: bool = False,
) -> bool:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[WARN] TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set — skipping message")
        return False

    if session == "sera":
        pass
    elif session in ("mattina", "pomeriggio") and not has_trades:
        print(f"[INFO] Session '{session}' — no trades, skipping notification")
        return False

    print(f"[DEBUG] Sending to chat_id='{CHAT_ID}' (len={len(CHAT_ID)})")
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(API_URL, json=payload, timeout=15)
        resp.raise_for_status()
        print(f"[OK] Telegram message sent ({session})")
        return True
    except requests.RequestException as e:
        print(f"[ERROR] Telegram send failed: {e}")
        status = getattr(e.response, "status_code", None)
        if status == 403:
            print("[HINT] 403 = bot non autorizzato per questa chat.")
            print("[HINT] Devi: 1) Aprire il bot su Telegram 2) Inviare /start")
            print(
                "[HINT] Poi trova il chat_id in: https://api.telegram.org/bot<TOKEN>/getUpdates"
            )
        return False
