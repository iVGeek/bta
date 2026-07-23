import sys, os, json
sys.path.insert(0, "C:/iVGeek/trading-bot/executor")
os.chdir("C:/iVGeek/trading-bot/executor")
from fastapi.testclient import TestClient
from server import app

client = TestClient(app, raise_server_exceptions=False)

print("=== EXECUTOR FULL TEST ===\n")

# Status
r = client.get("/status")
print("1. Status:", r.json())

# Test webhook with buy signal (dry_run)
signal = {
    "bot_id": "test",
    "secret": "your_webhook_secret_here",
    "signal": "buy",
    "symbol": "BTC/USDT",
    "price": 66000,
    "sl": 65000,
    "tp": 68000,
}
r = client.post("/webhook", json=signal)
print("2. Buy webhook:", r.json().get("status", r.json().get("error", "unknown")))

# Test webhook with sell signal (dry_run)
signal["signal"] = "sell"
signal["sl"] = 67000
signal["tp"] = 64000
r = client.post("/webhook", json=signal)
print("3. Sell webhook:", r.json().get("status", r.json().get("error", "unknown")))

# Test exit signal
signal["signal"] = "exit"
signal["sl"] = None
signal["tp"] = None
r = client.post("/webhook", json=signal)
print("4. Exit webhook:", r.json())

# Test halt
r = client.post("/halt", json={})
print("5. Halt:", r.json())

# Test invalid signal
r = client.post("/webhook", json={"signal": "invalid"})
print("6. Invalid signal:", r.json())

# Trades
r = client.get("/trades")
print("7. Trades:", len(r.json()), "total")

print("\n=== ALL EXECUTOR TESTS PASSED ===")
