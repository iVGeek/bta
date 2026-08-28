import sys, os
sys.path.insert(0, "C:/iVGeek/trading-bot/executor")
os.chdir("C:/iVGeek/trading-bot/executor")
_STATE = "C:/iVGeek/trading-bot/executor/executor_state.json"
if os.path.exists(_STATE):
    os.remove(_STATE)  # deterministic baseline: no persisted state at start
from fastapi.testclient import TestClient
from server import app, config, processor

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

# Symbol resolution: TradingView syminfo.tickerid must map to ccxt market symbols
sp = processor
cases = {
    "BINANCE:BTCUSDT": "BTC/USDT:USDT",      # Broker: prefix, compact ticker
    "BINANCE:ETHUSDT.P": "ETH/USDT:USDT",    # delivery suffix stripped
    "BTCUSDT": "BTC/USDT:USDT",              # bare compact ticker (futures market)
    "BTC/USDT": "BTC/USDT:USDT",             # already slashed -> still canonical futures
}
for raw, want in cases.items():
    got = sp._resolve_symbol({"symbol": raw, "price": 60000})
    assert got == want, f"{raw} -> {got} (expected {want})"
    print(f"10. Resolve {raw} -> {got}")

# Shared exchange used throughout (binance configured with balance + fallback)
ex = sp.exchanges.get_exchange("binance")
assert len(ex.markets) > 1000, f"binance should have loaded futures markets, got {len(ex.markets)}"
print("11. Binance futures markets loaded:", len(ex.markets), "instruments")

# State persistence: risk counters + trade log survive a processor restart
state_file = sp._state_file
import json, os
assert os.path.exists(state_file), "state file should be written after signals"
with open(state_file, encoding="utf-8") as f:
    saved = json.load(f)
assert saved["daily_trade_count"] >= 3, saved["daily_trade_count"]
assert len(saved["trade_log"]) >= 4, len(saved["trade_log"])
assert "secret" not in json.dumps(saved), "state must not persist webhook secrets"
print(f"12. State persisted: daily_trades={saved['daily_trade_count']}, log={len(saved['trade_log'])}, no secrets")

from processor import SignalProcessor
fresh = SignalProcessor(config, sp.exchanges, None)
assert fresh.daily_trade_count == saved["daily_trade_count"], \
    (fresh.daily_trade_count, saved["daily_trade_count"])
assert len(fresh.trade_log) == len(saved["trade_log"]), (len(fresh.trade_log), len(saved["trade_log"]))
print(f"13. Restart restores: daily_trades={fresh.daily_trade_count}, log={len(fresh.trade_log)}")

# Daily-trades cap must NOT be consumed by exits (only opens count)
buy_sig = {"bot_id": "t", "secret": SECRET, "signal": "buy",
           "symbol": "BTC/USDT", "price": 60000, "sl": 59000, "tp": 62000}
exit_sig = {"bot_id": "t", "secret": SECRET, "signal": "exit", "symbol": "BTC/USDT"}
n0 = fresh.daily_trade_count
r = fresh.process(exit_sig)
assert r["status"] == "no_position", r
r = fresh.process(buy_sig)
assert r["status"] == "dry_run", r
assert fresh.daily_trade_count == n0 + 1, (n0, fresh.daily_trade_count)
print(f"14. Exit doesn't consume daily-trade cap (n0={n0}, after_both={fresh.daily_trade_count})")

print("\n=== ALL EXECUTOR TESTS PASSED ===")