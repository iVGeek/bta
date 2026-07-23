"""
Claude AI layer for the trading bot.
- Signal confirmation: Claude validates each trade before execution
- Sentiment analysis: Claude processes market context/news
- Strategy optimization: Claude reviews trade history and suggests improvements
"""
import json
import logging
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger("ai")


class ClaudeTrader:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.trade_history: list[dict] = []
        self.strategy_notes: str = ""
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                logger.error("pip install anthropic")
                return None
        return self._client

    def _call(self, system: str, messages: list[dict], max_tokens: int = 1024) -> str:
        client = self._get_client()
        if not client:
            return '{"approved": true, "confidence": 50, "reason": "AI unavailable"}'

        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return '{"approved": true, "confidence": 50, "reason": "API error - defaulting to approve"}'

    # ── 1. Signal Confirmation ────────────────────────────────────────────
    def confirm_signal(self, signal: dict, market_data: dict = None) -> dict:
        """Claude reviews a trade signal and decides whether to approve it."""
        system = """You are a professional crypto trading analyst. You receive trade signals and must decide whether to approve or reject them.

RULES:
- Analyze the signal quality, risk/reward, and market context
- Consider the strategy scores, regime, MTF alignment
- Be conservative: reject signals with low confidence or poor setup
- Factor in drawdown risk and position concentration

Respond ONLY with valid JSON:
{
    "approved": true/false,
    "confidence": 0-100,
    "reason": "brief explanation",
    "adjustments": {
        "risk_pct": null or suggested override,
        "tp_adjustment": null or "wider"/"tighter",
        "skip_reason": null or reason to skip
    }
}"""

        signal_summary = {
            "signal": signal.get("signal"),
            "symbol": signal.get("symbol"),
            "price": signal.get("price"),
            "sl": signal.get("sl"),
            "tp": signal.get("tp"),
            "risk_pct": signal.get("risk_pct"),
            "score": signal.get("score"),
            "confidence": signal.get("confidence"),
            "regime": signal.get("regime"),
            "mtf_alignment": signal.get("mtf_alignment"),
            "sub_strategies": signal.get("sub_strategies"),
            "timeframe": signal.get("timeframe"),
        }

        if market_data:
            signal_summary["market_context"] = market_data

        messages = [{
            "role": "user",
            "content": f"Review this trade signal and decide whether to execute:\n\n{json.dumps(signal_summary, indent=2)}"
        }]

        raw = self._call(system, messages, max_tokens=512)
        return self._parse_json(raw, {
            "approved": True, "confidence": 50,
            "reason": "parse error", "adjustments": {}
        })

    # ── 2. Market Sentiment / Context ─────────────────────────────────────
    def analyze_market(self, symbol: str, price: float, indicators: dict,
                       recent_news: str = "") -> dict:
        """Claude provides market context and bias."""
        system = """You are a crypto market analyst. Given technical data, provide a concise market assessment.

Respond ONLY with valid JSON:
{
    "bias": "bullish"/"bearish"/"neutral",
    "strength": 0-100,
    "key_levels": {"support": price, "resistance": price},
    "risks": ["list of risks"],
    "catalyst": "upcoming events if known",
    "recommendation": "brief action recommendation"
}"""

        context = {
            "symbol": symbol,
            "current_price": price,
            "indicators": indicators,
        }
        if recent_news:
            context["recent_news"] = recent_news

        messages = [{
            "role": "user",
            "content": f"Analyze the current market for {symbol}:\n\n{json.dumps(context, indent=2)}"
        }]

        raw = self._call(system, messages, max_tokens=512)
        return self._parse_json(raw, {
            "bias": "neutral", "strength": 50,
            "risks": [], "recommendation": "hold"
        })

    # ── 3. Trade Journal & Review ─────────────────────────────────────────
    def log_trade(self, signal: dict, result: dict, outcome: str = "pending"):
        """Record a trade for later AI review."""
        self.trade_history.append({
            "timestamp": datetime.now().isoformat(),
            "signal": signal,
            "result": result,
            "outcome": outcome,
        })

    def review_trades(self, last_n: int = 20) -> dict:
        """Claude reviews recent trades and suggests improvements."""
        recent = self.trade_history[-last_n:]
        if not recent:
            return {"summary": "no trades to review", "suggestions": []}

        system = """You are a trading performance analyst. Review the trade journal and provide actionable improvements.

Respond ONLY with valid JSON:
{
    "win_rate": percentage,
    "avg_rr": number,
    "best_strategy": "name",
    "worst_strategy": "name",
    "patterns": ["observations about what works/doesn't"],
    "suggestions": ["specific actionable improvements"],
    "parameter_changes": {"param": "suggested_value"},
    "risk_adjustments": "any risk management changes needed"
}"""

        trade_summary = []
        for t in recent:
            trade_summary.append({
                "signal": t["signal"].get("signal"),
                "symbol": t["signal"].get("symbol"),
                "score": t["signal"].get("score"),
                "regime": t["signal"].get("regime"),
                "strategies": t["signal"].get("sub_strategies"),
                "outcome": t["outcome"],
            })

        messages = [{
            "role": "user",
            "content": f"Review these trades and suggest improvements:\n\n{json.dumps(trade_summary, indent=2)}"
        }]

        raw = self._call(system, messages, max_tokens=1024)
        return self._parse_json(raw, {"summary": "review failed", "suggestions": []})

    # ── 4. News / Social Sentiment ────────────────────────────────────────
    def analyze_sentiment(self, symbol: str, headlines: list[str]) -> dict:
        """Claude processes news headlines for sentiment."""
        system = """You are a crypto sentiment analyst. Analyze news headlines for a specific asset.

Respond ONLY with valid JSON:
{
    "sentiment": "positive"/"negative"/"neutral"/"mixed",
    "score": -100 to 100,
    "key_themes": ["main themes from news"],
    "impact": "high"/"medium"/"low",
    "contrarian_signal": true/false,
    "summary": "one sentence summary"
}"""

        messages = [{
            "role": "user",
            "content": f"Sentiment analysis for {symbol}:\n\nHeadlines:\n" + "\n".join(f"- {h}" for h in headlines[:10])
        }]

        raw = self._call(system, messages, max_tokens=512)
        return self._parse_json(raw, {
            "sentiment": "neutral", "score": 0,
            "impact": "low", "summary": "analysis unavailable"
        })

    # ── 5. Strategy Parameter Optimization ────────────────────────────────
    def optimize_params(self, strategy_name: str, current_params: dict,
                        performance: dict) -> dict:
        """Claude suggests parameter changes based on backtest results."""
        system = """You are a quantitative trading researcher. Suggest parameter optimizations.

Respond ONLY with valid JSON:
{
    "changes": {"param_name": {"current": value, "suggested": value, "reason": "why"}},
    "expected_impact": "description of expected improvement",
    "risk_notes": "any risks with these changes",
    "confidence": 0-100
}"""

        messages = [{
            "role": "user",
            "content": f"Optimize parameters for '{strategy_name}':\n\nCurrent params:\n{json.dumps(current_params, indent=2)}\n\nPerformance:\n{json.dumps(performance, indent=2)}"
        }]

        raw = self._call(system, messages, max_tokens=768)
        return self._parse_json(raw, {"changes": {}, "confidence": 0})

    # ── Helpers ───────────────────────────────────────────────────────────
    def _parse_json(self, raw: str, fallback: dict) -> dict:
        try:
            # Extract JSON from response (might be wrapped in markdown)
            text = raw.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text)
        except (json.JSONDecodeError, IndexError):
            logger.warning(f"Failed to parse Claude response: {raw[:200]}")
            return fallback
