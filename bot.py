import os
import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

API_KEY = os.environ["ALPACA_KEY"]
API_SECRET = os.environ["ALPACA_SECRET"]

WATCHLIST = ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD"]

trading_client = TradingClient(API_KEY, API_SECRET, paper=True)
data_client = CryptoHistoricalDataClient(API_KEY, API_SECRET)


def check_and_trade(symbol):
    bars_request = CryptoBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        limit=60
    )
    bars = data_client.get_crypto_bars(bars_request).df

    if bars.empty:
        print(f"{symbol}: no data returned")
        return

    if isinstance(bars.index, pd.MultiIndex):
        bars = bars.xs(symbol)

    closes = bars["close"]

    if len(closes) < 30:
        print(f"{symbol}: not enough data yet ({len(closes)} bars)")
        return

    short_ma = closes.rolling(10).mean().iloc[-1]
    long_ma = closes.rolling(30).mean().iloc[-1]

    position_qty = 0
    try:
        position = trading_client.get_open_position(symbol.replace("/", ""))
        position_qty = float(position.qty)
    except Exception:
        pass

    if short_ma > long_ma and position_qty == 0:
        print(f"{symbol}: buy signal")
        trading_client.submit_order(MarketOrderRequest(
            symbol=symbol, notional=100, side=OrderSide.BUY, time_in_force=TimeInForce.GTC
        ))
    elif short_ma < long_ma and position_qty > 0:
        print(f"{symbol}: sell signal")
        trading_client.submit_order(MarketOrderRequest(
            symbol=symbol, qty=position_qty, side=OrderSide.SELL, time_in_force=TimeInForce.GTC
        ))
    else:
        print(f"{symbol}: no signal")


for sym in WATCHLIST:
    try:
        check_and_trade(sym)
    except Exception as e:
        print(f"{sym}: error - {e}")
