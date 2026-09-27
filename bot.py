import os
import pandas as pd
from ta.trend import EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

API_KEY = os.environ["ALPACA_KEY"]
API_SECRET = os.environ["ALPACA_SECRET"]

WATCHLIST = ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD"]

# Strategy settings (from your Pine Script)
FAST_LEN = 5
SLOW_LEN = 12
RSI_LEN = 7
RSI_LONG = 40
RSI_LONG_EXIT = 35
ADX_LEN = 14
ADX_MIN = 0.0        # 0 = disabled, same as your default
VOL_LEN = 20
VOL_MIN_PCT = 0.0    # 0 = disabled
ATR_MULT = 1.5
MAX_DROP_PCT = 2.0
TRADE_NOTIONAL = 100  # dollars per buy

trading_client = TradingClient(API_KEY, API_SECRET, paper=True)
data_client = CryptoHistoricalDataClient(API_KEY, API_SECRET)


def check_and_trade(symbol):
    bars_request = CryptoBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        limit=100
    )
    bars = data_client.get_crypto_bars(bars_request).df

    if bars.empty:
        print(f"{symbol}: no data returned")
        return

    if isinstance(bars.index, pd.MultiIndex):
        bars = bars.xs(symbol)

    if len(bars) < max(SLOW_LEN, RSI_LEN, ADX_LEN, VOL_LEN) + 5:
        print(f"{symbol}: not enough data yet ({len(bars)} bars)")
        return

    close, high, low, volume = bars["close"], bars["high"], bars["low"], bars["volume"]

    fast_ema = EMAIndicator(close, FAST_LEN).ema_indicator()
    slow_ema = EMAIndicator(close, SLOW_LEN).ema_indicator()
    rsi = RSIIndicator(close, RSI_LEN).rsi()
    atr = AverageTrueRange(high, low, close, 14).average_true_range()
    adx = ADXIndicator(high, low, close, ADX_LEN).adx()
    vol_avg = volume.rolling(VOL_LEN).mean()

    last_close, last_fast, last_slow = close.iloc[-1], fast_ema.iloc[-1], slow_ema.iloc[-1]
    last_rsi, last_atr, last_adx = rsi.iloc[-1], atr.iloc[-1], adx.iloc[-1]
    last_vol, last_vol_avg = volume.iloc[-1], vol_avg.iloc[-1]
    prev_close, prev_fast, prev_rsi = close.iloc[-2], fast_ema.iloc[-2], rsi.iloc[-2]

    # ---- Entry conditions (long only) ----
    ema_long_state = last_fast > last_slow
    rsi_crossover = prev_rsi < RSI_LONG <= last_rsi
    price_crossover = prev_close < prev_fast and last_close > last_fast
    rsi_long_trigger = rsi_crossover or (last_rsi >= RSI_LONG and price_crossover)
    trend_strong = last_adx >= ADX_MIN
    vol_ok = VOL_MIN_PCT == 0.0 or (last_vol > last_vol_avg * VOL_MIN_PCT)

    raw_long = ema_long_state and rsi_long_trigger and trend_strong and vol_ok

    # ---- Current position, read directly from Alpaca ----
    position_qty, entry_price = 0.0, None
    try:
        position = trading_client.get_open_position(symbol.replace("/", ""))
        position_qty = float(position.qty)
        entry_price = float(position.avg_entry_price)
    except Exception:
        pass

    in_position = position_qty > 0

    # ---- Exit conditions ----
    stop_loss = (entry_price - last_atr * ATR_MULT) if entry_price else None
    bar_move_pct = (last_close - prev_close) / prev_close * 100

    hard_stop = in_position and stop_loss is not None and low.iloc[-1] <= stop_loss
    crash_exit = in_position and bar_move_pct <= -MAX_DROP_PCT
    trend_exit = in_position and (
        last_close < last_fast or last_fast < last_slow or last_rsi < RSI_LONG_EXIT
    )
    exit_long = in_position and (hard_stop or crash_exit or trend_exit)

    # ---- Act ----
    if raw_long and not in_position:
        print(f"{symbol}: buy signal")
        trading_client.submit_order(MarketOrderRequest(
            symbol=symbol, notional=TRADE_NOTIONAL, side=OrderSide.BUY, time_in_force=TimeInForce.GTC
        ))
    elif exit_long:
        reason = "stop/crash" if (hard_stop or crash_exit) else "trend"
        print(f"{symbol}: sell signal ({reason})")
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
