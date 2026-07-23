# iVGeek Quantum Trading Bot

A professional-grade multi-strategy trading bot written in Pine Script v5 for TradingView. Supports momentum, mean reversion, breakout, and smart money strategies with advanced risk management.

## Architecture

```
trading-bot/
├── pine/
│   ├── strategies/
│   │   ├── core_strategy.pine          # All-in-one bot with all 4 strategies
│   │   ├── momentum_strategy.pine      # Trend-following (EMA/RSI/MACD)
│   │   ├── mean_reversion_strategy.pine # BB bounce + RSI/stochastic
│   │   └── breakout_strategy.pine      # Volatility/volume breakouts
│   └── lib/
│       ├── risk_management.pine        # Kelly sizing, ATR stops, trails
│       └── indicators.pine             # Regime detection, S/R, order blocks
└── README.md
```

## Strategies

| Strategy | Market | Entry | Exit |
|----------|--------|-------|------|
| **Momentum** | Trending | EMA alignment + RSI > 50 + MACD bullish + volume spike | EMA cross / RSI divergence |
| **Mean Reversion** | Ranging | Price at BB extreme + oversold/overbought RSI + Stoch | Return to BB midline |
| **Breakout** | High Volatility | Price breaks 20-bar range + 2x volume + ATR expansion | ATR trail / range failure |
| **Smart Money** | Any | Liquidity sweep + BOS confirmation + trend filter | Standard SL/TP |

## Quick Start

### 1. Add to TradingView
- Open Pine Editor in TradingView
- Copy `pine/strategies/core_strategy.pine` into a new script
- Save and **Add to Chart**

### 2. Configure Inputs
The strategy exposes all key parameters as inputs:
- **Strategy Toggles**: Enable/disable each of the 4 strategies
- **Trade Direction**: Long only, Short only, or Both
- **Risk**: Position sizing (Kelly or fixed %), stop loss mode, trailing stop
- **Timeframe**: Multi-timeframe analysis (HTF EMA200 filter)
- **Webhook**: Set a `signalSecret` to authenticate webhook messages

### 3. Backtest
Click **Strategy Tester** tab to view:
- Net profit, win rate, Sharpe ratio, max drawdown
- Trade list with entry/exit prices
- Performance by strategy (check the Strategy Report)

### 4. Live Trading via Webhook
1. **Create Alert**: Click `...` on the indicator → `Add Alert`
2. **Condition**: Select your strategy name → choose a signal
3. **Options**: Check "Webhook URL"
4. **Webhook URL**: Point to your bot server (e.g., `https://your-server.com/webhook/tradingview`)
5. **JSON Payload**: The alert will send the built-in JSON automatically

Example webhook payload:
```json
{"action":"buy","symbol":"BINANCE:BTCUSDT","price":"45000","strategy":"momentum","score":"5","secret":"your_secret","id":"iVGeek-Bot-1"}
```

### 5. Forward to Exchange
Receive the webhook on your server and execute via CCXT (Binance, Bybit, etc.). The JSON includes all fields needed: action, symbol, price, strategy, and score.

## Risk Management

| Feature | Description |
|---------|-------------|
| **Kelly Criterion** | Dynamic position sizing based on win rate & avg win/loss |
| **Volatility Adjustment** | Reduces size in high vol, increases in low vol |
| **ATR Stops** | Stop loss based on market volatility |
| **S/R Stops** | Dynamic stops at support/resistance levels |
| **Trailing Stop** | Locks profit after price moves trailAct% in your favor |
| **Fixed % Stops** | Traditional percentage-based stop loss |
| **Trend Exit** | Exits when trend reverses (EMA21 + RSI) |

## Visualization

- **Buy/Sell Labels**: "STRONG BUY" / "STRONG SELL" for high-conviction signals
- **S/R Fractals**: Support (S) and Resistance (R) markers
- **Order Blocks**: Institutional order block markers
- **Liquidity Sweeps**: Stop hunt detection markers
- **BoS**: Break of Structure arrows
- **Stop/Target Lines**: Real-time SL/TP levels on chart
- **Regime Background**: Color-coded by market regime (bull/bear/ranging/volatile)
- **Dashboard**: On-chart performance table with all key metrics

## Performance Metrics Displayed

- Current market regime and volatility state
- Signal direction and score (L score / S score)
- Position state (LONG/SHORT/FLAT) with unrealized P&L
- Total trades, win rate, net profit
- Win/Loss ratio and Sharpe ratio
- Current risk % per trade

## Alert Conditions Available

| Alert | Trigger |
|-------|---------|
| Buy Signal | Any strategy triggers a long entry |
| Sell Signal | Any strategy triggers a short entry |
| Exit Long | Trend reversal exit |
| Exit Short | Trend reversal exit |
| Liquidity Grab Bull | Bullish stop hunt detected |
| Liquidity Grab Bear | Bearish stop hunt detected |
