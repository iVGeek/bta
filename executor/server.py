"""
Trading Bot Executor — Webhook server that receives TradingView alerts
and executes trades on crypto exchanges via ccxt, with Claude AI integration.

Usage:
    python server.py

Setup:
    1. Copy .env.example to .env and fill in your API keys
    2. pip install -r requirements.txt
    3. python server.py
    4. In TradingView, set alert webhook URL to http://YOUR_IP:8080/webhook
"""
import json
import logging
import sys
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from config import ExchangeConfig
from exchanges.connector import ExchangeManager
from processor import SignalProcessor
from ai.claude_trader import ClaudeTrader

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", mode="a"),
    ],
)
logger = logging.getLogger("server")

# ── Globals ──────────────────────────────────────────────────────────────
config = ExchangeConfig()
exchanges = ExchangeManager(config)

# Init Claude AI
import os
from dotenv import load_dotenv
load_dotenv()
claude_api_key = os.getenv("CLAUDE_API_KEY", "")
ai = ClaudeTrader(claude_api_key) if claude_api_key else None
if ai:
    logger.info("Claude AI enabled")
else:
    logger.info("Claude AI disabled (set CLAUDE_API_KEY in .env)")

processor = SignalProcessor(config, exchanges, ai)

# ── App ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== iVGeek Trading Bot Starting ===")
    logger.info(f"Exchanges: {list(exchanges.exchanges.keys())}")
    logger.info(f"Dry Run: {config.dry_run}")
    logger.info(f"Port: {config.webhook_port}")
    yield
    logger.info("=== iVGeek Trading Bot Stopping ===")

app = FastAPI(title="iVGeek Trading Bot", lifespan=lifespan)


# ── Webhook Endpoint ─────────────────────────────────────────────────────
@app.post("/webhook")
async def webhook(request: Request):
    try:
        body = await request.body()
        signal = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logger.info(f"Webhook received: {json.dumps(signal, indent=2)}")
    result = processor.process(signal)
    return JSONResponse(content=result)


# ── Status ───────────────────────────────────────────────────────────────
@app.get("/status")
async def status():
    return processor.get_status()


@app.get("/trades")
async def trades(limit: int = 20):
    return processor.get_recent_trades(limit)


@app.get("/positions")
async def positions(exchange: str = None):
    positions = exchanges.get_positions(exchange)
    return {"positions": positions}


@app.get("/balance")
async def balance(exchange: str = None):
    return exchanges.get_balance(exchange)


# ── AI Endpoints ─────────────────────────────────────────────────────────
@app.post("/ai/confirm")
async def ai_confirm(request: Request):
    body = await request.json()
    if not ai:
        return {"error": "Claude AI not configured (set CLAUDE_API_KEY)"}
    result = ai.confirm_signal(body)
    return result


@app.post("/ai/sentiment")
async def ai_sentiment(request: Request):
    body = await request.json()
    if not ai:
        return {"error": "Claude AI not configured"}
    symbol = body.get("symbol", "BTC/USDT")
    headlines = body.get("headlines", [])
    return ai.analyze_sentiment(symbol, headlines)


@app.post("/ai/market")
async def ai_market(request: Request):
    body = await request.json()
    if not ai:
        return {"error": "Claude AI not configured"}
    return ai.analyze_market(
        body.get("symbol", "BTC/USDT"),
        body.get("price", 0),
        body.get("indicators", {}),
        body.get("news", ""),
    )


@app.get("/ai/review")
async def ai_review(last_n: int = 20):
    if not ai:
        return {"error": "Claude AI not configured"}
    return ai.review_trades(last_n)


@app.post("/ai/optimize")
async def ai_optimize(request: Request):
    body = await request.json()
    if not ai:
        return {"error": "Claude AI not configured"}
    return ai.optimize_params(
        body.get("strategy", "unknown"),
        body.get("params", {}),
        body.get("performance", {}),
    )


# ── Manual Trade ─────────────────────────────────────────────────────────
@app.post("/trade")
async def manual_trade(request: Request):
    body = await request.json()
    signal = {
        "bot_id": "manual",
        "secret": config.webhook_secret,
        "signal": body.get("side", "buy"),
        "symbol": body.get("symbol", "BTC/USDT"),
        "price": body.get("price"),
        "sl": body.get("sl"),
        "tp": body.get("tp"),
        "risk_pct": body.get("risk_pct", config.max_position_pct),
        "exchange": body.get("exchange", config.default_exchange),
    }
    result = processor.process(signal)
    return JSONResponse(content=result)


@app.post("/close")
async def close_position(request: Request):
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        body = {}
    symbol = body.get("symbol", "BTC/USDT")
    exchange_name = body.get("exchange", config.default_exchange)
    ex = exchanges.get_exchange(exchange_name)
    if not ex:
        return JSONResponse(content={"error": f"exchange {exchange_name} not connected"})
    try:
        positions = ex.fetch_positions([symbol])
        for p in positions:
            if float(p.get("contracts", 0)) > 0:
                if p["side"] == "long":
                    result = exchanges.close_long(symbol, exchange_name=exchange_name)
                else:
                    result = exchanges.close_short(symbol, exchange_name=exchange_name)
                return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(content={"error": str(e)})
    return JSONResponse(content={"status": "no_position", "symbol": symbol})


@app.post("/halt")
async def emergency_halt(request: Request):
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        body = {}
    exchange_name = body.get("exchange", config.default_exchange)
    result = processor._execute_halt(exchange_name)
    return JSONResponse(content=result)


# ── Run ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host=config.webhook_host,
        port=config.webhook_port,
        reload=config.dry_run,
    )
