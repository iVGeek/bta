"""Deterministic unit tests for paper-engine SL exit + trailing stop logic."""
import sys, os, math
from datetime import date as _date
sys.path.insert(0, "C:/iVGeek/trading-bot")
os.chdir("C:/iVGeek/trading-bot")

from server import PaperPosition, TrailingStopManager, PaperEngine, risk_manager, RiskManager

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond)))
    print(f"{'PASS' if cond else 'FAIL'}: {name}" + (f"  ({detail})" if detail else ""))

paper = PaperEngine()
trail = TrailingStopManager()

# ── SL exit path: LONG ────────────────────────────────────────────────────────
pos = PaperPosition("BTC/USDT", "long", 100.0, 10, sl=99.0, tp=102.0)
# 1. Entry: neutral
check("long: initial pnl=0", pos.pnl == 0)
check("long: no close at entry", pos.should_close() is None)

# 2. Small profit — no trailing yet (profit=0.8 < ATR*breakeven=1.0*1.0=1.0)
pos.update(100.8, atr_val=1.0)
check("long: profit 0.8 at ATR=1", abs(pos.pnl - 8.0) < 0.01, f"pnl={pos.pnl}")
check("long: still open (profit < ATR*2)", pos.should_close() is None)
check("long: sl unchanged at 99.0 (profit < ATR*1.0)", pos.sl == 99.0)

# 3. Breakeven move: profit=1.0 >= ATR*1.0 -> SL moves to entry+0.05*ATR=100.05
pos.update(101.0, atr_val=1.0)
check("long: sl moved to breakeven (100.05)", pos.sl == 100.05, f"sl={pos.sl}")

# 4. Trail: profit=3.0 >= ATR*2=2.0 -> new_sl = 103.0 - 1.5*1.0 = 101.5
pos.update(103.0, atr_val=1.0)
check("long: sl trailed to 101.5", pos.sl == 101.5, f"sl={pos.sl}")

# 5. Price drops below trail -> SL hit
pos.update(101.4, atr_val=1.0)
close_reason = pos.should_close()
check("long: sl_hit triggered", close_reason == "sl_hit", f"reason={close_reason}")
expected_pnl = (101.4 - 100.0) * 10
check("long: pnl correct at SL close (14.0)", abs(pos.pnl - expected_pnl) < 0.01, f"pnl={pos.pnl}")

# ── SL exit path: SHORT ───────────────────────────────────────────────────────
pos2 = PaperPosition("ETH/USDT", "short", 100.0, 10, sl=101.0, tp=98.0)
check("short: initial pnl=0", pos2.pnl == 0)
check("short: no close at entry", pos2.should_close() is None)

# 6. Small profit — no trailing yet (profit=0.8 < ATR*1.0=1.0)
pos2.update(99.2, atr_val=1.0)
check("short: profit 0.8", abs(pos2.pnl - 8.0) < 0.01)
check("short: sl unchanged at 101.0 (profit < ATR*1.0)", pos2.sl == 101.0)

# 7. Breakeven move: profit=1.0 >= ATR*1.0 -> SL moves to entry-0.05*ATR=99.95
pos2.update(99.0, atr_val=1.0)
check("short: sl moved to breakeven (99.95)", pos2.sl == 99.95, f"sl={pos2.sl}")

# 8. Trail: profit=3.0 >= ATR*2=2.0 -> new_sl = 97.0 + 1.5*1.0 = 98.5; 98.5 < 99.95 -> update
pos2.update(97.0, atr_val=1.0)
check("short: sl trailed to 98.5", pos2.sl == 98.5, f"sl={pos2.sl}")

# 9. Price rises above trail -> SL hit
pos2.update(98.6, atr_val=1.0)
close_reason2 = pos2.should_close()
check("short: sl_hit triggered", close_reason2 == "sl_hit", f"reason={close_reason2}")
expected_pnl2 = (100.0 - 98.6) * 10
check("short: pnl correct at SL close (14.0)", abs(pos2.pnl - expected_pnl2) < 0.01, f"pnl={pos2.pnl}")

# ── TP exit path: confirm both sides ──────────────────────────────────────────
pos3 = PaperPosition("SOL/USDT", "long", 100.0, 10, sl=99.0, tp=102.0)
pos3.update(102.5, atr_val=1.0)
check("long: tp_hit", pos3.should_close() == "tp_hit")
pos4 = PaperPosition("XRP/USDT", "short", 100.0, 10, sl=101.0, tp=98.0)
pos4.update(97.5, atr_val=1.0)
check("short: tp_hit", pos4.should_close() == "tp_hit")

# ── Trailing never moves SL in wrong direction ────────────────────────────────
pos5 = PaperPosition("BNB/USDT", "long", 100.0, 5, sl=98.0, tp=105.0)
pos5.update(103.0, atr_val=1.0)  # trail -> new_sl = 101.5
trail_sl_after = pos5.sl
pos5.update(102.0, atr_val=1.0)  # profit=2.0 -> trail new_sl=100.5; 100.5 < 101.5 -> no move
check("trail: SL doesn't backtrack on profit dip", pos5.sl == trail_sl_after, f"sl={pos5.sl} expected={trail_sl_after}")

# ── Full cycle: open -> update_positions -> balance credited ────────────────────
paper2 = PaperEngine()
paper2.balance = 10000.0
paper2.initial_balance = 10000.0
# Inject a position manually — long with tight SL below entry
p = PaperPosition("BTC/USDT", "long", 100.0, 0.5, sl=99.9, tp=105.0)
paper2.positions.append(p)
tickers = {"BTC/USDT": {"price": 100.05}}
closed = paper2.update_positions(tickers)
check("cycle: no close at 100.05 (sl=99.9)", len(closed) == 0, f"closed={len(closed)}")
tickers = {"BTC/USDT": {"price": 99.85}}
closed = paper2.update_positions(tickers)
check("cycle: SL hit at 99.85 -> close", len(closed) == 1, f"closed={len(closed)}")
check("cycle: reason=sl_hit", closed[0]["reason"] == "sl_hit", f"reason={closed[0]['reason']}")
expected_bal = 10000.0 + (99.85 - 100.0) * 0.5
check("cycle: balance credited", abs(paper2.balance - expected_bal) < 0.001, f"bal={paper2.balance}")
check("cycle: position removed", len(paper2.positions) == 0)
check("cycle: trade logged", len(paper2.trades) == 1)

# ── Daily loss limit scales with equity (pct-of-equity, not fixed $) ──────────
risk2 = RiskManager()
eng = PaperEngine(); eng.balance = 10000.0; eng.initial_balance = 10000.0
assert risk2._daily_loss_limit(eng) == -500.0, f"5% of 10k = -500, got {risk2._daily_loss_limit(eng)}"
risk2.daily_pnl = -600.0  # 6% at 10k -> exceeds 5% limit
ok, why = risk2.can_trade(eng)
check("daily loss: 6% at 10k halts trading", not ok, why)
risk2.daily_pnl = -400.0  # 4% at 10k -> allowed
ok, why = risk2.can_trade(eng)
check("daily loss: 4% at 10k allowed", ok)
# At 10x the equity (100k), the same -600 is only 0.6% -> must still be allowed
eng2 = PaperEngine(); eng2.balance = 100000.0; eng2.initial_balance = 100000.0
risk3 = RiskManager(); risk3.daily_pnl = -600.0
check("daily loss: limit scales with equity (100k, -600 allowed)",
      risk3.can_trade(eng2)[0], f"limit={risk3._daily_loss_limit(eng2)}")
# Trade-count cap still enforced independently of $ amount
risk4 = RiskManager(); risk4.daily_trades = risk4.max_daily_trades
check("daily trades cap enforced", not risk4.can_trade(eng)[0])

# ── Max drawdown gate (unrealized equity vs peak) ─────────────────────────────
risk5 = RiskManager(); risk5.peak_equity = 10000.0; risk5.daily_pnl = 0
eng3 = PaperEngine(); eng3.balance = 10000.0; eng3.initial_balance = 10000.0
# Place a losing paper position dragging equity from peak: (50-100)*40 = -2000
# -> equity = balance + pnl = 10000 + (-2000) = 8000 -> 20% drawdown from peak 10000 (limit 15%)
from server import PaperPosition as PP
eng3.positions.append(PP("BTC/USDT", "long", 100.0, 40, sl=90.0, tp=120.0))
eng3.positions[0].update(50.0, atr_val=1.0)  # updates pnl = (50-100)*40 = -2000
check("drawdown: equity dropped", abs((10000.0 + eng3.positions[0].pnl) - 8000.0) < 0.01,
      f"equity={10000.0 + eng3.positions[0].pnl}")
ok, why = risk5.can_trade(eng3)
check("max drawdown: 20% exceeds 15% gate", not ok, why)
# Within 15% -> allowed
risk6 = RiskManager(); risk6.peak_equity = 10000.0; risk6.daily_pnl = 0
eng4 = PaperEngine(); eng4.balance = 10000.0; eng4.initial_balance = 10000.0
eng4.positions.append(PP("BTC/USDT", "long", 100.0, 40, sl=90.0, tp=120.0))
eng4.positions[0].update(97.0, atr_val=1.0)  # (97-100)*40 = -120 -> equity 9880 -> -1.2%
ok, why = risk6.can_trade(eng4)
check("max drawdown: 1.2% within gate allowed", ok, why)

# ── Daily reset on calendar rollover ──────────────────────────────────────────
from datetime import date
risk7 = RiskManager(); risk7.daily_pnl = -900.0; risk7.daily_trades = 19
risk7.last_reset = _date(2000, 1, 1)  # force "yesterday" -> rollover today resets counters
risk7._check_daily_reset()
check("daily reset: loss counter cleared", risk7.daily_pnl == 0.0, f"daily_pnl={risk7.daily_pnl}")
check("daily reset: trade counter cleared", risk7.daily_trades == 0, f"daily_trades={risk7.daily_trades}")
check("daily reset: date advanced", risk7.last_reset == _date.today())

failed = [n for n, ok in R if not ok]
print(f"\n=== {len(R) - len(failed)}/{len(R)} CHECKS PASSED ===")
if failed:
    print("FAILED:", failed)
    sys.exit(1)
