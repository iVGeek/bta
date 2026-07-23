// ═══════════════════════════════════════════════════════════════════════════════
// Bot Trading AI Terminal v2.0 — Frontend
// ═══════════════════════════════════════════════════════════════════════════════

let chart, candleSeries, volSeries, ema9Line, ema21Line, ema200Line;
let rsiChart, rsiSeries, rsiUpper, rsiLower;
let macdChart, macdSeries, macdSigSeries, macdHistSeries;
let ws, curSym = "BTC/USDT", curTF = "15";
let tickers = {}, indCache = {}, priceHistory = {};
let lastCandleTime = 0;
let candleData = [];
let assetFilter = "all";  // "all", "crypto", "stock"
let trialActive = false;  // stored candle array for click lookup

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initCharts(); initTabs(); initTFs(); connectWS();
  loadChart(); loadTickers(); loadOrderBook(); loadAIAnalysis(); loadNews(); loadHints();
  loadTrialStatus();
  setInterval(loadOrderBook, 5000);
  setInterval(loadAIAnalysis, 15000);
  setInterval(loadNews, 120000);
  setInterval(loadHints, 10000);
});

// ── Charts ───────────────────────────────────────────────────────────────────
const cfg = (h) => ({
  width: 0, height: h,
  layout: { background: { type: "solid", color: "#080d1a" }, textColor: "#a3b8e0", fontSize: 10, fontFamily: "'JetBrains Mono',monospace" },
  grid: { vertLines: { color: "rgba(30,45,80,.2)" }, horzLines: { color: "rgba(30,45,80,.2)" } },
  crosshair: { mode: 0, vertLine: { color: "rgba(34,211,167,.3)", width: 1, style: 2, labelBackgroundColor: "#141e36" }, horzLine: { color: "rgba(34,211,167,.3)", width: 1, style: 2, labelBackgroundColor: "#141e36" } },
  rightPriceScale: { borderColor: "#1e2d50", scaleMargins: { top: 0.05, bottom: 0.05 } },
  timeScale: { borderColor: "#1e2d50", timeVisible: true, secondsVisible: false },
});

function initCharts() {
  const mc = document.getElementById("cMain");
  chart = LightweightCharts.createChart(mc, cfg(mc.clientHeight));
  candleSeries = chart.addCandlestickSeries({
    upColor: "#22e87a", downColor: "#ff4d5a",
    borderUpColor: "#22e87a", borderDownColor: "#ff4d5a",
    wickUpColor: "#22e87a", wickDownColor: "#ff4d5a"
  });
  volSeries = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "v" });
  chart.priceScale("v").applyOptions({ scaleMargins: { top: 0.88, bottom: 0 } });
  ema9Line = chart.addLineSeries({ color: "#fbbf24", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  ema21Line = chart.addLineSeries({ color: "#4da6ff", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  ema200Line = chart.addLineSeries({ color: "#a78bfa", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });

  const rc = document.getElementById("cRsi");
  rsiChart = LightweightCharts.createChart(rc, cfg(rc.clientHeight));
  rsiSeries = rsiChart.addLineSeries({ color: "#22d3a7", lineWidth: 1.5, priceLineVisible: false });
  rsiUpper = rsiChart.addLineSeries({ color: "rgba(255,77,90,.4)", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
  rsiLower = rsiChart.addLineSeries({ color: "rgba(34,232,122,.4)", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
  rsiChart.priceScale("right").applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } });

  const mdc = document.getElementById("cMacd");
  macdChart = LightweightCharts.createChart(mdc, cfg(mdc.clientHeight));
  macdHistSeries = macdChart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
  macdSeries = macdChart.addLineSeries({ color: "#4da6ff", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  macdSigSeries = macdChart.addLineSeries({ color: "#fbbf24", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  macdChart.priceScale("right").applyOptions({ scaleMargins: { top: 0.2, bottom: 0.2 } });

  new ResizeObserver(() => {
    chart.applyOptions({ width: mc.clientWidth, height: mc.clientHeight });
    rsiChart.applyOptions({ width: rc.clientWidth, height: rc.clientHeight });
    macdChart.applyOptions({ width: mdc.clientWidth, height: mdc.clientHeight });
  }).observe(mc.parentElement);

  // Crosshair → candle info popup
  chart.subscribeCrosshairMove((param) => {
    const el = document.getElementById("candleInfo");
    if (!param || !param.time || !param.seriesData) { el.style.display = "none"; return; }
    const d = param.seriesData.get(candleSeries);
    if (!d) { el.style.display = "none"; return; }
    el.style.display = "block";
    const dt = new Date(param.time * 1000);
    document.getElementById("ciTime").textContent = dt.toLocaleString("en-US", {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"});
    document.getElementById("ciOpen").textContent = fmtP(d.open, curSym);
    document.getElementById("ciHigh").textContent = fmtP(d.high, curSym);
    document.getElementById("ciLow").textContent = fmtP(d.low, curSym);
    document.getElementById("ciClose").textContent = fmtP(d.close, curSym);
    const vol = param.seriesData.get(volSeries);
    document.getElementById("ciVol").textContent = vol ? fmtVol(vol.value) : "-";
    const chg = d.open > 0 ? ((d.close - d.open) / d.open * 100).toFixed(2) : "0";
    const chgEl = document.getElementById("ciChg");
    chgEl.textContent = (chg >= 0 ? "+" : "") + chg + "%";
    chgEl.style.color = chg >= 0 ? "var(--green)" : "var(--red)";
  });
}

async function loadChart() {
  try {
    const r = await fetch(`/api/chart/${curSym.replace("/", "-")}?timeframe=${curTF}`);
    const d = await r.json();
    if (!d.candles?.length) return;
    candleData = d.candles;
    candleSeries.setData(d.candles);
    lastCandleTime = d.candles[d.candles.length - 1].time;
    volSeries.setData(d.candles.map(c => ({
      time: c.time, value: c.volume,
      color: c.close >= c.open ? "rgba(34,232,122,.12)" : "rgba(255,77,90,.12)"
    })));
    chart.timeScale().fitContent();
    const ind = d.indicators;
    if (!ind) return;
    indCache = ind;
    if (ind.ema9_s) ema9Line.setData(ind.ema9_s);
    if (ind.ema21_s) ema21Line.setData(ind.ema21_s);
    if (ind.ema200_s) ema200Line.setData(ind.ema200_s);
    if (ind.rsi_s) {
      rsiSeries.setData(ind.rsi_s);
      rsiUpper.setData(ind.rsi_s.map(p => ({ time: p.time, value: 70 })));
      rsiLower.setData(ind.rsi_s.map(p => ({ time: p.time, value: 30 })));
      rsiChart.timeScale().fitContent();
    }
    if (ind.macd_m) {
      macdSeries.setData(ind.macd_m);
      macdSigSeries.setData(ind.macd_s_s);
      macdHistSeries.setData(ind.macd_h_s);
      macdChart.timeScale().fitContent();
    }
    updateIndicators(ind);
    updateTickerHeader();
  } catch (e) { console.warn("Chart:", e.message); }
}

function updateTickerHeader() {
  document.getElementById("cSym").textContent = curSym;
  const t = tickers[curSym];
  if (t) {
    document.getElementById("cPrice").textContent = fmtP(t.price, curSym);
    const ce = document.getElementById("cChg");
    ce.textContent = `${t.change_24h >= 0 ? "+" : ""}${t.change_24h.toFixed(2)}%`;
    ce.className = `sym-chg ${t.change_24h >= 0 ? "p" : "n"}`;
    document.getElementById("cVol").textContent = fmtVol(t.volume_24h);
    document.getElementById("cHi").textContent = fmtP(t.high_24h, curSym);
    document.getElementById("cLo").textContent = fmtP(t.low_24h, curSym);
  }
}

function updateIndicators(ind) {
  setI("xEma9", ind.ema9); setI("xEma21", ind.ema21); setI("xEma200", ind.ema200);
  setIC("xRsi", ind.rsi, ind.rsi > 70 ? "bear" : ind.rsi < 30 ? "bull" : "neut");
  setIC("xMacd", (ind.macd?.histogram > 0 ? "+" : "") + ind.macd?.histogram, ind.macd?.histogram > 0 ? "bull" : "bear");
  document.getElementById("xBB").textContent = `${fmtP(ind.bb?.lower, curSym)} - ${fmtP(ind.bb?.upper, curSym)}`;
  setIC("xStoch", `K:${ind.stoch_rsi?.k} D:${ind.stoch_rsi?.d}`, ind.stoch_rsi?.k > 80 ? "bear" : ind.stoch_rsi?.k < 20 ? "bull" : "neut");
  document.getElementById("xST").textContent = ind.supertrend ? fmtP(ind.supertrend, curSym) : "-";
  setIC("xTrend", ind.trend?.toUpperCase(), ind.trend === "bullish" ? "bull" : ind.trend === "bearish" ? "bear" : "neut");
  setIC("xStr", ind.strength + "%", ind.strength > 60 ? "bull" : ind.strength < 40 ? "bear" : "neut");
}

function setI(id, val) { document.getElementById(id).textContent = fmtP(val, curSym); }
function setIC(id, val, cls) { const e = document.getElementById(id); e.textContent = val; e.className = `v ${cls}`; }

function initTFs() {
  document.querySelectorAll(".tf").forEach(b => b.addEventListener("click", () => {
    document.querySelectorAll(".tf").forEach(x => x.classList.remove("on"));
    b.classList.add("on"); curTF = b.dataset.tf; loadChart();
  }));
}

function initTabs() {
  document.querySelectorAll(".rtab").forEach(t => t.addEventListener("click", () => {
    document.querySelectorAll(".rtab").forEach(x => x.classList.remove("on"));
    document.querySelectorAll(".rp").forEach(x => x.classList.remove("on"));
    t.classList.add("on");
    document.getElementById("rp-" + t.dataset.rp).classList.add("on");
  }));
}

// ── Sparkline Renderer ───────────────────────────────────────────────────────
function drawSparkline(canvas, data, color, w, h) {
  if (!canvas || !data?.length) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr; canvas.height = h * dpr;
  canvas.style.width = w + "px"; canvas.style.height = h + "px";
  ctx.scale(dpr, dpr);
  const mn = Math.min(...data), mx = Math.max(...data);
  const range = mx - mn || 1;
  const step = w / (data.length - 1 || 1);
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.2;
  ctx.lineJoin = "round";
  data.forEach((v, i) => {
    const x = i * step;
    const y = h - ((v - mn) / range) * (h - 2) - 1;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
  // gradient fill
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  let fillColor = color;
  if (color.startsWith("#")) {
    const r = parseInt(color.slice(1, 3), 16), g = parseInt(color.slice(3, 5), 16), b = parseInt(color.slice(5, 7), 16);
    fillColor = `rgba(${r},${g},${b},.15)`;
  } else {
    fillColor = color.replace(")", ",.15)").replace("rgb", "rgba");
  }
  grad.addColorStop(0, fillColor);
  grad.addColorStop(1, "transparent");
  ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
  ctx.fillStyle = grad; ctx.fill();
}

// ── WebSocket ────────────────────────────────────────────────────────────────
function connectWS() {
  const p = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${p}://${location.host}/ws`);
  ws.onopen = () => { document.getElementById("cDot").className = "conn-dot"; document.getElementById("cText").textContent = "LIVE"; };
  ws.onclose = () => { document.getElementById("cDot").className = "conn-dot off"; document.getElementById("cText").textContent = "RECONNECTING..."; setTimeout(connectWS, 2000); };
  ws.onmessage = (e) => { const d = JSON.parse(e.data); if (d.type === "update") onWS(d); };
}

function onWS(d) {
  if (d.tickers) {
    for (const [sym, t] of Object.entries(d.tickers)) {
      if (!priceHistory[sym]) priceHistory[sym] = [];
      if (tickers[sym]) {
        tickers[sym].price = t.price;
        tickers[sym].change_24h = t.change_24h;
      }
      priceHistory[sym].push(t.price);
      if (priceHistory[sym].length > 20) priceHistory[sym].shift();
    }
    renderWL(); renderHM(); renderTape(); updateTickerHeader();
  }
  if (d.candle && d.candle.time) {
    if (d.candle.time >= lastCandleTime) {
      candleSeries.update(d.candle);
      volSeries.update({ time: d.candle.time, value: d.candle.volume, color: d.candle.close >= d.candle.open ? "rgba(34,232,122,.12)" : "rgba(255,77,90,.12)" });
      lastCandleTime = d.candle.time;
    }
    document.getElementById("cPrice").textContent = fmtP(d.candle.close, curSym);
    if (d.candle.atr !== undefined) document.getElementById("cAtr").textContent = fmtP(d.candle.atr, curSym);
    if (d.candle.vwap !== undefined) document.getElementById("cVwap").textContent = fmtP(d.candle.vwap, curSym);
  }
  const m = d.metrics || {};
  document.getElementById("hBal").textContent = "$" + fmtN(d.balance);
  document.getElementById("hEq").textContent = "$" + fmtN(d.equity);
  setHV("hPnl", m.total_pnl, "$" + fmtN(m.total_pnl));
  document.getElementById("hWR").textContent = m.win_rate + "%";
  document.getElementById("hPF").textContent = m.profit_factor;
  setHV("hDD", m.max_drawdown, m.max_drawdown + "%");
  document.getElementById("btnRun").textContent = d.running ? "STOP" : "START";
  document.getElementById("btnRun").className = `btn ${d.running ? "stop" : "start"}`;
  document.getElementById("btnPaper").className = `btn paper ${d.paper_mode ? "on" : ""}`;
  document.getElementById("btnAI").className = `btn ${d.ai_enabled ? "ai-on" : "ai-off"}`;
  document.getElementById("btnAuto").className = `btn auto ${d.auto_trade ? "on" : ""}`;
  document.getElementById("mRisk").textContent = d.risk_per_trade + "%";
  document.getElementById("mSL").textContent = d.sl_atr_mult + " ATR";
  document.getElementById("mTP").textContent = d.tp_atr_mult + " ATR";
  document.getElementById("mScore").textContent = d.score_threshold;
  document.getElementById("mPos").textContent = `${d.positions_count}/${d.max_positions}`;
  document.getElementById("mCW").textContent = m.consecutive_wins;
  document.getElementById("mCL").textContent = m.consecutive_losses;
  document.getElementById("mExp").textContent = "$" + fmtN(m.expectancy);
  const rp = Math.min((d.positions_count / d.max_positions) * 100, 100);
  document.getElementById("gArc").style.strokeDashoffset = 188 - (188 * rp / 100);
  document.getElementById("gArc").style.stroke = rp > 70 ? "var(--red)" : rp > 40 ? "var(--yellow)" : "var(--green)";
  document.getElementById("gVal").textContent = Math.round(rp) + "%";
  document.getElementById("aiBadge").textContent = d.ai_enabled ? "ACTIVE" : "OFF";
  document.getElementById("aiBadge").className = `ai-badge ${d.ai_enabled ? "on" : "off"}`;
  renderPositions(d.positions || []);
  renderTrades(d.trades || []);
  renderSignals(d.signals || []);
  updateAIPanel(d);
  if (d.trial) {
    trialActive = d.trial.active;
    const tpEl = document.getElementById("trialPositions");
    if (tpEl && d.trial.positions && d.trial.positions.length) {
      tpEl.innerHTML = d.trial.positions.map(p => {
        const pnlCls = p.pnl >= 0 ? "g" : "r";
        return `<div class="pos">
          <div class="pos-side ${p.side}">${p.side.toUpperCase()}</div>
          <div style="flex:1"><b>${p.symbol}</b> @ ${fmtP(p.entry, p.symbol)}</div>
          <div class="pos-pnl ${pnlCls}">${p.pnl >= 0 ? "+" : ""}$${fmtN(p.pnl)}</div>
          <button onclick="closeTrialPos(${p.id})" style="background:transparent;border:1px solid var(--red);color:var(--red);border-radius:4px;padding:2px 8px;cursor:pointer;font-size:11px">X</button>
        </div>`;
      }).join("");
    } else if (tpEl) {
      tpEl.innerHTML = '<div class="empty" style="padding:12px;color:var(--text3)">No trial positions</div>';
    }
    if (d.trial.closed && d.trial.closed.length) {
      for (const t of d.trial.closed) {
        showNotif(`Trial closed ${t.symbol}: $${t.pnl}`, t.pnl >= 0 ? "green" : "red");
      }
    }
  }
  if (d.market) {
    document.getElementById("aiRec").textContent = d.market.recommendation || "Analyzing...";
    renderOpportunities(d.market.top_opportunities || []);
  }
}

function setHV(id, val, text) {
  const e = document.getElementById(id);
  e.textContent = text;
  e.className = `v ${val >= 0 ? "g" : "r"}`;
}

function updateAIPanel(d) {
  const sigs = d.ai_decisions || d.signals || [];
  const total = sigs.length;
  const approved = sigs.filter(s => s.ai_approved !== false).length;
  const avgConf = total ? Math.round(sigs.reduce((a, s) => a + (s.confidence || s.ai_score || 0), 0) / total) : 0;
  document.getElementById("aiDec").textContent = total;
  document.getElementById("aiApp").textContent = total ? Math.round(approved / total * 100) + "%" : "0%";
  document.getElementById("aiConf").textContent = avgConf + "%";
  if (sigs.length) {
    const last = sigs[sigs.length - 1];
    document.getElementById("aiLast").textContent = `${last.side?.toUpperCase()} ${last.symbol || ""}`;
  }
}

function renderOpportunities(opps) {
  const el = document.getElementById("oppList");
  if (!opps.length) { el.innerHTML = '<div class="empty">No opportunities found</div>'; return; }
  el.innerHTML = opps.map(o => `
    <div class="opp ${o.type.toLowerCase()}">
      <div class="opp-head">
        <span class="opp-sym">${o.symbol}</span>
        <span class="opp-side ${o.type.toLowerCase()}">${o.type}</span>
      </div>
      <div class="opp-reason">${o.reason}</div>
      <div class="opp-conf" style="color:${o.confidence > 70 ? 'var(--green)' : 'var(--yellow)'}">${o.confidence}%</div>
    </div>`).join("");
}

// ── Render ───────────────────────────────────────────────────────────────────
function renderPositions(positions) {
  const el = document.getElementById("posList"), emp = document.getElementById("emptyPos");
  if (!positions.length) { emp.style.display = "flex"; el.innerHTML = ""; return; }
  emp.style.display = "none";
  el.innerHTML = positions.map(p => `
    <div class="pos ${p.side}">
      <div class="pos-top"><span class="pos-sym">${p.symbol}</span>
        <div style="display:flex;gap:5px;align-items:center">
          <span class="pos-side ${p.side}">${p.side?.toUpperCase()}</span>
          <button onclick="closePos(${p.id})" style="padding:2px 7px;border:1px solid var(--red);border-radius:var(--radius-sm);background:transparent;color:var(--red);cursor:pointer;font-size:8px;font-weight:800;transition:all .15s" onmouseover="this.style.background='var(--red)';this.style.color='#fff'" onmouseout="this.style.background='transparent';this.style.color='var(--red)'">X</button>
        </div>
      </div>
      <div class="pos-grid">
        <span class="l">Entry</span><span class="v">${fmtP(p.entry, p.symbol)}</span>
        <span class="l">Current</span><span class="v">${fmtP(p.current, p.symbol)}</span>
        <span class="l">Size</span><span class="v">${p.amount?.toFixed(4)}</span>
        <span class="l">Stop Loss</span><span class="v" style="color:var(--red)">${fmtP(p.sl, p.symbol)}</span>
        <span class="l">Take Profit</span><span class="v" style="color:var(--green)">${fmtP(p.tp, p.symbol)}</span>
        <span class="l">R:R</span><span class="v">${p.rr}</span>
      </div>
      <div class="pos-pnl ${(p.pnl||0)>=0?'pos':'neg'}">${fmtM(p.pnl)} (${p.pnl_pct}%)</div>
    </div>`).join("");
}

async function closePos(id) { try { await fetch(`/api/close/${id}`, { method: "POST" }); showNotif("Position closed", "green"); } catch (e) { showNotif("Close failed: " + e.message, "red"); } }

function renderTrades(trades) {
  const el = document.getElementById("trList");
  if (!trades.length) { el.innerHTML = '<div class="empty">No trade history</div>'; return; }
  el.innerHTML = [...trades].reverse().map(t => `
    <div class="tr">
      <span class="tr-t">${fmtTime(t.time)}</span>
      <span><span class="tr-side ${t.side}">${t.side?.toUpperCase()}</span> <span class="tr-sym">${t.symbol}</span></span>
      <span style="font-family:'JetBrains Mono',monospace;font-weight:700;font-size:10px">${fmtP(t.price, t.symbol)}</span>
      <span class="tr-pnl ${(t.pnl||0)>=0?'pos':'neg'}">${fmtM(t.pnl)}</span>
    </div>`).join("");
}

function renderSignals(signals) {
  const el = document.getElementById("sigList");
  if (!signals.length) { el.innerHTML = '<div class="empty">Waiting for signals...</div>'; return; }
  el.innerHTML = [...signals].reverse().slice(0, 30).map(s => {
    const conf = s.confidence || s.ai_score || 0;
    const cls = conf >= 70 ? "high" : conf >= 40 ? "med" : "low";
    const reasons = (s.ai_reasons || []).slice(0, 3);
    return `
    <div class="sig">
      <div class="sig-top">
        <span class="sig-type ${s.side}">${s.side?.toUpperCase()} ${s.symbol}</span>
        <span class="sig-badge ${cls}">${conf}% AI</span>
      </div>
      <div class="sig-detail">${fmtP(s.price, s.symbol)} | ${s.type || "auto"} | ${s.ai_approved !== false ? "APPROVED" : "REJECTED"}</div>
      ${reasons.length ? `<div class="sig-reasons">${reasons.map(r => `<span>${r}</span>`).join("")}</div>` : ""}
    </div>`;
  }).join("");
}

// ── Tickers ──────────────────────────────────────────────────────────────────
async function loadTickers() {
  try {
    const r = await fetch("/api/tickers");
    tickers = await r.json();
    for (const [sym, t] of Object.entries(tickers)) {
      if (!priceHistory[sym]) priceHistory[sym] = [];
      priceHistory[sym].push(t.price);
    }
    renderWL(); renderHM(); renderTape(); updateTickerHeader();
  } catch (e) { console.warn("Tickers:", e.message); }
}

function renderWL() {
  const wl = document.getElementById("wl");
  let syms = Object.keys(tickers);
  if (assetFilter === "crypto") syms = syms.filter(s => s.includes("/"));
  else if (assetFilter === "stock") syms = syms.filter(s => !s.includes("/"));
  document.getElementById("wlc").textContent = syms.length;
  wl.innerHTML = syms.map(s => {
    const t = tickers[s];
    const sparkId = "sp_" + s.replace("/", "_");
    const hist = priceHistory[s] || [];
    const chg = (t.change_24h||0);
    const isStock = !s.includes("/");
    const badge = isStock ? '<span class="tkr-badge stock">STK</span>' : '<span class="tkr-badge crypto">CRC</span>';
    return `<div class="tkr ${s === curSym ? "active" : ""}" onclick="selectSym('${s}')">
      <div><div class="tkr-s">${s.split("/")[0]}${badge}</div><div class="tkr-sub">${s}</div></div>
      <canvas class="tkr-spark" id="${sparkId}"></canvas>
      <div><div class="tkr-p">${fmtP(t.price, s)}</div>
      <div class="tkr-c ${chg>=0?'p':'n'}">${chg>=0?"+":""}${chg.toFixed(2)}%</div></div>
    </div>`;
  }).join("");
  requestAnimationFrame(() => {
    syms.forEach(s => {
      const c = document.getElementById("sp_" + s.replace("/", "_"));
      if (c && priceHistory[s]?.length > 1) {
        const chg = (tickers[s]?.change_24h || 0);
        drawSparkline(c, priceHistory[s], chg >= 0 ? "#22e87a" : "#ff4d5a", 56, 22);
      }
    });
  });
}

function renderTape() {
  const track = document.getElementById("tapeTrack");
  let syms = Object.keys(tickers);
  if (assetFilter === "crypto") syms = syms.filter(s => s.includes("/"));
  else if (assetFilter === "stock") syms = syms.filter(s => !s.includes("/"));
  if (!syms.length) return;
  const items = syms.map(s => {
    const t = tickers[s];
    const chg = (t.change_24h||0);
    return `<div class="tape-item">
      <span class="tape-sym">${s.split("/")[0]}</span>
      <span class="tape-price">${fmtP(t.price, s)}</span>
      <span class="tape-chg ${chg>=0?'p':'n'}">${chg>=0?"+":""}${chg.toFixed(2)}%</span>
    </div>`;
  }).join("");
  track.innerHTML = items + items; // duplicate for infinite scroll
}

function renderHM() {
  const el = document.getElementById("hm");
  let items = Object.values(tickers);
  if (assetFilter === "crypto") items = items.filter(t => t.asset !== "stock");
  else if (assetFilter === "stock") items = items.filter(t => t.asset === "stock");
  const sorted = items.sort((a, b) => Math.abs(b.change_24h||0) - Math.abs(a.change_24h||0));
  el.innerHTML = sorted.slice(0, 9).map(t => {
    const c = t.change_24h || 0;
    const intensity = Math.min(Math.abs(c) * 8, 100);
    const bg = c >= 0
      ? `rgba(34,232,122,${(intensity/100*.18+.04).toFixed(2)})`
      : `rgba(255,77,90,${(intensity/100*.18+.04).toFixed(2)})`;
    const border = c >= 0
      ? `rgba(34,232,122,${(intensity/100*.25+.05).toFixed(2)})`
      : `rgba(255,77,90,${(intensity/100*.25+.05).toFixed(2)})`;
    return `<div class="hm" style="background:${bg};border-color:${border}" onclick="selectSym('${t.symbol}')">
      <div class="s">${t.symbol.split("/")[0]}</div>
      <div class="p" style="color:${c>=0?'var(--green)':'var(--red)'}">${c>=0?"+":""}${c.toFixed(1)}%</div>
      <div class="vol">${fmtVol(t.volume_24h)}</div>
    </div>`;
  }).join("");
}

function selectSym(s) { curSym = s; loadChart(); loadOrderBook(); }

// ── Order Book ───────────────────────────────────────────────────────────────
async function loadOrderBook() {
  try {
    const ob = await (await fetch(`/api/orderbook/${curSym.replace("/", "-")}`)).json();
    renderOB(ob);
  } catch (e) { console.warn("OrderBook:", e.message); }
}

function renderOB(ob) {
  const el = document.getElementById("obData");
  if (!ob.bids?.length && !ob.asks?.length) { el.innerHTML = '<div class="empty">No data</div>'; return; }
  const mx = Math.max(...(ob.asks||[]).map(a=>a[1]), ...(ob.bids||[]).map(b=>b[1]), 0.001);
  const asks = (ob.asks||[]).slice(0, 12).reverse();
  const bids = (ob.bids||[]).slice(0, 12);
  const spread = asks.length && bids.length ? asks[0][0] - bids[0][0] : 0;
  el.innerHTML = `<div class="ob">${asks.map(a => obR(a, mx, "ask")).join("")}
  <div class="ob-spread">Spread ${fmtP(spread, curSym)} (${(spread/(bids[0]?.[0]||1)*100).toFixed(4)}%)</div>
  ${bids.map(b => obR(b, mx, "bid")).join("")}</div>`;
}

function obR([price, qty], mx, side) {
  return `<div class="ob-row ${side}"><div class="bar" style="width:${(qty/mx*100).toFixed(0)}%"></div>
  <span class="p" style="color:${side==="ask"?"var(--red)":"var(--green)"}">${fmtP(price, curSym)}</span>
  <span class="q">${qty >= 1 ? qty.toFixed(3) : qty.toFixed(6)}</span></div>`;
}

// ── AI ───────────────────────────────────────────────────────────────────────
async function loadAIAnalysis() {
  try {
    const data = await (await fetch("/api/ai/analysis")).json();
    document.getElementById("aiRec").textContent = data.recommendation || "Analyzing...";
    renderOpportunities(data.top_opportunities || []);
  } catch (e) { console.warn("AI Analysis:", e.message); }
}

// ── Trade ────────────────────────────────────────────────────────────────────
async function executeTrade(side) {
  const price = tickers[curSym]?.price || 0;
  const r = await fetch("/api/trade", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: curSym, side: side === "long" ? "buy" : "sell", price }),
  });
  const result = await r.json();
  const ai = result.ai || {};
  const pos = result.position;
  const el = document.getElementById("manualAI");
  el.innerHTML = `
    <div class="ai-glass" style="margin-bottom:6px">
      <div class="ai-hdr"><span class="ai-title">AI VERDICT</span>
        <span class="ai-badge ${result.status === 'position_opened' ? 'on' : 'off'}">${result.status === 'position_opened' ? 'OPENED' : result.status === 'rejected_by_ai' ? 'REJECTED' : 'ERROR'}</span>
      </div>
      <div class="ai-grid">
        <div class="ai-cell"><div class="l">Score</div><div class="v" style="color:${ai.score > 60 ? 'var(--green)' : 'var(--red)'}">${ai.score || 0}%</div></div>
        <div class="ai-cell"><div class="l">Side</div><div class="v">${side.toUpperCase()}</div></div>
      </div>
    </div>
    <div class="sig-reasons" style="margin-top:4px">${(ai.reasons || []).map(r => `<span>${r}</span>`).join("")}</div>
    ${pos ? `<div style="margin-top:8px;padding:8px;background:var(--bg4);border-radius:var(--radius);font-size:10px">
      <div style="display:flex;justify-content:space-between;margin-bottom:2px"><span style="color:var(--text3);font-weight:600">Entry</span><span style="font-weight:700">${fmtP(pos.entry, pos.symbol)}</span></div>
      <div style="display:flex;justify-content:space-between;margin-bottom:2px"><span style="color:var(--text3);font-weight:600">Stop Loss</span><span style="color:var(--red);font-weight:700">${fmtP(pos.sl, pos.symbol)}</span></div>
      <div style="display:flex;justify-content:space-between;margin-bottom:2px"><span style="color:var(--text3);font-weight:600">Take Profit</span><span style="color:var(--green);font-weight:700">${fmtP(pos.tp, pos.symbol)}</span></div>
      <div style="display:flex;justify-content:space-between"><span style="color:var(--text3);font-weight:600">Size</span><span style="font-weight:700">${pos.amount?.toFixed(4)}</span></div>
    </div>` : ""}
    ${result.error ? `<div style="color:var(--red);font-size:10px;margin-top:4px;font-weight:600">${result.error}</div>` : ""}`;
}

// ── Controls ─────────────────────────────────────────────────────────────────
async function api(url, method = "POST") { try { await fetch(url, { method }); } catch (e) { console.warn("API:", e.message); } }
function openModal() { document.getElementById("modalBg").classList.add("show"); }
function closeModal() { document.getElementById("modalBg").classList.remove("show"); }

function showNotif(msg, color = "blue") {
  const n = document.createElement("div");
  n.style.cssText = `position:fixed;top:20px;right:20px;z-index:99999;padding:12px 20px;border-radius:8px;color:#fff;font-size:13px;font-family:Inter,sans-serif;box-shadow:0 4px 20px rgba(0,0,0,.4);max-width:400px;opacity:1;transition:opacity .3s;`;
  const colors = { green: "#16a34a", red: "#dc2626", yellow: "#ca8a04", blue: "#2563eb" };
  n.style.background = colors[color] || colors.blue;
  n.textContent = msg;
  document.body.appendChild(n);
  setTimeout(() => { n.style.opacity = "0"; setTimeout(() => n.remove(), 300); }, 3000);
}

async function saveCfg() {
  try {
    await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      risk_per_trade: parseFloat(document.getElementById("sRisk").value),
      max_positions: parseInt(document.getElementById("sMaxPos").value),
      sl_atr_mult: parseFloat(document.getElementById("sSL").value),
      tp_atr_mult: parseFloat(document.getElementById("sTP").value),
      score_threshold: parseInt(document.getElementById("sScore").value),
      timeframe: document.getElementById("sTF").value,
      selected_pairs: document.getElementById("sPairs").value.split(",").map(x => x.trim()),
    })});
    closeModal(); curTF = document.getElementById("sTF").value; loadChart(); loadTickers();
    showNotif("Configuration saved", "green");
  } catch (e) { showNotif("Save failed: " + e.message, "red"); }
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function fmtM(v) { return (v >= 0 ? "" : "-") + "$" + Math.abs(v || 0).toFixed(2); }
function fmtN(v) { return (v || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function fmtP(p, s) { if (p == null) return "-"; if (s?.includes("BTC")) return p.toFixed(1); if (p > 1000) return p.toFixed(2); if (p > 1) return p.toFixed(4); return p.toFixed(6); }
function fmtVol(v) { if (!v) return "0"; if (v >= 1e9) return (v/1e9).toFixed(1) + "B"; if (v >= 1e6) return (v/1e6).toFixed(1) + "M"; if (v >= 1e3) return (v/1e3).toFixed(1) + "K"; return v.toFixed(0); }
function fmtTime(t) { if (!t) return ""; return new Date(t).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
function fmtAgo(ts) {
  if (!ts) return "";
  const s = Math.floor(Date.now() / 1000 - ts);
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}

// ── News ─────────────────────────────────────────────────────────────────────
let newsData = [];

async function loadNews() {
  try {
    const d = await (await fetch("/api/news?limit=30")).json();
    newsData = d.items || [];
    renderNewsSentiment(d.summary || {});
    renderNews(newsData);
  } catch (e) { console.warn("News:", e.message); }
}

function renderNewsSentiment(s) {
  const bull = s.bullish_pct || 50;
  const bear = s.bearish_pct || 50;
  document.getElementById("nsBull").style.width = bull + "%";
  document.getElementById("nsBear").style.width = bear + "%";
  document.getElementById("nsBullPct").textContent = bull + "% Bullish";
  document.getElementById("nsBearPct").textContent = bear + "% Bearish";
  const vd = document.getElementById("nsVerdict");
  if (s.overall === "bullish") {
    vd.textContent = "Bullish — Positive sentiment dominating crypto news";
    vd.style.color = "var(--green)"; vd.style.borderColor = "rgba(34,232,122,.15)"; vd.style.background = "rgba(34,232,122,.04)";
  } else if (s.overall === "bearish") {
    vd.textContent = "Bearish — Negative headlines dominating crypto space";
    vd.style.color = "var(--red)"; vd.style.borderColor = "rgba(255,77,90,.15)"; vd.style.background = "rgba(255,77,90,.04)";
  } else {
    vd.textContent = "Neutral — Mixed signals across crypto news";
    vd.style.color = "var(--blue)"; vd.style.borderColor = "rgba(77,166,255,.12)"; vd.style.background = "rgba(77,166,255,.04)";
  }
}

function renderNews(items) {
  const el = document.getElementById("newsList");
  document.getElementById("newsCnt").textContent = items.length;
  if (!items.length) { el.innerHTML = '<div class="empty">No news available</div>'; return; }
  el.innerHTML = items.map(n => {
    const coins = (n.coins || []).map(c => `<span class="news-coin">${c}</span>`).join("");
    return `
    <div class="news-item ${n.sentiment}" onclick="${n.url ? `window.open('${escH(n.url)}','_blank')` : ''}">
      <div class="news-hdr">
        <div class="news-title">${escH(n.title)}</div>
        <span class="news-sent ${n.sentiment}">${n.sentiment.toUpperCase()}</span>
      </div>
      <div class="news-meta">
        <span class="news-source">${escH(n.source)}</span>
        <span class="news-time">${fmtAgo(n.time)}</span>
        <span class="news-conf ${n.confidence >= 70 ? 'high' : n.confidence >= 50 ? 'med' : 'low'}">${n.confidence}%</span>
        <div class="news-coins">${coins}</div>
      </div>
      ${n.body ? `<div class="news-body">${escH(n.body)}</div>` : ""}
    </div>`;
  }).join("");
}

function escH(s) { const d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }

// ── AI Hints ──────────────────────────────────────────────────────────────────
async function loadHints() {
  try {
    const r = await fetch("/api/hints");
    const d = await r.json();
    renderHints(d.hints);
  } catch (e) { console.warn("Hints:", e.message); }
}

function renderHints(hints) {
  const el = document.getElementById("hintsList");
  if (!hints || !hints.length) { el.innerHTML = '<div class="empty">No high-confidence signals right now. Scanning...</div>'; return; }
  el.innerHTML = hints.map(h => {
    const side = h.side.toLowerCase();
    const reasons = h.reasons.map(r => `<span class="hint-reason">${escH(r)}</span>`).join("");
    const confColor = side === "buy" ? "var(--green)" : "var(--red)";
    return `
    <div class="hint-card ${side}" onclick="selectHint('${h.symbol}', '${h.side}', ${h.confidence})">
      <div class="hint-rr">R:R ${h.rr}</div>
      <div class="hint-top">
        <span class="hint-sym">${escH(h.symbol)}</span>
        <span class="hint-side ${side}">${h.side}</span>
      </div>
      <div class="hint-conf ${side}">${h.confidence}%</div>
      <div class="hint-prices">
        <div><span class="hl">Entry</span><div class="hv">${fmtP(h.price, h.symbol)}</div></div>
        <div><span class="hl">Stop</span><div class="hv" style="color:var(--red)">${fmtP(h.sl, h.symbol)}</div></div>
        <div><span class="hl">Target</span><div class="hv" style="color:var(--green)">${fmtP(h.tp, h.symbol)}</div></div>
      </div>
      <div class="hint-reasons">${reasons}</div>
    </div>`;
  }).join("");
}

function selectHint(symbol, side, confidence) {
  curSym = symbol;
  loadChart();
  loadTickers();
  loadOrderBook();
  loadAIAnalysis();
  document.querySelector('[data-rp="trade"]').click();
}

// ── Asset Filter ──────────────────────────────────────────────────────────────
function filterAsset(type) {
  assetFilter = type;
  document.querySelectorAll(".af-btn").forEach(b => b.classList.toggle("on", b.dataset.asset === type));
  renderWL();
  renderHM();
  renderTape();
}

// ── Trial Mode ────────────────────────────────────────────────────────────────
async function loadTrialStatus() {
  try {
    const r = await fetch("/api/trial/status");
    const d = await r.json();
    trialActive = d.active;
    document.getElementById("btnTrial").classList.toggle("on", d.active);
    document.getElementById("trialStat").style.display = d.active ? "flex" : "none";
    document.getElementById("trialTradeBox").style.display = d.active ? "block" : "none";
    document.getElementById("hTrial").textContent = "$" + (d.balance / 1000).toFixed(0) + "K";
    const tpEl = document.getElementById("trialPositions");
    if (tpEl && d.positions && d.positions.length) {
      tpEl.innerHTML = d.positions.map(p => {
        const pnlCls = p.pnl >= 0 ? "g" : "r";
        return `<div class="pos">
          <div class="pos-side ${p.side}">${p.side.toUpperCase()}</div>
          <div style="flex:1"><b>${p.symbol}</b> @ ${fmtP(p.entry, p.symbol)}</div>
          <div class="pos-pnl ${pnlCls}">${p.pnl >= 0 ? "+" : ""}$${fmtN(p.pnl)}</div>
          <button onclick="closeTrialPos(${p.id})" style="background:transparent;border:1px solid var(--red);color:var(--red);border-radius:4px;padding:2px 8px;cursor:pointer;font-size:11px">X</button>
        </div>`;
      }).join("");
    } else if (tpEl) {
      tpEl.innerHTML = '<div class="empty" style="padding:12px;color:var(--text3)">No trial positions</div>';
    }
  } catch (e) {}
}

async function toggleTrial() {
  if (trialActive) {
    if (confirm("Reset trial mode? All positions and history will be cleared.")) {
      await api("/api/trial/reset", "POST");
      trialActive = false;
      document.getElementById("btnTrial").classList.remove("on");
      document.getElementById("trialStat").style.display = "none";
    }
  } else {
    await api("/api/trial/start", "POST");
    trialActive = true;
    document.getElementById("btnTrial").classList.add("on");
    document.getElementById("trialStat").style.display = "flex";
  }
}

async function closeTrialPos(id) {
  try {
    const r = await fetch(`/api/trial/close/${id}`, { method: "POST" });
    const d = await r.json();
    if (d.status === "closed") {
      showNotif(`Closed ${d.trade?.symbol} — P&L: $${d.trade?.pnl}`, d.trade?.pnl >= 0 ? "green" : "red");
      loadTrialStatus();
    }
  } catch (e) { showNotif("Close failed: " + e.message, "red"); }
}

async function trialTrade(side) {
  if (!trialActive) {
    alert("Start Trial Mode first!");
    return;
  }
  const price = tickers[curSym]?.price || 0;
  if (!price) return;
  try {
    const r = await fetch("/api/trial/trade", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ symbol: curSym, side, price, risk_pct: 2.0 })
    });
    const d = await r.json();
    if (d.status === "opened") {
      showNotif(`${side.toUpperCase()} ${curSym} @ $${fmtP(price, curSym)} — AI Score: ${d.ai?.score || "N/A"}`, side === "buy" ? "green" : "red");
      loadTrialStatus();
    } else if (d.status === "rejected_by_ai") {
      showNotif(`AI REJECTED ${side.toUpperCase()} ${curSym} — Score: ${d.ai?.score}`, "yellow");
    } else {
      showNotif(`Error: ${d.error || d.status}`, "red");
    }
  } catch (e) { showNotif("Trade failed: " + e.message, "red"); }
}
