import sys
sys.path.insert(0, "C:/iVGeek/trading-bot/executor")
from processor import SignalProcessor
from config import ExchangeConfig
from exchanges.connector import ExchangeManager
print("All executor imports OK")
print("SignalProcessor methods:", [m for m in dir(SignalProcessor) if not m.startswith("__")])
