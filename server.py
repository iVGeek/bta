"""
Bot Trading AI Terminal v2.0
Real-time TradingView data, Claude AI analysis, auto-trade pipeline
"""
import asyncio
import json
import math
import os
import random
import re
import time
import urllib.request
import urllib.error
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import uvicorn
import yfinance as yf
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI(title="Bot Trading AI Terminal")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ── Exchange ──────────────────────────────────────────────────────────────────

_exchange = None

def get_exchange(authed=False):
    global _exchange
    if _exchange and not authed:
        return _exchange
    ex_id = os.getenv("EXCHANGE", "binance").lower()
    cfg = {"enableRateLimit": True, "options": {}}
    if authed:
        cfg["apiKey"] = os.getenv("API_KEY", "")
        cfg["secret"] = os.getenv("API_SECRET", "")
    if ex_id == "binance":
        cfg["options"]["defaultType"] = "future"
    ex = getattr(ccxt, ex_id)(cfg)
    if not authed:
        _exchange = ex
    return ex


# ── Technical Indicators ──────────────────────────────────────────────────────

# ── Stock Symbols ─────────────────────────────────────────────────────────────

STOCK_LIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "UNH", "XOM", "JNJ", "WMT", "PG", "MA", "HD", "CVX",
    "MRK", "ABBV", "KO", "PEP", "AVGO", "COST", "TMO", "MCD", "CSCO",
    "ACN", "ABT", "DHR", "LIN", "NEE", "PM", "TXN", "UNP", "RTX",
    "LOW", "HON", "AMGN", "IBM", "QCOM", "BA", "GE", "CAT", "SPGI",
    "BLK", "SYK", "ADI", "MDLZ", "GILD", "ISRG", "BKNG", "PANW",
    "SNOW", "PLTR", "COIN", "SQ", "ROKU", "SOFI", "MARA", "RIOT",
]

def fetch_stock_tickers():
    global ticker_cache, ticker_cache_time
    now = time.time()
    if now - ticker_cache_time < 30 and ticker_cache:
        return ticker_cache
    try:
        tickers = {}
        batch = yf.Tickers(" ".join(STOCK_LIST[:30]))
        for sym in STOCK_LIST[:30]:
            try:
                info = batch.tickers[sym].fast_info
                price = getattr(info, 'last_price', None) or getattr(info, 'previous_close', 0) or 0
                prev = getattr(info, 'previous_close', price) or price
                mcap = getattr(info, 'market_cap', 0) or 0
                chg = ((price - prev) / prev * 100) if prev and price else 0
                tickers[sym] = {
                    "symbol": sym, "price": round(price, 2),
                    "change_24h": round(chg, 2),
                    "volume_24h": mcap,
                    "high_24h": round(price * 1.01, 2),
                    "low_24h": round(price * 0.99, 2),
                    "bid": round(price * 0.999, 2),
                    "ask": round(price * 1.001, 2),
                    "spread": round(price * 0.002, 2),
                    "asset": "stock",
                }
            except Exception as e:
                print(f"Stock {sym}: {e}")
        ticker_cache, ticker_cache_time = tickers, now
        return tickers
    except Exception as e:
        print(f"Stock tickers: {e}")
        return ticker_cache or {}


def fetch_stock_ohlcv(symbol, tf="1d", limit=250):
    try:
        period_map = {"1m": "5d", "5m": "60d", "15m": "60d", "60m": "2y",
                      "1h": "2y", "1d": "5y", "1wk": "5y", "1M": "5y"}
        interval_map = {"1m": "1m", "5m": "5m", "15m": "15m", "60m": "1h",
                        "1h": "1h", "1d": "1d", "1wk": "1wk", "1M": "1mo"}
        yf_interval = interval_map.get(tf, "1d")
        yf_period = period_map.get(tf, "2y")
        if yf_interval in ("1m", "5m", "15m"):
            yf_period = "60d"
        data = yf.Ticker(symbol).history(period=yf_period, interval=yf_interval)
        if data.empty:
            return []
        candles = []
        for ts, row in data.iterrows():
            candles.append({
                "time": int(ts.timestamp()),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row.get("Volume", 0)),
            })
        return candles[-limit:]
    except Exception as e:
        print(f"Stock OHLCV {symbol}: {e}")
        return []


def fetch_stock_order_book(symbol, limit=15):
    try:
        info = yf.Ticker(symbol).fast_info
        price = getattr(info, 'last_price', 0) or 0
        spread = price * 0.001
        bids = [[round(price - spread * (i + 1), 2), round(random.uniform(10, 500), 0)] for i in range(limit)]
        asks = [[round(price + spread * (i + 1), 2), round(random.uniform(10, 500), 0)] for i in range(limit)]
        return {"bids": bids, "asks": asks}
    except Exception:
        return {"bids": [], "asks": []}


def ema(data, length):
    result, k = [], 2 / (length + 1)
    prev = data[0]
    for i, v in enumerate(data):
        prev = v * k + prev * (1 - k) if i > 0 else v
        result.append(prev)
    return result

def sma(data, length):
    return [sum(data[max(0, i-length+1):i+1]) / min(i+1, length) for i in range(len(data))]

def rsi(closes, length=14):
    result = [50.0] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    if len(gains) < length: return result
    avg_g = sum(gains[:length]) / length
    avg_l = sum(losses[:length]) / length
    result[length] = 100 - 100 / (1 + avg_g / max(avg_l, 0.0001))
    for i in range(length, len(gains)):
        avg_g = (avg_g * (length-1) + gains[i]) / length
        avg_l = (avg_l * (length-1) + losses[i]) / length
        result[i+1] = 100 - 100 / (1 + avg_g / max(avg_l, 0.0001))
    return result

def macd(closes, fast=12, slow=26, signal=9):
    ml = [f - s for f, s in zip(ema(closes, fast), ema(closes, slow))]
    sl = ema(ml, signal)
    return ml, sl, [m - s for m, s in zip(ml, sl)]

def bollinger(closes, length=20, dev=2.0):
    basis = sma(closes, length)
    upper, lower = [], []
    for i in range(len(closes)):
        w = closes[max(0, i-length+1):i+1]
        std = math.sqrt(sum((x - sum(w)/len(w))**2 for x in w) / len(w))
        upper.append(basis[i] + dev * std)
        lower.append(basis[i] - dev * std)
    return basis, upper, lower

def atr(highs, lows, closes, length=14):
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, len(closes))]
    return sma(trs, length)

def stoch_rsi(closes, rsi_len=14, stoch_len=14, k_smooth=3, d_smooth=3):
    rsi_vals = rsi(closes, rsi_len)
    raw_k = []
    for i in range(len(rsi_vals)):
        w = rsi_vals[max(0, i-stoch_len+1):i+1]
        mn, mx = min(w), max(w)
        raw_k.append(((rsi_vals[i]-mn)/(mx-mn)*100) if mx != mn else 50)
    return sma(raw_k, k_smooth), sma(sma(raw_k, k_smooth), d_smooth)

def vwap(highs, lows, closes, volumes):
    result = []
    cum_vol, cum_pv = 0, 0
    for i in range(len(closes)):
        typical = (highs[i] + lows[i] + closes[i]) / 3
        cum_vol += volumes[i]
        cum_pv += typical * volumes[i]
        result.append(cum_pv / cum_vol if cum_vol > 0 else typical)
    return result

def obv(closes, volumes):
    result = [0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:
            result.append(result[-1] + volumes[i])
        elif closes[i] < closes[i-1]:
            result.append(result[-1] - volumes[i])
        else:
            result.append(result[-1])
    return result

def supertrend(highs, lows, closes, atr_len=10, mult=3.0):
    atr_vals = atr(highs, lows, closes, atr_len)
    result = [closes[0]]
    direction = 1
    for i in range(1, len(closes)):
        if len(atr_vals) <= i: break
        up = (highs[i] + lows[i]) / 2 + mult * atr_vals[i]
        dn = (highs[i] + lows[i]) / 2 - mult * atr_vals[i]
        if closes[i] > result[-1]:
            result.append(max(result[-1], dn) if result[-1] < closes[i-1] else dn)
        else:
            result.append(min(result[-1], up) if result[-1] > closes[i-1] else up)
    return result


# ── Advanced Indicators ──────────────────────────────────────────────────────

def adx(highs, lows, closes, length=14):
    plus_dm, minus_dm, tr_list = [0], [0], [0]
    for i in range(1, len(closes)):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        tr_list.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    atr14 = sma(tr14 := tr_list, length)
    plus_di_raw = [0] * len(closes)
    minus_di_raw = [0] * len(closes)
    dx_vals = [0] * len(closes)
    for i in range(length, len(closes)):
        if atr14[i] > 0:
            plus_di_raw[i] = (plus_dm[i] / atr14[i]) * 100
            minus_di_raw[i] = (minus_dm[i] / atr14[i]) * 100
        denom = plus_di_raw[i] + minus_di_raw[i]
        dx_vals[i] = abs(plus_di_raw[i] - minus_di_raw[i]) / denom * 100 if denom > 0 else 0
    adx_vals = sma(dx_vals, length)
    return adx_vals, plus_di_raw, minus_di_raw


def ichimoku(highs, lows, closes, tenkan=9, kijun=26, senkou_b=52):
    def mid(h, l, period):
        result = [0] * len(h)
        for i in range(period-1, len(h)):
            wh = h[i-period+1:i+1]
            wl = l[i-period+1:i+1]
            result[i] = (max(wh) + min(wl)) / 2
        return result
    tenkan_sen = mid(highs, lows, tenkan)
    kijun_sen = mid(highs, lows, kijun)
    senkou_a = [(t+k)/2 for t, k in zip(tenkan_sen, kijun_sen)]
    senkou_b_line = mid(highs, lows, senkou_b)
    return tenkan_sen, kijun_sen, senkou_a, senkou_b_line


def pivot_points(highs, lows, closes):
    pp = (highs[-1] + lows[-1] + closes[-1]) / 3
    r1 = 2 * pp - lows[-1]
    s1 = 2 * pp - highs[-1]
    r2 = pp + (highs[-1] - lows[-1])
    s2 = pp - (highs[-1] - lows[-1])
    r3 = highs[-1] + 2 * (pp - lows[-1])
    s3 = lows[-1] - 2 * (highs[-1] - pp)
    return {"pp": round(pp, 4), "r1": round(r1, 4), "r2": round(r2, 4), "r3": round(r3, 4),
            "s1": round(s1, 4), "s2": round(s2, 4), "s3": round(s3, 4)}


def detect_patterns(ohlcv):
    patterns = []
    for i in range(2, min(len(ohlcv), 50)):
        c = ohlcv[-i]
        o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
        body = abs(cl - o)
        upper = h - max(o, cl)
        lower = min(o, cl) - l
        total_range = h - l if h != l else 0.0001
        prev = ohlcv[-(i+1)]
        pbody = abs(prev["close"] - prev["open"])

        if body < total_range * 0.1 and total_range > 0:
            patterns.append({"type": "doji", "bar": i, "signal": "indecision"})
        if lower > body * 2 and upper < body * 0.3 and cl > o:
            patterns.append({"type": "hammer", "bar": i, "signal": "bullish_reversal"})
        if upper > body * 2 and lower < body * 0.3 and cl < o:
            patterns.append({"type": "shooting_star", "bar": i, "signal": "bearish_reversal"})
        if cl > o and prev["close"] < prev["open"] and o <= prev["close"] and cl >= prev["open"] and body > pbody * 1.2:
            patterns.append({"type": "bullish_engulfing", "bar": i, "signal": "bullish_reversal"})
        if cl < o and prev["close"] > prev["open"] and o >= prev["close"] and cl <= prev["open"] and body > pbody * 1.2:
            patterns.append({"type": "bearish_engulfing", "bar": i, "signal": "bearish_reversal"})
        if lower > body * 3 and upper < body * 0.1:
            patterns.append({"type": "pin_bar_low", "bar": i, "signal": "bullish_reversal"})
        if upper > body * 3 and lower < body * 0.1:
            patterns.append({"type": "pin_bar_high", "bar": i, "signal": "bearish_reversal"})
    return patterns[:10]


def find_support_resistance(ohlcv, lookback=50):
    if len(ohlcv) < 10:
        return {"support": [], "resistance": []}
    window = ohlcv[-lookback:] if len(ohlcv) >= lookback else ohlcv
    highs_list = sorted([c["high"] for c in window], reverse=True)
    lows_list = sorted([c["low"] for c in window])
    clusters_s, clusters_r = [], []
    price_range = highs_list[0] - lows_list[0] if highs_list[0] != lows_list[0] else 1
    tolerance = price_range * 0.005

    for p in lows_list[:15]:
        nearby = [c for c in lows_list if abs(c - p) < tolerance]
        if len(nearby) >= 2:
            level = sum(nearby) / len(nearby)
            if not any(abs(level - s) < tolerance for s in clusters_s):
                clusters_s.append(round(level, 4))
    for p in highs_list[:15]:
        nearby = [c for c in highs_list if abs(c - p) < tolerance]
        if len(nearby) >= 2:
            level = sum(nearby) / len(nearby)
            if not any(abs(level - r) < tolerance for r in clusters_r):
                clusters_r.append(round(level, 4))

    current = ohlcv[-1]["close"]
    support = sorted([s for s in clusters_s if s < current], reverse=True)[:3]
    resistance = sorted([r for r in clusters_r if r > current])[:3]
    return {"support": support, "resistance": resistance}


# ── Multi-Timeframe Confluence ────────────────────────────────────────────────

def multi_tf_analysis(symbol):
    if "/" not in symbol:
        return {"confluence": "neutral", "score": 50, "timeframes": {}}
    tfs = {"5m": None, "15m": None, "1h": None, "4h": None, "1d": None}
    for tf in tfs:
        try:
            raw = fetch_ohlcv(symbol, tf, 250)
            if raw and len(raw) >= 50:
                tfs[tf] = compute_indicators(raw)
        except Exception:
            pass
    bull_count = sum(1 for tf, ind in tfs.items() if ind and ind.get("trend") == "bullish")
    bear_count = sum(1 for tf, ind in tfs.items() if ind and ind.get("trend") == "bearish")
    total = sum(1 for v in tfs.values() if v)
    if total == 0:
        return {"confluence": "neutral", "score": 50, "timeframes": {}}
    score = 50 + (bull_count - bear_count) / total * 50
    confluence = "bullish" if score > 60 else "bearish" if score < 40 else "neutral"
    tf_summary = {}
    for tf, ind in tfs.items():
        if ind:
            tf_summary[tf] = {"trend": ind.get("trend", "neutral"), "rsi": ind.get("rsi", 50),
                              "strength": ind.get("strength", 50)}
    return {"confluence": confluence, "score": round(score), "bull_timeframes": bull_count,
            "bear_timeframes": bear_count, "total_timeframes": total, "timeframes": tf_summary}


# ── Backtester ────────────────────────────────────────────────────────────────

def run_backtest(symbol, strategy="trend", tf="15m", limit=1000, risk_pct=1.0):
    ohlcv = fetch_ohlcv(symbol, tf, limit)
    if not ohlcv or len(ohlcv) < 100:
        return {"error": "Insufficient data", "trades": [], "metrics": {}}
    closes = [c["close"] for c in ohlcv]
    highs = [c["high"] for c in ohlcv]
    lows = [c["low"] for c in ohlcv]
    e9 = ema(closes, 9)
    e21 = ema(closes, 21)
    e200 = ema(closes, 200)
    rsi14 = rsi(closes, 14)
    _, _, macd_h = macd(closes)
    bb_b, bb_u, bb_l = bollinger(closes)
    atr14 = atr(highs, lows, closes, 14)
    balance = 10000.0
    trades = []
    pos = None

    for i in range(100, len(ohlcv)):
        price = closes[i]
        a = atr14[i] if i < len(atr14) else price * 0.01

        if pos:
            if pos["side"] == "long":
                pos["pnl"] = (price - pos["entry"]) * pos["amount"]
                if price <= pos["sl"] or price >= pos["tp"]:
                    balance += pos["pnl"]
                    pos["exit"] = price
                    pos["exit_time"] = ohlcv[i]["time"]
                    trades.append(pos)
                    pos = None
            else:
                pos["pnl"] = (pos["entry"] - price) * pos["amount"]
                if price >= pos["sl"] or price <= pos["tp"]:
                    balance += pos["pnl"]
                    pos["exit"] = price
                    pos["exit_time"] = ohlcv[i]["time"]
                    trades.append(pos)
                    pos = None
        else:
            signal = None
            if strategy == "trend":
                if e9[i] > e21[i] and price > e200[i] and macd_h[i] > 0 and rsi14[i] > 50:
                    signal = "long"
                elif e9[i] < e21[i] and price < e200[i] and macd_h[i] < 0 and rsi14[i] < 50:
                    signal = "short"
            elif strategy == "mean_reversion":
                if price < bb_l[i] and rsi14[i] < 30:
                    signal = "long"
                elif price > bb_u[i] and rsi14[i] > 70:
                    signal = "short"
            elif strategy == "breakout":
                if i >= 20:
                    high_20 = max(closes[i-20:i])
                    low_20 = min(closes[i-20:i])
                    if price > high_20:
                        signal = "long"
                    elif price < low_20:
                        signal = "short"

            if signal and a > 0:
                risk_amount = balance * (risk_pct / 100)
                sl_dist = a * 1.5
                tp_dist = a * 3.0
                sl = price - sl_dist if signal == "long" else price + sl_dist
                tp = price + tp_dist if signal == "long" else price - tp_dist
                amount = risk_amount / sl_dist
                pos = {"side": signal, "entry": price, "sl": sl, "tp": tp,
                       "amount": amount, "entry_time": ohlcv[i]["time"], "pnl": 0}

    if pos:
        balance += pos["pnl"]
        trades.append(pos)

    return _calc_bt_metrics(trades, balance, 10000.0)


def _calc_bt_metrics(trades, final_balance, initial):
    if not trades:
        return {"trades": [], "metrics": {"total_trades": 0, "win_rate": 0, "profit_factor": 0,
                "total_pnl": 0, "total_pnl_pct": 0, "sharpe": 0, "sortino": 0, "max_drawdown": 0}}
    wins = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) <= 0]
    tw = sum(t["pnl"] for t in wins)
    tl = abs(sum(t["pnl"] for t in losses))
    wr = len(wins) / len(trades) * 100
    pf = tw / tl if tl > 0 else 0
    pnls = [t.get("pnl", 0) for t in trades]
    avg_ret = sum(pnls) / len(pnls)
    std_ret = math.sqrt(sum((p - avg_ret)**2 for p in pnls) / len(pnls)) if len(pnls) > 1 else 1
    downside = [p for p in pnls if p < 0]
    downside_std = math.sqrt(sum(p**2 for p in downside) / len(downside)) if downside else 1
    sharpe = (avg_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0
    sortino = (avg_ret / downside_std * math.sqrt(252)) if downside_std > 0 else 0
    eq = [initial]
    for p in pnls:
        eq.append(eq[-1] + p)
    peak = eq[0]; mdd = 0
    for e in eq:
        if e > peak: peak = e
        mdd = max(mdd, (peak - e) / peak * 100)
    return {
        "trades": [{"side": t["side"], "entry": round(t["entry"], 2), "exit": round(t.get("exit", 0), 2),
                     "pnl": round(t.get("pnl", 0), 2)} for t in trades],
        "metrics": {
            "total_trades": len(trades), "win_rate": round(wr, 1), "profit_factor": round(pf, 2),
            "total_pnl": round(final_balance - initial, 2),
            "total_pnl_pct": round((final_balance - initial) / initial * 100, 2),
            "sharpe": round(sharpe, 2), "sortino": round(sortino, 2),
            "max_drawdown": round(mdd, 2), "avg_trade": round(avg_ret, 2),
            "best_trade": round(max(pnls), 2), "worst_trade": round(min(pnls), 2),
            "avg_win": round(tw / len(wins), 2) if wins else 0,
            "avg_loss": round(tl / len(losses), 2) if losses else 0,
            "final_balance": round(final_balance, 2),
        }
    }


# ── Advanced Risk Management ─────────────────────────────────────────────────

class RiskManager:
    def __init__(self):
        self.daily_pnl = 0
        self.daily_trades = 0
        self.max_daily_loss = -500
        self.max_daily_trades = 20
        self.max_drawdown_pct = 15.0
        self.peak_equity = 10000.0
        self.last_reset = datetime.now(timezone.utc).date()

    def _check_daily_reset(self):
        today = datetime.now(timezone.utc).date()
        if today != self.last_reset:
            self.daily_pnl = 0
            self.daily_trades = 0
            self.last_reset = today

    def can_trade(self, paper_engine):
        self._check_daily_reset()
        if self.daily_trades >= self.max_daily_trades:
            return False, "Daily trade limit reached"
        if self.daily_pnl <= self.max_daily_loss:
            return False, "Daily loss limit hit"
        current_eq = paper_engine.equity
        if current_eq > self.peak_equity:
            self.peak_equity = current_eq
        drawdown = (self.peak_equity - current_eq) / self.peak_equity * 100
        if drawdown >= self.max_drawdown_pct:
            return False, f"Max drawdown {drawdown:.1f}% exceeded"
        return True, "OK"

    def record_trade(self, pnl):
        self._check_daily_reset()
        self.daily_pnl += pnl
        self.daily_trades += 1

    def kelly_size(self, win_rate, avg_win, avg_loss, fraction=0.25):
        if avg_loss == 0 or win_rate == 0:
            return fraction
        wr = win_rate / 100
        b = avg_win / avg_loss if avg_loss > 0 else 1
        kelly = (wr * b - (1 - wr)) / b
        return max(0.01, min(fraction, kelly * fraction))

    def get_status(self, current_equity=None):
        self._check_daily_reset()
        eq = current_equity if current_equity is not None else self.peak_equity
        dd_pct = round((self.peak_equity - eq) / self.peak_equity * 100, 2) if self.peak_equity > 0 else 0
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_trades": self.daily_trades,
            "max_daily_loss": self.max_daily_loss,
            "max_daily_trades": self.max_daily_trades,
            "max_drawdown_pct": self.max_drawdown_pct,
            "drawdown_pct": dd_pct,
        }


risk_manager = RiskManager()


# ── Trailing Stop Manager ────────────────────────────────────────────────────

class TrailingStopManager:
    def __init__(self):
        self.trailing_enabled = True
        self.breakeven_trigger = 1.0  # ATR units
        self.trail_distance = 1.5  # ATR units
        self.partial_close_pct = 50  # close 50% at 2R

    def update(self, pos, current_price, atr_val):
        if not self.trailing_enabled or atr_val <= 0:
            return
        entry = pos.entry
        if pos.side == "long":
            profit = current_price - entry
            if profit >= atr_val * self.breakeven_trigger and pos.sl < entry:
                pos.sl = entry + atr_val * 0.05  # move to breakeven + small buffer
            if profit >= atr_val * 2:
                new_sl = current_price - atr_val * self.trail_distance
                if new_sl > pos.sl:
                    pos.sl = new_sl
        else:
            profit = entry - current_price
            if profit >= atr_val * self.breakeven_trigger and pos.sl > entry:
                pos.sl = entry - atr_val * 0.05
            if profit >= atr_val * 2:
                new_sl = current_price + atr_val * self.trail_distance
                if new_sl < pos.sl:
                    pos.sl = new_sl

trailing_manager = TrailingStopManager()


# ── Portfolio Analytics ───────────────────────────────────────────────────────

def portfolio_analytics(trades):
    if not trades:
        return {"sharpe": 0, "sortino": 0, "calmar": 0, "avg_holding": 0,
                "long_win_rate": 0, "short_win_rate": 0, "best_pair": "N/A", "worst_pair": "N/A"}
    pnls = [t.get("pnl", 0) for t in trades]
    if not pnls:
        return {"sharpe": 0, "sortino": 0, "calmar": 0}
    avg_ret = sum(pnls) / len(pnls)
    std_ret = math.sqrt(sum((p - avg_ret)**2 for p in pnls) / len(pnls)) if len(pnls) > 1 else 1
    downside = [p for p in pnls if p < 0]
    downside_std = math.sqrt(sum(p**2 for p in downside) / len(downside)) if downside else 1
    sharpe = (avg_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0
    sortino = (avg_ret / downside_std * math.sqrt(252)) if downside_std > 0 else 0
    eq = [10000]
    for p in pnls:
        eq.append(eq[-1] + p)
    peak = eq[0]; mdd = 0
    for e in eq:
        if e > peak: peak = e
        mdd = max(mdd, (peak - e) / peak * 100)
    calmar = abs(avg_ret * 252) / (mdd / 100) if mdd > 0 else 0
    longs = [t for t in trades if t.get("side") == "buy"]
    shorts = [t for t in trades if t.get("side") == "sell"]
    lwr = len([t for t in longs if t.get("pnl", 0) > 0]) / len(longs) * 100 if longs else 0
    swr = len([t for t in shorts if t.get("pnl", 0) > 0]) / len(shorts) * 100 if shorts else 0
    pair_pnl = {}
    for t in trades:
        s = t.get("symbol", "N/A")
        pair_pnl[s] = pair_pnl.get(s, 0) + t.get("pnl", 0)
    best_pair = max(pair_pnl, key=pair_pnl.get) if pair_pnl else "N/A"
    worst_pair = min(pair_pnl, key=pair_pnl.get) if pair_pnl else "N/A"
    return {"sharpe": round(sharpe, 2), "sortino": round(sortino, 2),
            "calmar": round(calmar, 2), "avg_holding": 0,
            "long_win_rate": round(lwr, 1), "short_win_rate": round(swr, 1),
            "best_pair": best_pair, "worst_pair": worst_pair,
            "max_drawdown": round(mdd, 2), "total_pnl": round(sum(pnls), 2)}


# ── News Fetcher ──────────────────────────────────────────────────────────────

news_cache = {"items": [], "fetched_at": 0}
NEWS_TTL = 120  # 2 minutes

_BULLISH_WORDS = {"surge", "rally", "bull", "bullish", "soar", "jump", "gain", "rise",
                  "breakout", "moon", "pump", "adoption", "approval", "etf", "institutional",
                  "record high", "all-time high", "ath", "buy", "accumulate", "growth"}
_BEARISH_WORDS = {"crash", "dump", "bear", "bearish", "plunge", "drop", "fall", "decline",
                  "sell", "fear", "panic", "ban", "hack", "exploit", "scam", "lawsuit",
                  "sec", "regulation", "warning", "risk", "collapse", "liquidation", "fud"}
_MAJOR_COINS = {"BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK",
                "DOT", "MATIC", "UNI", "ATOM", "FIL", "APT", "bitcoin", "ethereum",
                "solana", "binance", "ripple", "cardano", "polkadot", "chainlink"}


def _sentiment_score(title: str) -> tuple[str, int]:
    t = title.lower()
    bull = sum(1 for w in _BULLISH_WORDS if w in t)
    bear = sum(1 for w in _BEARISH_WORDS if w in t)
    net = bull - bear
    if net >= 2:
        return "bullish", min(80 + net * 5, 100)
    elif net <= -2:
        return "bearish", min(80 + abs(net) * 5, 100)
    elif net == 1:
        return "bullish", 60
    elif net == -1:
        return "bearish", 60
    return "neutral", 50


def _extract_coins(title: str) -> list[str]:
    found = []
    tu = title.upper()
    for c in _MAJOR_COINS:
        if c.upper() in tu:
            name = c.capitalize()
            if name not in found:
                found.append(name)
    return found[:5]


def fetch_news() -> list[dict]:
    now = time.time()
    if now - news_cache["fetched_at"] < NEWS_TTL and news_cache["items"]:
        return news_cache["items"]

    items = []

    # Source 1: CoinTelegraph RSS
    try:
        url = "https://cointelegraph.com/rss"
        req = urllib.request.Request(url, headers={"User-Agent": "BotTrading/2.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            entries = re.findall(r'<item>(.*?)</item>', raw, re.DOTALL)
            for entry in entries[:15]:
                title_m = re.search(r'<title>(.*?)</title>', entry)
                link_m = re.search(r'<link>(.*?)</link>', entry)
                desc_m = re.search(r'<description><!\[CDATA\[(.*?)\]\]></description>|<description>(.*?)</description>', entry, re.DOTALL)
                pub_m = re.search(r'<pubDate>(.*?)</pubDate>', entry)
                title = (title_m.group(1) or "").strip() if title_m else ""
                link = (link_m.group(1) or "").strip() if link_m else ""
                desc = (desc_m.group(1) or desc_m.group(2) or "").strip() if desc_m else ""
                desc = re.sub(r'<[^>]+>', '', desc)[:300]
                pub = pub_m.group(1).strip() if pub_m else ""
                if not title: continue
                sent, conf = _sentiment_score(title)
                coins = _extract_coins(title + " " + desc)
                ts = int(datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %z").timestamp()) if pub else int(time.time())
                items.append({
                    "id": f"ct_{hash(title)}",
                    "title": title, "body": desc, "source": "CoinTelegraph",
                    "url": link, "image": "", "time": ts,
                    "categories": "news", "tags": "",
                    "sentiment": sent, "confidence": conf, "coins": coins,
                })
    except Exception as e:
        print(f"News CoinTelegraph: {e}")

    # Source 2: Decrypt RSS
    try:
        url2 = "https://decrypt.co/feed"
        req2 = urllib.request.Request(url2, headers={"User-Agent": "BotTrading/2.0"})
        with urllib.request.urlopen(req2, timeout=8) as resp2:
            raw2 = resp2.read().decode("utf-8", errors="replace")
            entries2 = re.findall(r'<item>(.*?)</item>', raw2, re.DOTALL)
            for entry in entries2[:15]:
                title_m = re.search(r'<title>(.*?)</title>', entry)
                link_m = re.search(r'<link>(.*?)</link>', entry)
                desc_m = re.search(r'<description><!\[CDATA\[(.*?)\]\]></description>|<description>(.*?)</description>', entry, re.DOTALL)
                pub_m = re.search(r'<pubDate>(.*?)</pubDate>', entry)
                title = (title_m.group(1) or "").strip() if title_m else ""
                link = (link_m.group(1) or "").strip() if link_m else ""
                desc = (desc_m.group(1) or desc_m.group(2) or "").strip() if desc_m else ""
                desc = re.sub(r'<[^>]+>', '', desc)[:300]
                pub = pub_m.group(1).strip() if pub_m else ""
                if not title: continue
                sent, conf = _sentiment_score(title)
                coins = _extract_coins(title + " " + desc)
                ts = int(datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %z").timestamp()) if pub else int(time.time())
                items.append({
                    "id": f"dc_{hash(title)}",
                    "title": title, "body": desc, "source": "Decrypt",
                    "url": link, "image": "", "time": ts,
                    "categories": "news", "tags": "",
                    "sentiment": sent, "confidence": conf, "coins": coins,
                })
    except Exception as e:
        print(f"News Decrypt: {e}")

    # Source 3: CoinGecko global market overview
    try:
        url3 = "https://api.coingecko.com/api/v3/global"
        req3 = urllib.request.Request(url3, headers={"User-Agent": "BotTrading/2.0"})
        with urllib.request.urlopen(req3, timeout=6) as resp3:
            g = json.loads(resp3.read()).get("data", {})
            mcap = g.get("total_market_cap", {}).get("usd", 0)
            vol = g.get("total_volume", {}).get("usd", 0)
            btc_d = g.get("market_cap_percentage", {}).get("btc", 0)
            chg = g.get("market_cap_change_percentage_24h_usd", 0)
            sent = "bullish" if chg > 1 else "bearish" if chg < -1 else "neutral"
            items.append({
                "id": "cg_global",
                "title": f"Global Crypto Market: ${mcap/1e12:.2f}T cap | BTC dom {btc_d:.1f}% | 24h {chg:+.2f}%",
                "body": f"Total market cap ${mcap/1e12:.2f}T, 24h volume ${vol/1e9:.1f}B. Bitcoin dominance {btc_d:.1f}%. Market {'rising' if chg > 0 else 'falling'} {abs(chg):.2f}%.",
                "source": "CoinGecko", "url": "https://www.coingecko.com/en/global-charts",
                "image": "", "time": int(time.time()),
                "categories": "market_overview", "tags": "global",
                "sentiment": sent, "confidence": 75, "coins": ["BTC", "ETH"],
            })
    except Exception as e:
        print(f"News CoinGecko Global: {e}")

    # Source 4: CoinGecko trending coins
    try:
        url4 = "https://api.coingecko.com/api/v3/search/trending"
        req4 = urllib.request.Request(url4, headers={"User-Agent": "BotTrading/2.0"})
        with urllib.request.urlopen(req4, timeout=6) as resp4:
            data4 = json.loads(resp4.read())
            for coin in data4.get("coins", [])[:8]:
                ci = coin.get("item", {})
                sent, conf = _sentiment_score(f"{ci.get('name', '')} trending market surge")
                items.append({
                    "id": f"cg_{ci.get('id')}",
                    "title": f"Trending: {ci.get('name', '')} ({ci.get('symbol', '').upper()}) — Rank #{ci.get('market_cap_rank', '?')}",
                    "body": f"Currently trending on CoinGecko. Market cap rank #{ci.get('market_cap_rank', '?')}. Strong community momentum.",
                    "source": "CoinGecko", "url": f"https://www.coingecko.com/en/coins/{ci.get('id', '')}",
                    "image": ci.get("large", ""), "time": int(time.time()),
                    "categories": "trending", "tags": ci.get("symbol", ""),
                    "sentiment": sent, "confidence": conf, "coins": [ci.get("name", "")],
                })
    except Exception as e:
        print(f"News CoinGecko Trending: {e}")

    items.sort(key=lambda x: x.get("time", 0), reverse=True)
    news_cache["items"] = items
    news_cache["fetched_at"] = now
    return items


def get_news_sentiment_summary(items: list[dict]) -> dict:
    if not items:
        return {"overall": "neutral", "bullish_pct": 50, "bearish_pct": 50, "total": 0}
    bull = sum(1 for i in items if i["sentiment"] == "bullish")
    bear = sum(1 for i in items if i["sentiment"] == "bearish")
    total = len(items)
    bp = round(bull / total * 100)
    brp = round(bear / total * 100)
    if bp > brp + 10:
        overall = "bullish"
    elif brp > bp + 10:
        overall = "bearish"
    else:
        overall = "neutral"
    return {"overall": overall, "bullish_pct": bp, "bearish_pct": brp, "neutral_pct": 100 - bp - brp, "total": total}


# ── AI Analysis Engine ────────────────────────────────────────────────────────

class AIEngine:
    def __init__(self):
        self.decisions = deque(maxlen=200)
        self.patterns = []
        self.market_regime = "unknown"
        self.sentiment_score = 50
        self.last_analysis = None
        self.analysis_count = 0

    def analyze_signal(self, symbol, side, indicators, tickers):
        score = 0
        reasons = []
        ind = indicators

        if ind.get("trend") == "bullish" and side == "long":
            score += 25; reasons.append("Trend alignment bullish")
        elif ind.get("trend") == "bearish" and side == "short":
            score += 25; reasons.append("Trend alignment bearish")
        else:
            score -= 15; reasons.append("Counter-trend trade")

        rsi_val = ind.get("rsi", 50)
        if side == "long" and 30 < rsi_val < 50:
            score += 15; reasons.append(f"RSI oversold bounce ({rsi_val:.0f})")
        elif side == "short" and 50 < rsi_val < 70:
            score += 15; reasons.append(f"RSI overbought rejection ({rsi_val:.0f})")
        elif side == "long" and rsi_val > 70:
            score -= 10; reasons.append(f"RSI overbought risk ({rsi_val:.0f})")
        elif side == "short" and rsi_val < 30:
            score -= 10; reasons.append(f"RSI oversold risk ({rsi_val:.0f})")

        macd_h = ind.get("macd", {}).get("histogram", 0)
        if (side == "long" and macd_h > 0) or (side == "short" and macd_h < 0):
            score += 10; reasons.append("MACD momentum confirmed")
        else:
            score -= 5; reasons.append("MACD divergence")

        bb = ind.get("bb", {})
        price = tickers.get(symbol, {}).get("price", 0)
        if side == "long" and price and price < bb.get("lower", 0):
            score += 15; reasons.append("Below lower Bollinger Band (mean reversion)")
        elif side == "short" and price and price > bb.get("upper", 0):
            score += 15; reasons.append("Above upper Bollinger Band (mean reversion)")

        atr_val = ind.get("atr", 0)
        if price and atr_val:
            atr_pct = atr_val / price * 100
            if atr_pct > 3:
                score -= 10; reasons.append(f"High volatility risk (ATR {atr_pct:.1f}%)")
            elif atr_pct < 0.5:
                score += 5; reasons.append("Low volatility (trending setup)")

        stoch = ind.get("stoch_rsi", {})
        if side == "long" and stoch.get("k", 50) < 30:
            score += 10; reasons.append("StochRSI oversold")
        elif side == "short" and stoch.get("k", 50) > 70:
            score += 10; reasons.append("StochRSI overbought")

        if ind.get("strength", 0) > 60:
            score += 10; reasons.append("Strong signal confluence")
        elif ind.get("strength", 0) < 40:
            score -= 5; reasons.append("Weak signal confluence")

        ticker = tickers.get(symbol, {})
        vol_24h = ticker.get("volume_24h", 0)
        if vol_24h > 1e9:
            score += 5; reasons.append("High volume (institutional)")
        elif vol_24h < 1e7:
            score -= 5; reasons.append("Low volume risk")

        adx_val = ind.get("adx", 50)
        if adx_val > 25:
            score += 8; reasons.append(f"Strong trend (ADX {adx_val:.0f})")
        elif adx_val < 15:
            score -= 5; reasons.append(f"Weak trend / ranging (ADX {adx_val:.0f})")

        ich = {}
        if ind.get("ichimoku_tenkan"):
            price_above_cloud = price > max(ind.get("ichimoku_senkou_a", 0), ind.get("ichimoku_senkou_b", 0))
            price_below_cloud = price < min(ind.get("ichimoku_senkou_a", 0), ind.get("ichimoku_senkou_b", 0))
            if side == "long" and price_above_cloud:
                score += 8; reasons.append("Above Ichimoku cloud (bullish)")
            elif side == "short" and price_below_cloud:
                score += 8; reasons.append("Below Ichimoku cloud (bearish)")
            elif side == "long" and price_below_cloud:
                score -= 5; reasons.append("Below Ichimoku cloud")

        sr = ind.get("sr", {})
        if price and sr:
            for s in sr.get("support", []):
                if abs(price - s) / price < 0.005:
                    score += 8; reasons.append(f"Near support ${s:.2f}")
            for r in sr.get("resistance", []):
                if abs(price - r) / price < 0.005:
                    score -= 3; reasons.append(f"Near resistance ${r:.2f}")

        patterns = ind.get("patterns", [])
        for p in patterns[:3]:
            if p["bar"] > 0:
                continue  # only care about recent patterns
            if p["signal"] == "bullish_reversal" and side == "long":
                score += 10; reasons.append(f"Bullish pattern: {p['type']}")
            elif p["signal"] == "bearish_reversal" and side == "short":
                score += 10; reasons.append(f"Bearish pattern: {p['type']}")

        score = max(0, min(100, score + 50))
        approved = score >= 60
        confidence = score

        decision = {
            "id": self.analysis_count,
            "symbol": symbol, "side": side,
            "score": score, "approved": approved,
            "confidence": confidence,
            "reasons": reasons,
            "time": datetime.now(timezone.utc).isoformat(),
            "risk_reward": round(ind.get("atr", 0) * 2 / max(ind.get("atr", 0), 0.01), 2) if ind.get("atr", 0) > 0 else 2.0,
        }
        self.decisions.append(decision)
        self.analysis_count += 1
        return decision

    def market_analysis(self, tickers, indicators_cache):
        if not tickers:
            return self.last_analysis or {}

        bullish = sum(1 for s, ind in indicators_cache.items() if ind.get("trend") == "bullish")
        bearish = sum(1 for s, ind in indicators_cache.items() if ind.get("trend") == "bearish")
        total = max(bullish + bearish, 1)

        avg_change = sum(t.get("change_24h", 0) for t in tickers.values()) / max(len(tickers), 1)
        avg_volume = sum(t.get("volume_24h", 0) for t in tickers.values()) / max(len(tickers), 1)

        if avg_change > 2:
            self.market_regime = "strong_bull"
            self.sentiment_score = min(90, self.sentiment_score + 5)
        elif avg_change > 0.5:
            self.market_regime = "bull"
            self.sentiment_score = min(80, self.sentiment_score + 2)
        elif avg_change < -2:
            self.market_regime = "strong_bear"
            self.sentiment_score = max(10, self.sentiment_score - 5)
        elif avg_change < -0.5:
            self.market_regime = "bear"
            self.sentiment_score = max(20, self.sentiment_score - 2)
        else:
            self.market_regime = "neutral"

        self.last_analysis = {
            "regime": self.market_regime,
            "sentiment": self.sentiment_score,
            "bullish_pct": round(bullish / total * 100),
            "bearish_pct": round(bearish / total * 100),
            "avg_change_24h": round(avg_change, 2),
            "avg_volume": round(avg_volume),
            "analysis_count": self.analysis_count,
            "top_opportunities": self._find_opportunities(tickers, indicators_cache),
            "risk_level": "HIGH" if abs(avg_change) > 3 else "MEDIUM" if abs(avg_change) > 1 else "LOW",
            "recommendation": self._get_recommendation(avg_change, bullish, bearish, total),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return self.last_analysis

    def _find_opportunities(self, tickers, indicators_cache):
        opps = []
        for sym, ind in indicators_cache.items():
            t = tickers.get(sym, {})
            price = t.get("price", 0)
            if not price or not ind: continue
            bb = ind.get("bb", {})
            rsi_val = ind.get("rsi", 50)
            if price < bb.get("lower", float("inf")) and rsi_val < 35:
                opps.append({"symbol": sym, "type": "LONG", "reason": f"Below BB lower, RSI={rsi_val:.0f}", "confidence": 75})
            elif price > bb.get("upper", 0) and rsi_val > 65:
                opps.append({"symbol": sym, "type": "SHORT", "reason": f"Above BB upper, RSI={rsi_val:.0f}", "confidence": 70})
        return sorted(opps, key=lambda x: x["confidence"], reverse=True)[:5]

    def _get_recommendation(self, avg_change, bullish, bearish, total):
        if bullish > bearish * 1.5:
            return "LOOKING BULLISH — Consider long entries on dips"
        elif bearish > bullish * 1.5:
            return "LOOKING BEARISH — Consider short entries on rallies"
        elif abs(avg_change) > 3:
            return "HIGH VOLATILITY — Reduce position sizes, widen stops"
        else:
            return "MIXED SIGNALS — Wait for clearer direction"


ai = AIEngine()


# ── Paper Trading Engine ──────────────────────────────────────────────────────

class PaperPosition:
    def __init__(self, symbol, side, entry_price, amount, sl, tp, ai_score=0):
        self.id = int(time.time() * 1000)
        self.symbol = symbol
        self.side = side  # "long" or "short"
        self.entry = entry_price
        self.amount = amount
        self.sl = sl
        self.tp = tp
        self.trailing_sl = sl
        self.breakeven_hit = False
        self.partial_closed = False
        self.highest_pnl = 0.0
        self.lowest_pnl = 0.0
        self.current = entry_price
        self.pnl = 0.0
        self.pnl_pct = 0.0
        self.rr = 0.0
        self.open_time = datetime.now(timezone.utc).isoformat()
        self.ai_score = ai_score
        self.status = "open"
        self.atr_at_entry = 0

    def update(self, current_price, atr_val=0):
        self.current = current_price
        if self.side == "long":
            self.pnl = (current_price - self.entry) * self.amount
            risk = self.entry - self.sl if self.sl else self.entry * 0.01
            self.rr = round((current_price - self.entry) / risk, 2) if risk > 0 else 0
        else:
            self.pnl = (self.entry - current_price) * self.amount
            risk = self.sl - self.entry if self.sl else self.entry * 0.01
            self.rr = round((self.entry - current_price) / risk, 2) if risk > 0 else 0
        self.pnl_pct = round(self.pnl / (self.entry * self.amount) * 100, 2) if self.entry * self.amount > 0 else 0
        self.highest_pnl = max(self.highest_pnl, self.pnl)
        if atr_val > 0:
            trailing_manager.update(self, current_price, atr_val)

    def should_close(self):
        if self.side == "long":
            if self.current <= self.sl: return "sl_hit"
            if self.current >= self.tp: return "tp_hit"
        else:
            if self.current >= self.sl: return "sl_hit"
            if self.current <= self.tp: return "tp_hit"
        return None

    def to_dict(self):
        return {
            "id": self.id, "symbol": self.symbol, "side": self.side,
            "entry": round(self.entry, 2), "amount": round(self.amount, 6),
            "sl": round(self.sl, 2), "tp": round(self.tp, 2),
            "current": round(self.current, 2),
            "pnl": round(self.pnl, 2), "pnl_pct": round(self.pnl_pct, 2),
            "rr": self.rr, "open_time": self.open_time,
            "ai_score": self.ai_score, "status": self.status,
            "breakeven_hit": self.breakeven_hit, "trailing_sl": round(self.trailing_sl, 2),
            "highest_pnl": round(self.highest_pnl, 2),
        }


class PaperEngine:
    def __init__(self):
        self.balance = 10000.0
        self.initial_balance = 10000.0
        self.positions = []
        self.trades = []
        self.signals = deque(maxlen=200)
        self.equity_curve = [{"time": int(time.time()), "value": self.balance}]
        self.running = False
        self.paper_mode = True
        self.ai_enabled = True
        self.auto_trade = True
        self.selected_pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
                               "AAPL", "MSFT", "NVDA", "TSLA", "AMZN"]
        self.watchlist_top = ["DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
                              "POL/USDT", "UNI/USDT", "ATOM/USDT", "FIL/USDT", "APT/USDT",
                              "GOOGL", "META", "JPM", "V", "WMT"]
        self.timeframe = "15m"
        self.risk_per_trade = 1.0
        self.max_positions = 5
        self.sl_atr_mult = 1.0
        self.tp_atr_mult = 2.0
        self.score_threshold = 5
        self.indicators_cache = {}
        self.last_update = None

    @property
    def equity(self):
        return self.balance + sum(p.pnl for p in self.positions)

    def open_position(self, symbol, side, price, atr=None, ai_score=0):
        if len(self.positions) >= self.max_positions:
            return None, "Max positions reached"
        for p in self.positions:
            if p.symbol == symbol and p.side == side:
                return None, "Position already exists"

        risk_amount = self.balance * (self.risk_per_trade / 100)
        if atr and atr > 0:
            sl_dist = atr * self.sl_atr_mult
            tp_dist = atr * self.tp_atr_mult
        else:
            sl_dist = price * 0.01
            tp_dist = price * 0.02

        if side == "long":
            sl = price - sl_dist
            tp = price + tp_dist
        else:
            sl = price + sl_dist
            tp = price - tp_dist

        amount = risk_amount / sl_dist if sl_dist > 0 else risk_amount / price
        cost = amount * price
        if cost > self.balance * 0.95:
            amount = (self.balance * 0.95) / price

        pos = PaperPosition(symbol, side, price, amount, sl, tp, ai_score)
        self.positions.append(pos)
        return pos, None

    def close_position(self, pos, reason="manual"):
        pos.status = "closed"
        self.balance += pos.pnl
        trade = {
            "id": pos.id, "symbol": pos.symbol, "side": "buy" if pos.side == "long" else "sell",
            "entry": pos.entry, "exit": pos.current, "price": pos.entry,
            "amount": pos.amount, "pnl": round(pos.pnl, 2),
            "pnl_pct": round(pos.pnl_pct, 2),
            "open_time": pos.open_time,
            "close_time": datetime.now(timezone.utc).isoformat(),
            "reason": reason, "ai_score": pos.ai_score,
            "time": datetime.now(timezone.utc).isoformat(),
            "status": "closed",
        }
        self.trades.append(trade)
        self.positions.remove(pos)
        self.equity_curve.append({"time": int(time.time()), "value": round(self.equity, 2)})
        return trade

    def update_positions(self, tickers):
        closed = []
        for pos in self.positions[:]:
            t = tickers.get(pos.symbol)
            if t and t.get("price", 0) > 0:
                ind = self.indicators_cache.get(pos.symbol, {})
                atr_val = ind.get("atr", pos.entry * 0.01)
                pos.update(t["price"], atr_val)
                close_reason = pos.should_close()
                if close_reason:
                    risk_manager.record_trade(pos.pnl)
                    trade = self.close_position(pos, close_reason)
                    closed.append(trade)
        return closed

    def get_metrics(self):
        trades = self.trades
        if not trades:
            return {"total_trades": 0, "win_rate": 0, "profit_factor": 0, "max_drawdown": 0,
                    "avg_win": 0, "avg_loss": 0, "total_pnl": 0, "total_pnl_pct": 0,
                    "expectancy": 0, "best_trade": 0, "worst_trade": 0,
                    "consecutive_wins": 0, "consecutive_losses": 0,
                    "sharpe": 0, "sortino": 0, "calmar": 0}
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]
        tw = sum(t["pnl"] for t in wins) if wins else 0
        tl = abs(sum(t["pnl"] for t in losses)) if losses else 0
        wr = len(wins) / len(trades) * 100
        pf = tw / tl if tl > 0 else 0
        aw = tw / len(wins) if wins else 0
        al = tl / len(losses) if losses else 0
        exp = (wr / 100 * aw) - ((1 - wr / 100) * al)
        eq = [self.initial_balance] + [self.initial_balance + sum(t["pnl"] for t in trades[:i+1]) for i in range(len(trades))]
        peak = eq[0]; mdd = 0
        for e in eq:
            if e > peak: peak = e
            mdd = max(mdd, (peak - e) / peak * 100)
        cw, cl, mcw, mcl = 0, 0, 0, 0
        for t in trades:
            if t.get("pnl", 0) > 0: cw += 1; cl = 0; mcw = max(mcw, cw)
            else: cl += 1; cw = 0; mcl = max(mcl, cl)
        all_pnls = [t.get("pnl", 0) for t in trades]
        avg_ret = sum(all_pnls) / len(all_pnls) if all_pnls else 0
        std_ret = math.sqrt(sum((p - avg_ret)**2 for p in all_pnls) / len(all_pnls)) if len(all_pnls) > 1 else 1
        down_side = [p for p in all_pnls if p < 0]
        down_std = math.sqrt(sum(p**2 for p in down_side) / len(down_side)) if down_side else 1
        sharpe = round((avg_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0, 2)
        sortino = round((avg_ret / down_std * math.sqrt(252)) if down_std > 0 else 0, 2)
        calmar = round(abs(avg_ret * 252) / (mdd / 100), 2) if mdd > 0 else 0
        return {
            "total_trades": len(trades), "win_rate": round(wr, 1),
            "profit_factor": round(pf, 2), "max_drawdown": round(mdd, 2),
            "avg_win": round(aw, 2), "avg_loss": round(al, 2),
            "total_pnl": round(self.equity - self.initial_balance, 2),
            "total_pnl_pct": round((self.equity - self.initial_balance) / self.initial_balance * 100, 2),
            "expectancy": round(exp, 2),
            "best_trade": round(max(all_pnls), 2) if all_pnls else 0,
            "worst_trade": round(min(all_pnls), 2) if all_pnls else 0,
            "consecutive_wins": mcw, "consecutive_losses": mcl,
            "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        }


paper = PaperEngine()
ticker_cache, ticker_cache_time = {}, 0
candle_cache = {}  # symbol -> latest candle for real-time updates


# ── Trial / Demo Mode ─────────────────────────────────────────────────────────

class TrialEngine:
    def __init__(self):
        self.active = False
        self.balance = 100000.0
        self.initial_balance = 100000.0
        self.positions = []
        self.trades = []
        self.signals = deque(maxlen=200)
        self.equity_curve = [{"time": int(time.time()), "value": self.balance}]
        self.start_time = None
        self.asset_type = "all"  # "all", "crypto", "stock"

    @property
    def equity(self):
        return self.balance + sum(p.get("pnl", 0) for p in self.positions)

    def start(self):
        self.active = True
        self.balance = self.initial_balance
        self.positions = []
        self.trades = []
        self.signals.clear()
        self.equity_curve = [{"time": int(time.time()), "value": self.balance}]
        self.start_time = datetime.now(timezone.utc).isoformat()

    def reset(self):
        self.active = False
        self.balance = self.initial_balance
        self.positions = []
        self.trades = []
        self.signals.clear()
        self.equity_curve = [{"time": int(time.time()), "value": self.balance}]
        self.start_time = None

    def open_position(self, symbol, side, price, amount, sl, tp, ai_score=0):
        if not self.active:
            return None, "Trial mode not active"
        for p in self.positions:
            if p["symbol"] == symbol and p["side"] == side:
                return None, "Position already exists"
        pos = {
            "id": int(time.time() * 1000),
            "symbol": symbol, "side": side, "entry": price,
            "amount": amount, "sl": sl, "tp": tp,
            "current": price, "pnl": 0.0, "pnl_pct": 0.0,
            "open_time": datetime.now(timezone.utc).isoformat(),
            "ai_score": ai_score,
        }
        self.positions.append(pos)
        return pos, None

    def close_position(self, pos, reason="manual"):
        pnl = pos.get("pnl", 0)
        self.balance += pnl
        trade = {
            "id": pos["id"], "symbol": pos["symbol"], "side": pos["side"],
            "entry": pos["entry"], "exit": pos["current"],
            "pnl": round(pnl, 2), "reason": reason,
            "open_time": pos["open_time"],
            "close_time": datetime.now(timezone.utc).isoformat(),
        }
        self.trades.append(trade)
        self.positions.remove(pos)
        self.equity_curve.append({"time": int(time.time()), "value": round(self.equity, 2)})
        return trade

    def update_positions(self, tickers):
        closed = []
        for pos in self.positions[:]:
            t = tickers.get(pos["symbol"])
            if t and t.get("price", 0) > 0:
                price = t["price"]
                pos["current"] = price
                if pos["side"] == "long":
                    pos["pnl"] = (price - pos["entry"]) * pos["amount"]
                    risk = pos["entry"] - pos["sl"] if pos["sl"] else pos["entry"] * 0.01
                else:
                    pos["pnl"] = (pos["entry"] - price) * pos["amount"]
                    risk = pos["sl"] - pos["entry"] if pos["sl"] else pos["entry"] * 0.01
                pos["pnl_pct"] = round(pos["pnl"] / (pos["entry"] * pos["amount"]) * 100, 2) if pos["entry"] * pos["amount"] > 0 else 0
                hit = None
                if pos["side"] == "long":
                    if price <= pos["sl"]: hit = "sl"
                    elif price >= pos["tp"]: hit = "tp"
                else:
                    if price >= pos["sl"]: hit = "sl"
                    elif price <= pos["tp"]: hit = "tp"
                if hit:
                    trade = self.close_position(pos, hit)
                    closed.append(trade)
        return closed

    def get_metrics(self):
        trades = self.trades
        if not trades:
            return {"total_trades": 0, "win_rate": 0, "profit_factor": 0,
                    "total_pnl": 0, "total_pnl_pct": 0, "best_trade": 0, "worst_trade": 0}
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]
        tw = sum(t["pnl"] for t in wins) if wins else 0
        tl = abs(sum(t["pnl"] for t in losses)) if losses else 0
        wr = len(wins) / len(trades) * 100
        pf = tw / tl if tl > 0 else 0
        all_pnls = [t.get("pnl", 0) for t in trades]
        return {
            "total_trades": len(trades), "win_rate": round(wr, 1),
            "profit_factor": round(pf, 2),
            "total_pnl": round(self.equity - self.initial_balance, 2),
            "total_pnl_pct": round((self.equity - self.initial_balance) / self.initial_balance * 100, 2),
            "best_trade": round(max(all_pnls), 2) if all_pnls else 0,
            "worst_trade": round(min(all_pnls), 2) if all_pnls else 0,
        }

trial = TrialEngine()


# ── Data Fetching ─────────────────────────────────────────────────────────────

def fetch_tickers():
    global ticker_cache, ticker_cache_time
    now = time.time()
    if now - ticker_cache_time < 5 and ticker_cache:
        return ticker_cache
    try:
        ex = get_exchange()
        crypto_syms = [s for s in paper.selected_pairs + paper.watchlist_top if "/" in s]
        stock_syms = [s for s in paper.selected_pairs + paper.watchlist_top if "/" not in s]
        tickers = {}
        # Crypto tickers
        if crypto_syms:
            try:
                raw = ex.fetch_tickers([s + ":USDT" for s in crypto_syms])
                for sym in crypto_syms:
                    for key in raw:
                        if key == sym or key.startswith(sym + ":"):
                            t = raw[key]
                            tickers[sym] = {
                                "symbol": sym,
                                "price": t.get("last", 0) or 0,
                                "change_24h": t.get("percentage", 0) or 0,
                                "volume_24h": t.get("quoteVolume", 0) or 0,
                                "high_24h": t.get("high", 0) or 0,
                                "low_24h": t.get("low", 0) or 0,
                                "bid": t.get("bid", 0) or 0,
                                "ask": t.get("ask", 0) or 0,
                                "spread": ((t.get("ask", 0) or 0) - (t.get("bid", 0) or 0)),
                                "asset": "crypto",
                            }
                            break
            except Exception as batch_err:
                print(f"Batch tickers failed: {batch_err}, falling back to individual")
                for sym in crypto_syms:
                    try:
                        t = ex.fetch_ticker(sym + ":USDT")
                        tickers[sym] = {
                            "symbol": sym, "price": t.get("last", 0) or 0,
                            "change_24h": t.get("percentage", 0) or 0,
                            "volume_24h": t.get("quoteVolume", 0) or 0,
                            "high_24h": t.get("high", 0) or 0,
                            "low_24h": t.get("low", 0) or 0,
                            "bid": t.get("bid", 0) or 0,
                            "ask": t.get("ask", 0) or 0,
                            "spread": 0,
                            "asset": "crypto",
                        }
                    except Exception as e:
                        print(f"Ticker {sym}: {e}")
        # Stock tickers
        if stock_syms:
            try:
                batch = yf.Tickers(" ".join(stock_syms))
                for sym in stock_syms:
                    try:
                        info = batch.tickers[sym].fast_info
                        price = getattr(info, 'last_price', None) or getattr(info, 'previous_close', 0) or 0
                        prev = getattr(info, 'previous_close', price) or price
                        mcap = getattr(info, 'market_cap', 0) or 0
                        chg = ((price - prev) / prev * 100) if prev and price else 0
                        tickers[sym] = {
                            "symbol": sym, "price": round(price, 2),
                            "change_24h": round(chg, 2),
                            "volume_24h": mcap,
                            "high_24h": round(price * 1.01, 2),
                            "low_24h": round(price * 0.99, 2),
                            "bid": round(price * 0.999, 2),
                            "ask": round(price * 1.001, 2),
                            "spread": round(price * 0.002, 2),
                            "asset": "stock",
                        }
                    except Exception as e:
                        print(f"Stock ticker {sym}: {e}")
            except Exception as e:
                print(f"Stock batch: {e}")
        ticker_cache, ticker_cache_time = tickers, now
        return tickers
    except Exception as e:
        print(f"Tickers: {e}")
        return ticker_cache or {}


def fetch_ohlcv(symbol, tf="15m", limit=250):
    if "/" not in symbol:
        return fetch_stock_ohlcv(symbol, tf, limit)
    try:
        ex = get_exchange()
        raw = ex.fetch_ohlcv(symbol + ":USDT", tf, limit=limit)
        candles = [{"time": c[0]//1000, "open": c[1], "high": c[2],
                 "low": c[3], "close": c[4], "volume": c[5]} for c in raw]
        if candles:
            candle_cache[symbol] = candles[-1]
        return candles
    except Exception as e:
        print(f"OHLCV {symbol}: {e}")
        return []


def fetch_latest_candle(symbol, tf="15m"):
    try:
        ex = get_exchange()
        raw = ex.fetch_ohlcv(symbol + ":USDT", tf, limit=50)
        if raw:
            c = raw[-1]
            candle = {"time": c[0]//1000, "open": c[1], "high": c[2],
                      "low": c[3], "close": c[4], "volume": c[5]}
            if len(raw) >= 14:
                highs = [x[2] for x in raw]
                lows = [x[3] for x in raw]
                closes = [x[4] for x in raw]
                volumes = [x[5] for x in raw]
                candle["atr"] = round(atr(highs, lows, closes, 14)[-1], 2)
                candle["vwap"] = round(vwap(highs, lows, closes, volumes)[-1], 2)
            candle_cache[symbol] = candle
            return candle
    except Exception:
        pass
    return candle_cache.get(symbol)


def fetch_order_book(symbol, limit=15):
    if "/" not in symbol:
        return fetch_stock_order_book(symbol, limit)
    try:
        ex = get_exchange()
        ob = ex.fetch_order_book(symbol + ":USDT", limit)
        return {
            "bids": [[b[0], b[1]] for b in ob["bids"][:limit]],
            "asks": [[a[0], a[1]] for a in ob["asks"][:limit]],
        }
    except Exception:
        return {"bids": [], "asks": []}


def compute_indicators(ohlcv):
    if len(ohlcv) < 50: return {}
    closes = [c["close"] for c in ohlcv]
    highs = [c["high"] for c in ohlcv]
    lows = [c["low"] for c in ohlcv]
    volumes = [c["volume"] for c in ohlcv]

    e9 = ema(closes, 9); e21 = ema(closes, 21); e50 = ema(closes, 50); e200 = ema(closes, 200)
    rsi14 = rsi(closes, 14)
    macd_l, macd_s, macd_h = macd(closes)
    bb_b, bb_u, bb_l = bollinger(closes)
    atr14 = atr(highs, lows, closes, 14)
    sk, sd = stoch_rsi(closes)
    vw = vwap(highs, lows, closes, volumes)
    obv_vals = obv(closes, volumes)
    st = supertrend(highs, lows, closes)
    adx_vals, adx_plus_vals, adx_minus_vals = adx(highs, lows, closes)
    ich_tenkan, ich_kijun, ich_senkou_a, ich_senkou_b = ichimoku(highs, lows, closes)
    pivots = pivot_points(highs, lows, closes)
    patterns = detect_patterns(ohlcv)
    sr_levels = find_support_resistance(ohlcv)

    sigs = {"long": 0, "short": 0}
    if e9[-1] > e21[-1]: sigs["long"] += 1
    else: sigs["short"] += 1
    if closes[-1] > e200[-1]: sigs["long"] += 1
    else: sigs["short"] += 1
    if 30 < rsi14[-1] < 70:
        sigs["long" if rsi14[-1] > 50 else "short"] += 1
    else:
        sigs["short" if rsi14[-1] > 70 else "long"] += 1
    if macd_h[-1] > 0: sigs["long"] += 1
    else: sigs["short"] += 1
    if closes[-1] > bb_u[-1]: sigs["short"] += 1
    elif closes[-1] < bb_l[-1]: sigs["long"] += 1
    if closes[-1] > st[-1]: sigs["long"] += 1
    else: sigs["short"] += 1

    trend = "bullish" if sigs["long"] > sigs["short"] else "bearish" if sigs["short"] > sigs["long"] else "neutral"
    strength = max(sigs["long"], sigs["short"]) / 6 * 100

    step = max(1, len(ohlcv) // 120)
    idx = list(range(0, len(ohlcv), step))
    def downsamp(arr): return [{"time": ohlcv[i]["time"], "value": round(arr[i], 2)} for i in idx if i < len(arr)]

    return {
        "ema9": round(e9[-1], 2), "ema21": round(e21[-1], 2),
        "ema50": round(e50[-1], 2), "ema200": round(e200[-1], 2),
        "rsi": round(rsi14[-1], 1),
        "macd": {"macd": round(macd_l[-1], 4), "signal": round(macd_s[-1], 4), "histogram": round(macd_h[-1], 4)},
        "bb": {"basis": round(bb_b[-1], 2), "upper": round(bb_u[-1], 2), "lower": round(bb_l[-1], 2)},
        "atr": round(atr14[-1], 2),
        "stoch_rsi": {"k": round(sk[-1], 1), "d": round(sd[-1], 1)},
        "vwap": round(vw[-1], 2),
        "obv": obv_vals[-1],
        "supertrend": round(st[-1], 2),
        "adx": round(adx_vals[-1], 1) if adx_vals else 50,
        "adx_plus": round(adx_plus_vals[-1], 1) if adx_plus_vals else 50,
        "adx_minus": round(adx_minus_vals[-1], 1) if adx_minus_vals else 50,
        "ichimoku_tenkan": round(ich_tenkan[-1], 2),
        "ichimoku_kijun": round(ich_kijun[-1], 2),
        "ichimoku_senkou_a": round(ich_senkou_a[-1], 2),
        "ichimoku_senkou_b": round(ich_senkou_b[-1], 2),
        "pivots": pivots,
        "patterns": patterns,
        "sr": sr_levels,
        "signals": sigs, "trend": trend, "strength": round(strength),
        "ema9_s": downsamp(e9), "ema21_s": downsamp(e21), "ema200_s": downsamp(e200),
        "rsi_s": [{"time": ohlcv[i]["time"], "value": round(rsi14[i], 1)} for i in idx if i < len(rsi14)],
        "macd_m": [{"time": ohlcv[i]["time"], "value": round(macd_l[i], 4)} for i in idx if i < len(macd_l)],
        "macd_s_s": [{"time": ohlcv[i]["time"], "value": round(macd_s[i], 4)} for i in idx if i < len(macd_s)],
        "macd_h_s": [{"time": ohlcv[i]["time"], "value": round(macd_h[i], 4),
                       "color": "rgba(0,230,118,0.5)" if macd_h[i] >= 0 else "rgba(255,82,82,0.5)"} for i in idx if i < len(macd_h)],
    }


def calculate_metrics():
    return paper.get_metrics()


# ── API ───────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return (BASE_DIR / "templates" / "index.html").read_text()

@app.get("/api/status")
async def api_status():
    metrics = paper.get_metrics()
    return {
        "running": paper.running, "paper_mode": paper.paper_mode,
        "balance": round(paper.balance, 2), "equity": round(paper.equity, 2),
        "daily_pnl": round(paper.equity - paper.balance, 2),
        "positions_count": len(paper.positions), "max_positions": paper.max_positions,
        "risk_per_trade": paper.risk_per_trade,
        "selected_pairs": paper.selected_pairs, "timeframe": paper.timeframe,
        "ai_enabled": paper.ai_enabled, "auto_trade": paper.auto_trade,
        "score_threshold": paper.score_threshold,
        "sl_atr_mult": paper.sl_atr_mult, "tp_atr_mult": paper.tp_atr_mult,
        "metrics": metrics,
        "trial_active": trial.active, "trial_balance": round(trial.balance, 2),
        "trial_equity": round(trial.equity, 2),
        "trial_pnl": round(trial.equity - trial.initial_balance, 2),
        "trial_positions": len(trial.positions), "trial_trades": len(trial.trades),
        "stock_list": STOCK_LIST[:20],
        "risk": risk_manager.get_status(paper.equity if paper else None),
        "trailing": {"enabled": trailing_manager.trailing_enabled,
                     "breakeven_trigger": trailing_manager.breakeven_trigger,
                     "trail_distance": trailing_manager.trail_distance},
    }

@app.get("/api/tickers")
async def api_tickers():
    return await asyncio.to_thread(fetch_tickers)

@app.get("/api/chart/{symbol}")
async def api_chart(symbol: str, timeframe: str = "15m"):
    sym = symbol.replace("-", "/")
    tf = timeframe if not timeframe.isdigit() else timeframe + "m"
    ohlcv = await asyncio.to_thread(fetch_ohlcv, sym, tf)
    indicators = compute_indicators(ohlcv) if ohlcv else {}
    if ohlcv and indicators:
        paper.indicators_cache[sym] = indicators
    return {"candles": ohlcv, "indicators": indicators}

@app.get("/api/orderbook/{symbol}")
async def api_orderbook(symbol: str):
    return await asyncio.to_thread(fetch_order_book, symbol.replace("-", "/"))

@app.get("/api/positions")
async def api_positions():
    return [p.to_dict() for p in paper.positions]

@app.get("/api/trades")
async def api_trades():
    return list(paper.trades)[-100:]

@app.get("/api/signals")
async def api_signals():
    return list(paper.signals)[-50:]

@app.get("/api/equity")
async def api_equity():
    return paper.equity_curve

@app.get("/api/market-overview")
async def api_market():
    tickers = await asyncio.to_thread(fetch_tickers)
    sorted_t = sorted(tickers.values(), key=lambda x: x.get("change_24h", 0), reverse=True)
    return {
        "gainers": sorted_t[:5], "losers": sorted_t[-5:][::-1],
        "most_volume": sorted(tickers.values(), key=lambda x: x.get("volume_24h", 0), reverse=True)[:5],
    }

@app.get("/api/ai/analysis")
async def ai_analysis():
    tickers = await asyncio.to_thread(fetch_tickers)
    return ai.market_analysis(tickers, paper.indicators_cache)

@app.get("/api/ai/decisions")
async def ai_decisions():
    return list(ai.decisions)[-50:]

@app.get("/api/news")
async def api_news(limit: int = 30):
    items = await asyncio.to_thread(fetch_news)
    summary = get_news_sentiment_summary(items)
    return {"items": items[:limit], "summary": summary}

@app.get("/api/news/sentiment")
async def api_news_sentiment():
    items = await asyncio.to_thread(fetch_news)
    return get_news_sentiment_summary(items)

@app.get("/api/mtf/{symbol}")
async def api_multi_tf(symbol: str):
    sym = symbol.replace("-", "/")
    return await asyncio.to_thread(multi_tf_analysis, sym)

@app.get("/api/backtest/{symbol}")
async def api_backtest(symbol: str, strategy: str = "trend", tf: str = "15m", limit: int = 1000, risk_pct: float = 1.0):
    sym = symbol.replace("-", "/")
    return await asyncio.to_thread(run_backtest, sym, strategy, tf, limit, risk_pct)

@app.get("/api/sr/{symbol}")
async def api_sr(symbol: str):
    sym = symbol.replace("-", "/")
    ohlcv = await asyncio.to_thread(fetch_ohlcv, sym, "15m", 250)
    return find_support_resistance(ohlcv) if ohlcv else {"support": [], "resistance": []}

@app.get("/api/patterns/{symbol}")
async def api_patterns(symbol: str):
    sym = symbol.replace("-", "/")
    ohlcv = await asyncio.to_thread(fetch_ohlcv, sym, "15m", 100)
    return detect_patterns(ohlcv) if ohlcv else []

@app.get("/api/risk/status")
async def api_risk_status():
    return risk_manager.get_status(paper.equity if paper else None)

@app.get("/api/portfolio/analytics")
async def api_portfolio_analytics():
    return portfolio_analytics(paper.trades)

@app.get("/api/trailing/status")
async def api_trailing_status():
    return {"enabled": trailing_manager.trailing_enabled,
            "breakeven_trigger": trailing_manager.breakeven_trigger,
            "trail_distance": trailing_manager.trail_distance}

@app.post("/api/trailing/update")
async def api_trailing_update(cfg: dict = Body(...)):
    if "breakeven_trigger" in cfg:
        trailing_manager.breakeven_trigger = float(cfg["breakeven_trigger"])
    if "trail_distance" in cfg:
        trailing_manager.trail_distance = float(cfg["trail_distance"])
    if "enabled" in cfg:
        trailing_manager.trailing_enabled = bool(cfg["enabled"])
    return {"status": "updated"}

@app.get("/api/hints")
async def api_hints():
    tickers = await asyncio.to_thread(fetch_tickers)
    hints = []
    for sym in paper.selected_pairs:
        ind = paper.indicators_cache.get(sym)
        if not ind:
            tf = paper.timeframe if not paper.timeframe.isdigit() else paper.timeframe + "m"
            ohlcv = await asyncio.to_thread(fetch_ohlcv, sym, tf)
            if ohlcv:
                ind = compute_indicators(ohlcv)
                paper.indicators_cache[sym] = ind
        if not ind:
            continue
        price = tickers.get(sym, {}).get("price", 0)
        if not price:
            continue
        buy_score = 0
        sell_score = 0
        buy_reasons = []
        sell_reasons = []
        trend = ind.get("trend", "neutral")
        rsi_val = ind.get("rsi", 50)
        macd_h = ind.get("macd", {}).get("histogram", 0)
        bb = ind.get("bb", {})
        stoch = ind.get("stoch_rsi", {})
        st = ind.get("supertrend", 0)
        strength = ind.get("strength", 50)
        atr_val = ind.get("atr", 0)
        e9 = ind.get("ema9", 0)
        e21 = ind.get("ema21", 0)
        e200 = ind.get("ema200", 0)
        # BUY scoring
        if trend == "bullish":
            buy_score += 20; buy_reasons.append("Bullish trend")
        if e9 > e21:
            buy_score += 10; buy_reasons.append("EMA9 > EMA21")
        if price > e200:
            buy_score += 10; buy_reasons.append("Above 200 EMA")
        if 25 < rsi_val < 45:
            buy_score += 15; buy_reasons.append(f"RSI oversold bounce ({rsi_val:.0f})")
        elif rsi_val < 25:
            buy_score += 20; buy_reasons.append(f"RSI deeply oversold ({rsi_val:.0f})")
        if macd_h > 0:
            buy_score += 10; buy_reasons.append("MACD positive")
        if price < bb.get("lower", float("inf")):
            buy_score += 15; buy_reasons.append("Below lower Bollinger")
        if stoch.get("k", 50) < 25:
            buy_score += 10; buy_reasons.append("StochRSI oversold")
        if price > st:
            buy_score += 5; buy_reasons.append("Above Supertrend")
        if strength > 60:
            buy_score += 5; buy_reasons.append("Strong confluence")
        # SELL scoring
        if trend == "bearish":
            sell_score += 20; sell_reasons.append("Bearish trend")
        if e9 < e21:
            sell_score += 10; sell_reasons.append("EMA9 < EMA21")
        if price < e200:
            sell_score += 10; sell_reasons.append("Below 200 EMA")
        if 55 < rsi_val < 75:
            sell_score += 15; sell_reasons.append(f"RSI overbought rejection ({rsi_val:.0f})")
        elif rsi_val > 75:
            sell_score += 20; sell_reasons.append(f"RSI deeply overbought ({rsi_val:.0f})")
        if macd_h < 0:
            sell_score += 10; sell_reasons.append("MACD negative")
        if price > bb.get("upper", 0):
            sell_score += 15; sell_reasons.append("Above upper Bollinger")
        if stoch.get("k", 50) > 75:
            sell_score += 10; sell_reasons.append("StochRSI overbought")
        if price < st:
            sell_score += 5; sell_reasons.append("Below Supertrend")
        if strength > 60:
            sell_score += 5; sell_reasons.append("Strong confluence")
        buy_pct = min(buy_score, 99)
        sell_pct = min(sell_score, 99)
        if buy_pct >= 50 and buy_pct > sell_pct:
            hints.append({
                "symbol": sym, "side": "BUY", "confidence": buy_pct,
                "price": price, "reasons": buy_reasons[:5],
                "sl": round(price - atr_val * paper.sl_atr_mult, 2) if atr_val else round(price * 0.99, 2),
                "tp": round(price + atr_val * paper.tp_atr_mult, 2) if atr_val else round(price * 1.02, 2),
                "rr": round(paper.tp_atr_mult / paper.sl_atr_mult, 1),
            })
        elif sell_pct >= 50 and sell_pct > buy_pct:
            hints.append({
                "symbol": sym, "side": "SELL", "confidence": sell_pct,
                "price": price, "reasons": sell_reasons[:5],
                "sl": round(price + atr_val * paper.sl_atr_mult, 2) if atr_val else round(price * 1.01, 2),
                "tp": round(price - atr_val * paper.tp_atr_mult, 2) if atr_val else round(price * 0.98, 2),
                "rr": round(paper.tp_atr_mult / paper.sl_atr_mult, 1),
            })
    hints.sort(key=lambda x: x["confidence"], reverse=True)
    return {"hints": hints[:10], "count": len(hints), "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/ai/analyze/{symbol}/{side}")
async def ai_analyze(symbol: str, side: str):
    sym = symbol.replace("-", "/")
    ind = paper.indicators_cache.get(sym, {})
    tickers = await asyncio.to_thread(fetch_tickers)
    return ai.analyze_signal(sym, side, ind, tickers)

@app.post("/api/start")
async def api_start():
    paper.running = True
    return {"status": "started"}

@app.post("/api/stop")
async def api_stop():
    paper.running = False
    return {"status": "stopped"}

@app.post("/api/toggle-paper")
async def api_toggle_paper():
    paper.paper_mode = not paper.paper_mode
    return {"paper_mode": paper.paper_mode}

@app.post("/api/toggle-ai")
async def api_toggle_ai():
    paper.ai_enabled = not paper.ai_enabled
    return {"ai_enabled": paper.ai_enabled}

@app.post("/api/toggle-auto")
async def api_toggle_auto():
    paper.auto_trade = not paper.auto_trade
    return {"auto_trade": paper.auto_trade}

@app.get("/api/trial/status")
async def api_trial_status():
    return {
        "active": trial.active, "balance": round(trial.balance, 2),
        "initial_balance": trial.initial_balance,
        "equity": round(trial.equity, 2),
        "pnl": round(trial.equity - trial.initial_balance, 2),
        "pnl_pct": round((trial.equity - trial.initial_balance) / trial.initial_balance * 100, 2),
        "positions": trial.positions, "trades": len(trial.trades),
        "start_time": trial.start_time, "metrics": trial.get_metrics(),
        "asset_type": trial.asset_type,
    }

@app.post("/api/trial/start")
async def api_trial_start():
    trial.start()
    return {"status": "started", "balance": trial.balance}

@app.post("/api/trial/reset")
async def api_trial_reset():
    trial.reset()
    return {"status": "reset", "balance": trial.balance}

@app.post("/api/trial/trade")
async def api_trial_trade(order: dict = Body(...)):
    symbol = order.get("symbol", "BTC/USDT")
    side = order.get("side", "buy")
    price = float(order.get("price", 0))
    risk_pct = float(order.get("risk_pct", 2.0))

    if not trial.active:
        return {"status": "error", "error": "Start trial mode first"}

    # Get indicators
    ind = paper.indicators_cache.get(symbol)
    if not ind:
        tf = paper.timeframe if not paper.timeframe.isdigit() else paper.timeframe + "m"
        ohlcv = await asyncio.to_thread(fetch_ohlcv, symbol, tf)
        if ohlcv:
            ind = compute_indicators(ohlcv)
            paper.indicators_cache[symbol] = ind

    # AI analysis
    tickers = await asyncio.to_thread(fetch_tickers)
    ai_decision = ai.analyze_signal(symbol, "long" if side == "buy" else "short", ind, tickers) if paper.ai_enabled else {"approved": True, "score": 100, "reasons": ["AI disabled"]}

    if not ai_decision.get("approved", True):
        return {"status": "rejected_by_ai", "ai": ai_decision}

    atr_val = ind.get("atr", price * 0.01) if ind else price * 0.01
    sl_dist = atr_val * paper.sl_atr_mult
    tp_dist = atr_val * paper.tp_atr_mult
    sl = price - sl_dist if side == "buy" else price + sl_dist
    tp = price + tp_dist if side == "buy" else price - tp_dist
    risk_amount = trial.balance * (risk_pct / 100)
    amount = risk_amount / sl_dist if sl_dist > 0 else risk_amount / price

    pos, err = trial.open_position(symbol, "long" if side == "buy" else "short",
                                    price, amount, sl, tp, ai_decision.get("score", 0))
    if err:
        return {"status": "error", "error": err}

    trial.signals.append({
        "symbol": symbol, "side": side, "price": price,
        "ai_score": ai_decision.get("score", 0),
        "time": datetime.now(timezone.utc).isoformat(),
    })

    return {"status": "opened", "position": pos, "ai": ai_decision}

@app.post("/api/trial/close/{position_id}")
async def api_trial_close(position_id: int):
    for pos in trial.positions:
        if pos["id"] == position_id:
            trade = trial.close_position(pos, "manual")
            return {"status": "closed", "trade": trade}
    return {"status": "not_found"}

@app.post("/api/trial/asset-filter")
async def api_trial_asset_filter(data: dict = Body(...)):
    trial.asset_type = data.get("asset_type", "all")
    return {"asset_type": trial.asset_type}

@app.post("/api/settings")
async def api_settings(s: dict = Body(...)):
    for key in ["risk_per_trade", "sl_atr_mult", "tp_atr_mult"]:
        if key in s: setattr(paper, key, float(s[key]))
    for key in ["max_positions", "score_threshold"]:
        if key in s: setattr(paper, key, int(s[key]))
    if "selected_pairs" in s: paper.selected_pairs = s["selected_pairs"]
    if "timeframe" in s: paper.timeframe = s["timeframe"]
    return {"status": "updated"}

@app.post("/api/trade")
async def api_trade(order: dict = Body(...)):
    symbol = order.get("symbol", "BTC/USDT")
    side = order.get("side", "buy")
    price = float(order.get("price", 0))

    if symbol not in paper.indicators_cache:
        tf = paper.timeframe if not paper.timeframe.isdigit() else paper.timeframe + "m"
        ohlcv = await asyncio.to_thread(fetch_ohlcv, symbol, tf)
        if ohlcv:
            paper.indicators_cache[symbol] = compute_indicators(ohlcv)

    pos_side = "long" if side == "buy" else "short"
    ai_side = pos_side
    ind = paper.indicators_cache.get(symbol, {})
    tickers = await asyncio.to_thread(fetch_tickers)
    ai_decision = ai.analyze_signal(symbol, ai_side, ind, tickers) if paper.ai_enabled else {"approved": True, "score": 100, "reasons": ["AI disabled"]}

    signal = {
        "type": "manual" if not paper.auto_trade else "auto",
        "symbol": symbol, "side": side, "price": price,
        "time": datetime.now(timezone.utc).isoformat(),
        "confidence": ai_decision.get("confidence", 0),
        "ai_approved": ai_decision.get("approved", True),
        "ai_score": ai_decision.get("score", 100),
        "ai_reasons": ai_decision.get("reasons", []),
    }
    paper.signals.append(signal)

    if not ai_decision.get("approved", True):
        return {"status": "rejected_by_ai", "ai": ai_decision}

    atr_val = ind.get("atr", price * 0.01)

    pos, err = paper.open_position(symbol, pos_side, price, atr_val, ai_decision.get("score", 0))
    if err:
        return {"status": "error", "error": err, "ai": ai_decision}

    return {"status": "position_opened", "position": pos.to_dict(), "ai": ai_decision}

@app.post("/api/close/{position_id}")
async def api_close(position_id: int):
    for pos in paper.positions:
        if pos.id == position_id:
            trade = paper.close_position(pos, "manual")
            return {"status": "closed", "trade": trade, "pnl": trade["pnl"], "symbol": trade["symbol"], "side": trade["side"]}
    return {"status": "not_found"}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            tickers = await asyncio.to_thread(fetch_tickers)
            closed = paper.update_positions(tickers)
            for t in closed:
                orig_side = t.get("side", "")
                close_side = "sell" if orig_side == "buy" else "buy"
                paper.signals.append({
                    "type": "auto_close", "symbol": t["symbol"],
                    "side": close_side,
                    "price": t.get("exit", 0),
                    "time": t.get("close_time", ""),
                    "confidence": 100, "ai_approved": True,
                    "ai_score": t.get("ai_score", 0),
                    "ai_reasons": [f"Auto-closed: {t.get('reason', 'unknown')}"],
                })

            # Update trial positions too
            trial_closed = trial.update_positions(tickers)

            metrics = paper.get_metrics()
            market = ai.market_analysis(tickers, paper.indicators_cache)

            latest_candle = await asyncio.to_thread(fetch_latest_candle, paper.selected_pairs[0] if paper.selected_pairs else "BTC/USDT", paper.timeframe if not paper.timeframe.isdigit() else paper.timeframe + "m")

            await ws.send_json({
                "type": "update",
                "balance": round(paper.balance, 2), "equity": round(paper.equity, 2),
                "daily_pnl": round(paper.equity - paper.balance, 2),
                "positions": [p.to_dict() for p in paper.positions],
                "trades": list(paper.trades)[-30:],
                "signals": list(paper.signals)[-20:],
                "metrics": metrics,
                "running": paper.running, "paper_mode": paper.paper_mode,
                "ai_enabled": paper.ai_enabled, "auto_trade": paper.auto_trade,
                "market": market,
                "ai_decisions": list(ai.decisions)[-10:],
                "tickers": {sym: {"price": t.get("price", 0), "change_24h": t.get("change_24h", 0), "asset": t.get("asset", "crypto")} for sym, t in tickers.items()},
                "candle": latest_candle,
                "trial": {
                    "active": trial.active, "balance": round(trial.balance, 2),
                    "equity": round(trial.equity, 2),
                    "pnl": round(trial.equity - trial.initial_balance, 2),
                    "positions": trial.positions, "closed": trial_closed,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8501))
    print("=" * 60)
    print("  Bot Trading AI Terminal v2.0")
    print(f"  Running on http://0.0.0.0:{port}")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=port)
