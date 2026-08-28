import sys, os
sys.path.insert(0, "C:/iVGeek/trading-bot/executor")
os.chdir("C:/iVGeek/trading-bot/executor")
from fastapi.testclient import TestClient
from server import app, config

client = TestClient(app, raise_server_exceptions=False)

SECRET = config.webhook_secret
print("=== EXECUTOR FULL TEST ===\n")

# Status
r = client.get("/status")
print("1. Status:", r.json())

# Reject: wrong secret
signal = {
    "bot_id": "test", "secret": "wrong_secret", "signal": "buy",
    "symbol": "BTC/USDT", "price": 66000, "sl": 65000, "tp": 68000,
}
r = client.post("/webhook", json=signal)
assert r.json().get("status") == "rejected", r.json()
print("2. Buy w/ bad secret -> rejected")

# Happy path: valid BUY in dry run -> sized dry_run order
signal["secret"] = SECRET
r = client.post("/webhook", json=signal)
res = r.json()
assert res.get("status") == "dry_run", res
assert float(res.get("amount", 0)) > 0, res
print(f"3. Buy w/ valid secret -> dry_run amount={res['amount']}")

# Happy path: valid SELL in dry run
signal["signal"] = "sell"; signal["sl"] = 67000; signal["tp"] = 64000
r = client.post("/webhook", json=signal)
res = r.json()
assert res.get("status") == "dry_run", res
print(f"4. Sell w/ valid secret -> dry_run amount={res['amount']}")

# Exit (dry run, no live position -> no_position)
signal["signal"] = "exit"; signal["sl"] = None; signal["tp"] = None
r = client.post("/webhook", json=signal)
res = r.json()
assert res.get("status") == "no_position", res
print("5. Exit -> no_position (dry run)")

# Halt (no keys -> error, non-crashing)
r = client.post("/halt", json={})
res = r.json()
print("6. Halt:", res)

# Invalid payload
r = client.post("/webhook", json={"signal": "invalid"})
assert r.json().get("status") == "rejected", r.json()
print("7. Invalid signal -> rejected")

# Finite amount check: 1% risk on $10000 with $1000 sl_distance -> 0.1 BTC
signal = {"bot_id": "t", "secret": SECRET, "signal": "buy",
          "symbol": "BTC/USDT", "price": 60000, "sl": 59000, "tp": 62000}
r = client.post("/webhook", json=signal)
res = r.json()
expected = 10000 * config.max_position_pct / 100 / (60000 - 59000)
assert abs(float(res["amount"]) - expected) < 1e-9, (res, expected)
print(f"8. Position size math exact ({res['amount']} BTC)")

# Trades log
r = client.get("/trades")
assert len(r.json()) >= 4, r.json()
print("9. Trades logged:", len(r.json()))

print("\n=== ALL EXECUTOR TESTS PASSED ===")