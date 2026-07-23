"""
Multi-exchange connector using ccxt.
Supports: Binance, Bybit, OKX, Bitget, Gate.io, and more.
"""
import ccxt
import logging
import time
from typing import Optional
from config import ExchangeConfig

logger = logging.getLogger("exchange")


class ExchangeManager:
    def __init__(self, config: ExchangeConfig):
        self.config = config
        self.exchanges: dict[str, ccxt.Exchange] = {}
        self._init_exchanges()

    def _init_exchanges(self):
        for name in self.config.get_exchange_list():
            ex = self._create_exchange(name)
            if ex:
                self.exchanges[name] = ex
                logger.info(f"Connected to {name}")

    def _create_exchange(self, name: str) -> Optional[ccxt.Exchange]:
        name = name.lower()
        try:
            if name == "binance":
                ex = ccxt.binance({
                    "apiKey": self.config.binance_api_key,
                    "secret": self.config.binance_api_secret,
                    "options": {"defaultType": "future"},
                    "sandbox": self.config.binance_testnet,
                })
            elif name == "bybit":
                ex = ccxt.bybit({
                    "apiKey": self.config.bybit_api_key,
                    "secret": self.config.bybit_api_secret,
                    "options": {"defaultType": "swap"},
                    "sandbox": self.config.bybit_testnet,
                })
            elif name == "okx":
                ex = ccxt.okx({
                    "apiKey": self.config.okx_api_key,
                    "secret": self.config.okx_api_secret,
                    "password": self.config.okx_passphrase,
                    "options": {"defaultType": "swap"},
                })
                if self.config.okx_testnet:
                    ex.set_sandbox_mode(True)
            elif name == "bitget":
                ex = ccxt.bitget({
                    "apiKey": self.config.bitget_api_key,
                    "secret": self.config.bitget_api_secret,
                    "password": self.config.bitget_passphrase,
                    "options": {"defaultType": "swap"},
                })
                if self.config.bitget_testnet:
                    ex.set_sandbox_mode(True)
            elif name == "gate":
                ex = ccxt.gate({
                    "apiKey": self.config.gate_api_key,
                    "secret": self.config.gate_api_secret,
                    "options": {"defaultType": "swap"},
                })
            else:
                # Generic ccxt exchange (works for dozens of exchanges)
                exchange_class = getattr(ccxt, name, None)
                if exchange_class:
                    ex = exchange_class({"enableRateLimit": True})
                else:
                    logger.error(f"Unknown exchange: {name}")
                    return None

            ex.load_markets()
            return ex
        except Exception as e:
            logger.error(f"Failed to init {name}: {e}")
            return None

    def get_exchange(self, name: str = None) -> Optional[ccxt.Exchange]:
        name = name or self.config.default_exchange
        return self.exchanges.get(name.lower())

    def get_balance(self, exchange_name: str = None) -> dict:
        ex = self.get_exchange(exchange_name)
        if not ex:
            return {"error": "exchange not connected"}
        try:
            return ex.fetch_balance()
        except Exception as e:
            return {"error": str(e)}

    def get_positions(self, exchange_name: str = None) -> list:
        ex = self.get_exchange(exchange_name)
        if not ex:
            return []
        try:
            positions = ex.fetch_positions()
            return [p for p in positions if float(p.get("contracts", 0)) > 0]
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def set_leverage(self, symbol: str, leverage: int, exchange_name: str = None) -> bool:
        ex = self.get_exchange(exchange_name)
        if not ex:
            return False
        try:
            ex.set_leverage(leverage, symbol)
            return True
        except Exception as e:
            logger.error(f"Error setting leverage: {e}")
            return False

    def open_long(self, symbol: str, amount: float, price: float = None,
                  sl: float = None, tp: float = None, leverage: int = None,
                  exchange_name: str = None, dry_run: bool = False) -> dict:
        return self._place_order("buy", symbol, amount, price, sl, tp, leverage, exchange_name, dry_run)

    def open_short(self, symbol: str, amount: float, price: float = None,
                   sl: float = None, tp: float = None, leverage: int = None,
                   exchange_name: str = None, dry_run: bool = False) -> dict:
        return self._place_order("sell", symbol, amount, price, sl, tp, leverage, exchange_name, dry_run)

    def close_long(self, symbol: str, amount: float = None,
                   exchange_name: str = None, dry_run: bool = False) -> dict:
        return self._close_position("sell", symbol, amount, exchange_name, dry_run)

    def close_short(self, symbol: str, amount: float = None,
                    exchange_name: str = None, dry_run: bool = False) -> dict:
        return self._close_position("buy", symbol, amount, exchange_name, dry_run)

    def _place_order(self, side: str, symbol: str, amount: float, price: float = None,
                     sl: float = None, tp: float = None, leverage: int = None,
                     exchange_name: str = None, dry_run: bool = False) -> dict:
        ex = self.get_exchange(exchange_name)
        if not ex:
            return {"error": "exchange not connected"}

        if dry_run or self.config.dry_run:
            order_type = "limit" if price else "market"
            logger.info(f"[DRY RUN] {side.upper()} {amount} {symbol} @ {price or 'market'}")
            return {
                "id": f"dry_{int(time.time())}",
                "status": "dry_run",
                "side": side,
                "symbol": symbol,
                "amount": amount,
                "price": price,
                "sl": sl,
                "tp": tp,
            }

        try:
            if leverage:
                self.set_leverage(symbol, leverage, exchange_name)

            order_type = "limit" if price else "market"
            order = ex.create_order(symbol, order_type, side, amount, price)
            order_id = order.get("id")

            # Place SL order
            if sl and order_id:
                sl_side = "sell" if side == "buy" else "buy"
                try:
                    ex.create_order(
                        symbol, "stop_market", sl_side, amount,
                        params={"stopPrice": sl, "reduceOnly": True}
                    )
                except Exception as e:
                    logger.warning(f"SL order failed: {e}")

            # Place TP order
            if tp and order_id:
                tp_side = "sell" if side == "buy" else "buy"
                try:
                    ex.create_order(
                        symbol, "take_profit_market", tp_side, amount,
                        params={"stopPrice": tp, "reduceOnly": True}
                    )
                except Exception as e:
                    logger.warning(f"TP order failed: {e}")

            logger.info(f"Order placed: {side} {amount} {symbol} -> {order_id}")
            return order

        except Exception as e:
            logger.error(f"Order failed: {e}")
            return {"error": str(e)}

    def _close_position(self, side: str, symbol: str, amount: float = None,
                        exchange_name: str = None, dry_run: bool = False) -> dict:
        ex = self.get_exchange(exchange_name)
        if not ex:
            return {"error": "exchange not connected"}

        if dry_run or self.config.dry_run:
            logger.info(f"[DRY RUN] CLOSE {side.upper()} {symbol}")
            return {"status": "dry_run", "side": side, "symbol": symbol}

        try:
            if not amount:
                positions = ex.fetch_positions([symbol])
                for p in positions:
                    if float(p.get("contracts", 0)) > 0:
                        amount = float(p["contracts"])
                        break

            if not amount or amount <= 0:
                return {"error": "no position to close"}

            order = ex.create_order(symbol, "market", side, amount, params={"reduceOnly": True})
            logger.info(f"Position closed: {side} {amount} {symbol}")
            return order

        except Exception as e:
            logger.error(f"Close failed: {e}")
            return {"error": str(e)}

    def get_ticker(self, symbol: str, exchange_name: str = None) -> dict:
        ex = self.get_exchange(exchange_name)
        if not ex:
            return {}
        try:
            return ex.fetch_ticker(symbol)
        except Exception as e:
            return {"error": str(e)}
