"""
Signal processor — validates incoming TradingView signals, runs through Claude AI, and routes to exchanges.
"""
import logging
import time
from datetime import datetime, date
from typing import Optional
from config import ExchangeConfig
from exchanges.connector import ExchangeManager
from ai.claude_trader import ClaudeTrader

logger = logging.getLogger("processor")


class TradeRecord:
    def __init__(self, signal: dict, result: dict, timestamp: float, ai_decision: dict = None):
        self.signal = signal
        self.result = result
        self.timestamp = timestamp
        self.time_str = datetime.fromtimestamp(timestamp).isoformat()
        self.ai_decision = ai_decision or {}


class SignalProcessor:
    def __init__(self, config: ExchangeConfig, exchange_mgr: ExchangeManager, ai: ClaudeTrader = None):
        self.config = config
        self.exchanges = exchange_mgr
        self.ai = ai
        self.trade_log: list[TradeRecord] = []
        self.daily_trade_count = 0
        self.daily_pnl = 0.0
        self.last_reset_day = date.today()
        self.open_orders: dict[str, dict] = {}
        self.ai_enabled = ai is not None

    def _reset_daily(self):
        today = date.today()
        if today != self.last_reset_day:
            self.daily_trade_count = 0
            self.daily_pnl = 0.0
            self.last_reset_day = today

    def process(self, signal: dict) -> dict:
        self._reset_daily()

        # Validate
        validation = self._validate(signal)
        if not validation["ok"]:
            return {"status": "rejected", "reason": validation["reason"]}

        # Extract
        bot_id = signal.get("bot_id", "")
        secret = signal.get("secret", "")
        signal_type = signal.get("signal", "").lower()
        symbol = self._resolve_symbol(signal)
        exchange_name = signal.get("exchange", self.config.default_exchange)

        # Risk checks
        risk_check = self._check_risk(signal)
        if not risk_check["ok"]:
            return {"status": "rejected", "reason": risk_check["reason"]}

        # Claude AI confirmation (skip for exit/halt)
        ai_decision = {}
        if self.ai_enabled and signal_type in ("buy", "sell"):
            try:
                ai_decision = self.ai.confirm_signal(signal)
                if not ai_decision.get("approved", True):
                    logger.info(f"AI rejected signal: {ai_decision.get('reason', 'no reason')}")
                    return {
                        "status": "ai_rejected",
                        "reason": ai_decision.get("reason", "AI declined"),
                        "ai_confidence": ai_decision.get("confidence", 0),
                    }
                # Apply AI adjustments
                adj = ai_decision.get("adjustments", {})
                if adj.get("risk_pct"):
                    signal["risk_pct"] = adj["risk_pct"]
                    logger.info(f"AI adjusted risk to {adj['risk_pct']}%")
            except Exception as e:
                logger.warning(f"AI confirmation failed, proceeding: {e}")

        # Execute
        result = self._execute(signal_type, symbol, signal, exchange_name)

        # Log
        record = TradeRecord(signal, result, time.time(), ai_decision)
        self.trade_log.append(record)
        self.daily_trade_count += 1

        # Track daily P&L from closed trades
        trade_pnl = result.get("pnl", result.get("unrealizedPnl", 0)) or 0
        if trade_pnl:
            self.daily_pnl += trade_pnl

        # Feed to AI for learning
        if self.ai_enabled:
            outcome = "win" if result.get("status") != "error" else "loss"
            self.ai.log_trade(signal, result, outcome)

        logger.info(f"Signal processed: {signal_type} {symbol} -> {result.get('status', result.get('error', 'unknown'))}")
        return result

    def _validate(self, signal: dict) -> dict:
        if not signal:
            return {"ok": False, "reason": "empty signal"}

        if signal.get("secret") != self.config.webhook_secret:
            return {"ok": False, "reason": "invalid secret"}

        sig_type = signal.get("signal", "").lower()
        if sig_type not in ("buy", "sell", "exit", "halt"):
            return {"ok": False, "reason": f"unknown signal type: {sig_type}"}

        return {"ok": True}

    def _check_risk(self, signal: dict) -> dict:
        if self.daily_trade_count >= self.config.max_daily_trades:
            return {"ok": False, "reason": f"max daily trades reached ({self.config.max_daily_trades})"}

        if signal.get("signal", "").lower() in ("buy", "sell"):
            if abs(self.daily_pnl) >= self.config.max_daily_loss_pct:
                return {"ok": False, "reason": f"max daily loss reached ({self.config.max_daily_loss_pct}%)"}

        return {"ok": True}

    def _resolve_symbol(self, signal: dict) -> str:
        symbol = signal.get("symbol", "")

        if not symbol:
            # Try to infer from timeframe and common pairs
            price = signal.get("price", 0)
            if price > 50000:
                symbol = "BTC/USDT"
            elif price > 2000:
                symbol = "ETH/USDT"
            elif price > 100:
                symbol = "SOL/USDT"
            else:
                symbol = "BTC/USDT"

        # Normalize to ccxt format
        symbol = symbol.upper().replace("-", "/").replace("_", "/")
        if "/" not in symbol:
            symbol = symbol + "/USDT"

        return symbol

    def _execute(self, signal_type: str, symbol: str, signal: dict, exchange_name: str) -> dict:
        dry_run = self.config.dry_run
        price = signal.get("price")
        sl = signal.get("sl")
        tp = signal.get("tp")
        risk_pct = signal.get("risk_pct", self.config.max_position_pct)

        if signal_type == "halt":
            return self._execute_halt(exchange_name)

        if signal_type == "exit":
            return self._execute_exit(symbol, exchange_name, dry_run)

        if signal_type == "buy":
            return self._execute_long(symbol, price, sl, tp, risk_pct, exchange_name, dry_run)

        if signal_type == "sell":
            return self._execute_short(symbol, price, sl, tp, risk_pct, exchange_name, dry_run)

        return {"error": "unhandled signal type"}

    def _execute_long(self, symbol, price, sl, tp, risk_pct, exchange_name, dry_run) -> dict:
        ex = self.exchanges.get_exchange(exchange_name)
        if not ex:
            return {"error": f"exchange {exchange_name} not connected"}

        # Calculate position size
        amount = self._calc_size(symbol, price, sl, risk_pct, ex, exchange_name)
        if not amount:
            return {"error": "could not calculate position size"}

        return self.exchanges.open_long(
            symbol, amount, price, sl, tp,
            leverage=self.config.default_leverage,
            exchange_name=exchange_name, dry_run=dry_run
        )

    def _execute_short(self, symbol, price, sl, tp, risk_pct, exchange_name, dry_run) -> dict:
        ex = self.exchanges.get_exchange(exchange_name)
        if not ex:
            return {"error": f"exchange {exchange_name} not connected"}

        amount = self._calc_size(symbol, price, sl, risk_pct, ex, exchange_name)
        if not amount:
            return {"error": "could not calculate position size"}

        return self.exchanges.open_short(
            symbol, amount, price, sl, tp,
            leverage=self.config.default_leverage,
            exchange_name=exchange_name, dry_run=dry_run
        )

    def _execute_exit(self, symbol, exchange_name, dry_run) -> dict:
        ex = self.exchanges.get_exchange(exchange_name)
        if not ex:
            return {"error": f"exchange {exchange_name} not connected"}

        try:
            positions = ex.fetch_positions([symbol])
            for p in positions:
                if float(p.get("contracts", 0)) > 0:
                    if p["side"] == "long":
                        return self.exchanges.close_long(symbol, exchange_name=exchange_name, dry_run=dry_run)
                    else:
                        return self.exchanges.close_short(symbol, exchange_name=exchange_name, dry_run=dry_run)
        except Exception as e:
            return {"error": str(e)}

        return {"status": "no_position", "symbol": symbol}

    def _execute_halt(self, exchange_name) -> dict:
        results = []
        ex = self.exchanges.get_exchange(exchange_name)
        if not ex:
            return {"error": f"exchange {exchange_name} not connected"}

        try:
            positions = ex.fetch_positions()
            for p in positions:
                if float(p.get("contracts", 0)) > 0:
                    if p["side"] == "long":
                        result = self.exchanges.close_long(
                            p["symbol"], exchange_name=exchange_name, dry_run=self.config.dry_run
                        )
                    else:
                        result = self.exchanges.close_short(
                            p["symbol"], exchange_name=exchange_name, dry_run=self.config.dry_run
                        )
                    results.append(result)
        except Exception as e:
            return {"error": str(e), "partial": results}

        return {"status": "halt_executed", "closed": len(results), "details": results}

    def _calc_size(self, symbol, price, sl, risk_pct, ex, exchange_name) -> Optional[float]:
        try:
            balance = ex.fetch_balance()
            equity = float(balance.get("total", {}).get("USDT", 0))
        except Exception:
            return None

        if equity <= 0:
            return None

        risk_amount = equity * risk_pct / 100

        if sl and price and sl > 0 and price > 0:
            sl_distance = abs(price - sl)
            if sl_distance > 0:
                amount = risk_amount / sl_distance
            else:
                amount = risk_amount / price
        else:
            amount = risk_amount / price if price else 0

        # Get market precision
        try:
            market = ex.market(symbol)
            amount = ex.amount_to_precision(symbol, amount)
            return float(amount)
        except Exception:
            return amount if amount > 0 else None

    def get_status(self) -> dict:
        return {
            "daily_trades": self.daily_trade_count,
            "daily_pnl": self.daily_pnl,
            "total_trades": len(self.trade_log),
            "exchanges": list(self.exchanges.exchanges.keys()),
            "dry_run": self.config.dry_run,
        }

    def get_recent_trades(self, limit: int = 20) -> list[dict]:
        trades = []
        for record in self.trade_log[-limit:]:
            trades.append({
                "time": record.time_str,
                "signal": record.signal,
                "result": record.result,
            })
        return trades
