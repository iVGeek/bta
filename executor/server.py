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
from fastapi.responses import JSONResponse, HTMLResponse
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
@app.get("/", response_class=HTMLResponse)
async def landing():
    """Human-friendly landing page that live-polls the executor /status + /trades."""
    return HTMLResponse(_LANDING_HTML)


# ── Status API ───────────────────────────────────────────────────────────
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


# ── Landing page (browser-friendly fork of /status + /trades) ──────────────
_LANDING_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>iVGeek Executor</title>
<style>
  :root{--bg:#080d1a;--panel:#0f1730;--line:#1e2d50;--txt:#a3b8e0;--b:#e8f0ff;
        --green:#22e87a;--red:#ff4d5a;--amber:#fbbf24;--cyan:#22d3a7;--muted:#52678f;}
  *{box-sizing:border-box}
  body{background:var(--bg);color:var(--txt);font-family:'JetBrains Mono',Consolas,monospace;
       margin:0;padding:24px;font-size:13px}
  h1{color:var(--b);font-size:18px;letter-spacing:1px;margin:0 0 4px}
  .sub{color:var(--muted);margin-bottom:18px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:22px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px}
  .card .l{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
  .card .v{font-size:20px;color:var(--b);font-weight:700;margin-top:6px}
  .card .v.green{color:var(--green)}.card .v.red{color:var(--red)}.card .v.amber{color:var(--amber)}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;margin-bottom:16px;overflow:hidden}
  .panel-h{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;padding:10px 14px;border-bottom:1px solid var(--line)}
  table{width:100%;border-collapse:collapse}
  th,td{text-align:left;padding:7px 14px;border-bottom:1px solid #14203d;font-size:12px}
  th{color:var(--muted);font-weight:600}
  td.sym{color:var(--b);font-weight:700}
  .ok{color:var(--green)}.bad{color:var(--red)}
  .badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700}
  .badge.on{background:rgba(34,232,122,.15);color:var(--green)}
  .badge.off{background:rgba(255,77,90,.15);color:var(--red)}
  a{color:var(--cyan);text-decoration:none}
  .endpoint{font-size:11px;color:var(--muted);margin-top:18px;line-height:1.8}
  .endpoint code{color:var(--cyan)}
</style>
</head>
<body>
  <h1>iVGeek Trading Executor</h1>
  <div class="sub" id="sub">Loading…</div>

  <div class="cards">
    <div class="card"><div class="l">Mode</div><div class="v" id="mode">–</div></div>
    <div class="card"><div class="l">Exchanges</div><div class="v" id="exchanges">–</div></div>
    <div class="card"><div class="l">Total Trades</div><div class="v" id="total">–</div></div>
    <div class="card"><div class="l">Today's Trades</div><div class="v" id="today">–</div></div>
    <div class="card"><div class="l">Today's P&amp;L</div><div class="v" id="pnl">–</div></div>
  </div>

  <div class="panel">
    <div class="panel-h">Recent Trades</div>
    <table>
      <thead><tr><th>Time</th><th>Signal</th><th>Symbol</th><th>Result</th><th>Amount</th><th>Details</th></tr></thead>
      <tbody id="rows"><tr><td colspan="6" style="color:var(--muted)">No trades yet.</td></tr></tbody>
    </table>
  </div>

  <div class="endpoint">
    Webhook URL for TradingView: <code>/webhook</code> (POST) &nbsp;·&nbsp;
    Example: <code>http://YOUR_IP:8080/webhook</code><br>
    API: <code>/status</code> · <code>/trades</code> · <code>/positions</code> · <code>/balance</code> · <code>/halt</code>
  </div>

<script>
const $ = id => document.getElementById(id);
const PIN = sym => {
  const ok = sym && (sym.startsWith('BTC') || sym.startsWith('ETH') || sym.startsWith('SOL'));
  return ok ? '<span class="ok">PIN</span>' : '<span class="muted">spot</span>';
};
function fmtTime(ts){
  if(!ts) return '–';
  const d = new Date(ts);
  if(isNaN(d)) return String(ts);
  return d.toLocaleString('en-US',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
}
async function tick(){
  try{
    const st = await (await fetch('/status')).json();
    const dry = st.dry_run;
    $('mode').textContent = dry ? 'DRY RUN' : 'LIVE';
    $('mode').className = 'v ' + (dry ? 'amber' : 'green');
    $('mode').innerHTML += dry ? ' <span class="badge on">safe</span>' : ' <span class="badge off">real</span>';
    $('exchanges').textContent = (st.exchanges||[]).join(', ') || '–';
    $('total').textContent = st.total_trades ?? '–';
    $('today').textContent = st.daily_trades ?? '–';
    const p = st.daily_pnl ?? 0;
    $('pnl').textContent = (p>0?'+':'') + Number(p).toFixed(2);
    $('pnl').className = 'v ' + (p>0?'green':p<0?'red':'');
    const sub = 'Polling /status every 2s · ' + (dry ? 'No API keys required — orders simulated' : 'Executing on real exchange');
    if($('sub').textContent.indexOf('Polling')===-1) $('sub').textContent = sub;
  }catch(e){ $('sub').textContent = 'Cannot reach executor API: ' + e.message; }

  try{
    const tr = await (await fetch('/trades?limit=12')).json();
    const tb = $('rows'); tb.innerHTML = '';
    if(!tr || !tr.length){ tb.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">No trades yet.</td></tr>'; return; }
    for(const t of tr){
      const rec = document.createElement('tr');
      const sigMap = (t.signal||{});
      const resMap = (t.result||{});
      const sig = (sigMap.signal||'').toUpperCase();
      const symbol = resMap.symbol || sigMap.symbol || '–';
      const status = resMap.status||resMap.error||'';
      const good = String(status).indexOf('rejected')===-1 && String(status).indexOf('error')===-1 && status!=='';
      rec.innerHTML =
        '<td>'+fmtTime(t.time)+'</td>'+
        '<td class="sym">'+sig+'</td>'+
        '<td>'+PIN(symbol)+' '+symbol+'</td>'+
        '<td class="'+(good?'ok':'bad')+'">'+status+'</td>'+
        '<td>'+(resMap.amount??'–')+'</td>'+
        '<td>'+((resMap.dry_run?'dry · ':'')+(resMap.reason||resMap.error||'–'))+'</td>';
      tb.appendChild(rec);
    }
    $('rows').innerHTML = tb.innerHTML;
  }catch(e){ /* table is decorative, ignore */ }
}
setInterval(tick, 2000);
tick();
</script>
</body>
</html>
"""


# ── Run ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    import uvicorn
    # Reload is off by default for stable background service runs. Enable via
    # EXECUTOR_RELOAD=1 (e.g. dev) — uvicorn's reloader can hang when spawned
    # as a detached/background process.
    reload_on = os.getenv("EXECUTOR_RELOAD", "0") == "1"
    uvicorn.run(
        "server:app",
        host=config.webhook_host,
        port=config.webhook_port,
        reload=reload_on,
    )
