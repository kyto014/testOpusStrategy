#!/usr/bin/env python3
"""
Asymmetric Long/Short Strategy V4 for ETHUSDT
==============================================
SHORT = "Panic Catcher" - aggressive, fast indicators, tight SL, quick TP
LONG = "Trend Confirmer" - conservative, slow indicators, wider SL, bigger TP

Key differences:
- Shorts use EMA 10/30 + fast MACD (8,17,5) + volume spikes
- Longs use EMA 50/200 + standard MACD (12,26,9) + trend confirmation
- Different risk per trade: shorts 1.5%, longs 1.0%
- Different SL/TP levels and time-based exits
- Different session multipliers for hour-of-day filtering
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import csv

# =============================================================================
# INDICATOR CALCULATIONS
# =============================================================================

def calculate_ema(data, period, column='Close'):
    """Calculate Exponential Moving Average"""
    return data[column].ewm(span=period, adjust=False).mean()

def calculate_rsi(data, period=14, column='Close'):
    """Calculate RSI indicator"""
    delta = data[column].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_atr(data, period=14):
    """Calculate Average True Range"""
    high_low = data['High'] - data['Low']
    high_close = np.abs(data['High'] - data['Close'].shift())
    low_close = np.abs(data['Low'] - data['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    atr = true_range.rolling(window=period).mean()
    return atr

def calculate_macd(data, fast=12, slow=26, signal=9, column='Close'):
    """Calculate MACD indicator"""
    ema_fast = data[column].ewm(span=fast, adjust=False).mean()
    ema_slow = data[column].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calculate_bollinger_bands(data, period=20, std_dev=2.0, column='Close'):
    """Calculate Bollinger Bands"""
    sma = data[column].rolling(window=period).mean()
    std = data[column].rolling(window=period).std()
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    return upper_band, sma, lower_band

# =============================================================================
# TIME FILTERS
# =============================================================================

def get_day_of_week(dt):
    """Get day of week (0=Monday, 6=Sunday)"""
    return dt.weekday()

def is_trading_allowed(dt, position_type=None):
    """Check if trading is allowed based on day/time filters"""
    day = get_day_of_week(dt)
    hour = dt.hour
    
    # No trading on weekends
    if day >= 5:  # Saturday (5) or Sunday (6)
        return False, 0.0
    
    # No new positions Friday after 18:00 UTC
    if day == 4 and hour >= 18:
        return False, 0.0
    
    # Get session multiplier based on position type and hour
    if position_type == 'SHORT':
        # Short sessions - more during high volatility
        if 8 <= hour < 11:
            multiplier = 1.0  # EU open
        elif 13 <= hour < 17:
            multiplier = 1.0  # US open
        elif 17 <= hour < 21:
            multiplier = 0.8
        elif 21 <= hour < 24 or 0 <= hour < 2:
            multiplier = 0.6
        elif 2 <= hour < 8:
            multiplier = 0.4  # Quiet Asian session
        else:
            multiplier = 0.6
    else:  # LONG
        # Long sessions - work in all sessions
        if 8 <= hour < 17:
            multiplier = 1.0
        elif 6 <= hour < 8 or 17 <= hour < 21:
            multiplier = 0.8
        elif 0 <= hour < 6 or 21 <= hour < 24:
            multiplier = 0.6
        else:
            multiplier = 0.6
    
    return True, multiplier

def should_close_for_friday(dt):
    """Check if positions should be closed for Friday 20:00 UTC"""
    return dt.weekday() == 4 and dt.hour >= 20

# =============================================================================
# ENTRY SIGNAL LOGIC
# =============================================================================

def check_short_entry(row, prev_row, indicators):
    """
    SHORT Entry Rules (ALL must be true):
    1. EMA 10 < EMA 30 (fast bearish cross) by at least 0.2%
    2. Close < EMA 10 (price below fast EMA)
    3. Fast MACD (8,17,5) histogram < 0 AND declining (getting more negative)
    4. RSI between 30 and 48 (bearish but not oversold yet)
    5. Volume > 1.8 × Volume SMA 20 (strong panic volume)
    6. Close < Lower BB (breakdown confirmed)
    7. Price momentum: close dropped > 0.5% from previous candle
    """
    # Rule 1: EMA 10 < EMA 30 by at least 0.2%
    if not (indicators['EMA_10'] < indicators['EMA_30'] and 
            (indicators['EMA_30'] - indicators['EMA_10']) / indicators['EMA_30'] > 0.002):
        return False
    
    # Rule 2: Close < EMA 10
    if not (row['Close'] < indicators['EMA_10']):
        return False
    
    # Rule 3: Fast MACD histogram < 0 AND declining
    if not (indicators['MACD_Fast_Hist'] < 0 and indicators['MACD_Fast_Hist'] < indicators['MACD_Fast_Hist_Prev']):
        return False
    
    # Rule 4: RSI between 30 and 48
    if not (30 <= indicators['RSI'] <= 48):
        return False
    
    # Rule 5: Volume > 1.8 × Volume SMA 20
    if not (row['Volume'] > 1.8 * indicators['Volume_SMA']):
        return False
    
    # Rule 6: Close < Lower BB
    if not (row['Close'] < indicators['BB_Lower']):
        return False
    
    # Rule 7: Price dropped > 0.5%
    if prev_row is None or not (row['Close'] < prev_row['Close'] * 0.995):
        return False
    
    return True

def check_long_entry(row, prev_row, indicators):
    """
    LONG Entry Rules (ALL must be true):
    1. EMA 50 > EMA 200 by at least 1.5% (strong uptrend)
    2. Close > EMA 50 AND close > EMA 30 (price above both)
    3. EMA 10 > EMA 30 (short-term bullish)
    4. Standard MACD histogram > 0 AND rising AND positive for at least 2 candles
    5. RSI between 55 and 70 (stronger bullish momentum)
    6. Volume > 1.2 × Volume SMA 20 (good volume confirmation)
    7. Previous 2 candles were both above EMA 50 (strong trend)
    8. Current candle is green (close > open) AND gained > 0.2%
    """
    # Rule 1: EMA 50 > EMA 200 by at least 1.5%
    if not (indicators['EMA_50'] > indicators['EMA_200'] and
            (indicators['EMA_50'] - indicators['EMA_200']) / indicators['EMA_200'] > 0.015):
        return False
    
    # Rule 2: Close > EMA 50 AND close > EMA 30
    if not (row['Close'] > indicators['EMA_50'] and row['Close'] > indicators['EMA_30']):
        return False
    
    # Rule 3: EMA 10 > EMA 30
    if not (indicators['EMA_10'] > indicators['EMA_30']):
        return False
    
    # Rule 4: MACD histogram > 0 AND rising
    if not (indicators['MACD_Hist'] > 0 and 
            indicators['MACD_Hist'] > indicators['MACD_Hist_Prev'] and
            indicators['MACD_Hist_Prev'] > 0):
        return False
    
    # Rule 5: RSI between 55 and 70
    if not (55 <= indicators['RSI'] <= 70):
        return False
    
    # Rule 6: Volume > 1.2 × Volume SMA 20
    if not (row['Volume'] >= 1.2 * indicators['Volume_SMA']):
        return False
    
    # Rule 7: Previous 2 candles above EMA 50
    if prev_row is None or not (prev_row['Close'] > indicators['EMA_50_Prev'] and
                                 indicators['Close_Prev2'] > indicators['EMA_50_Prev2']):
        return False
    
    # Rule 8: Current candle is green AND gained > 0.2%
    if not (row['Close'] > row['Open'] and row['Close'] > prev_row['Close'] * 1.002):
        return False
    
    return True

def check_consolidation_filters(row, indicators):
    """
    Additional filters:
    - No consolidation trading for LONGS: if abs(EMA50 - EMA200) / Close < 0.003
    - Minimum ATR filter: if ATR/Close < 0.005, skip ALL entries
    """
    # Minimum ATR filter (applies to both)
    if indicators['ATR'] / row['Close'] < 0.005:
        return False, False  # No long, no short
    
    # Long consolidation filter
    long_ok = True
    if abs(indicators['EMA_50'] - indicators['EMA_200']) / row['Close'] < 0.003:
        long_ok = False
    
    # Shorts work in consolidation
    short_ok = True
    
    return long_ok, short_ok

# =============================================================================
# POSITION MANAGEMENT
# =============================================================================

class Position:
    """Class to track position state"""
    def __init__(self, position_type, entry_price, entry_date, size, capital, 
                 sl_distance, tp1, tp2, tp3, trailing_stop_distance, 
                 max_duration, session_mult, risk_pct):
        self.type = position_type
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.size = size  # In ETH
        self.initial_size = size
        self.capital_at_entry = capital
        self.sl_distance = sl_distance
        self.stop_loss = entry_price - sl_distance if position_type == 'LONG' else entry_price + sl_distance
        self.tp1_price = tp1
        self.tp2_price = tp2
        self.tp3_price = tp3
        self.trailing_stop_distance = trailing_stop_distance
        self.max_duration = max_duration
        self.session_multiplier = session_mult
        self.risk_percent = risk_pct
        
        self.candles_held = 0
        self.tp1_hit = False
        self.tp2_hit = False
        self.tp3_hit = False
        self.trailing_stop_active = False
        self.trailing_stop_price = None
        self.sl_at_breakeven = False
        
        self.partial_closes = []
        self.total_pnl = 0
        self.total_commission = 0
        
    def update(self, current_price, current_date):
        """Update position state and check exits"""
        self.candles_held += 1
        
        # Update trailing stop if active
        if self.trailing_stop_active:
            if self.type == 'LONG':
                # Move trailing stop up as price increases
                new_stop = current_price - self.trailing_stop_distance
                if self.trailing_stop_price is None or new_stop > self.trailing_stop_price:
                    self.trailing_stop_price = new_stop
            else:  # SHORT
                # Move trailing stop down as price decreases
                new_stop = current_price + self.trailing_stop_distance
                if self.trailing_stop_price is None or new_stop < self.trailing_stop_price:
                    self.trailing_stop_price = new_stop
        
        # Check TP levels and execute partial closes
        if self.type == 'LONG':
            # TP1 check
            if not self.tp1_hit and current_price >= self.tp1_price:
                self.execute_partial_close(current_price, current_date, 'TP1', 0.40)
                self.tp1_hit = True
                # Move SL to break-even
                self.stop_loss = self.entry_price
                self.sl_at_breakeven = True
                # Activate trailing stop
                self.trailing_stop_active = True
                self.trailing_stop_price = current_price - self.trailing_stop_distance
            
            # TP2 check
            if not self.tp2_hit and current_price >= self.tp2_price:
                self.execute_partial_close(current_price, current_date, 'TP2', 0.30)
                self.tp2_hit = True
            
            # TP3 check
            if not self.tp3_hit and current_price >= self.tp3_price:
                self.execute_partial_close(current_price, current_date, 'TP3', 1.0)  # Close remaining
                self.tp3_hit = True
                
        else:  # SHORT
            # TP1 check
            if not self.tp1_hit and current_price <= self.tp1_price:
                self.execute_partial_close(current_price, current_date, 'TP1', 0.50)
                self.tp1_hit = True
                # Move SL to break-even
                self.stop_loss = self.entry_price
                self.sl_at_breakeven = True
                # Activate trailing stop
                self.trailing_stop_active = True
                self.trailing_stop_price = current_price + self.trailing_stop_distance
            
            # TP2 check
            if not self.tp2_hit and current_price <= self.tp2_price:
                self.execute_partial_close(current_price, current_date, 'TP2', 0.30)
                self.tp2_hit = True
            
            # TP3 check
            if not self.tp3_hit and current_price <= self.tp3_price:
                self.execute_partial_close(current_price, current_date, 'TP3', 1.0)  # Close remaining
                self.tp3_hit = True
    
    def execute_partial_close(self, price, date, reason, percentage):
        """Execute a partial close of the position"""
        if self.size <= 0:
            return
        
        close_size = self.initial_size * percentage if percentage < 1.0 else self.size
        close_size = min(close_size, self.size)  # Don't close more than remaining
        
        if close_size <= 0:
            return
        
        # Calculate PnL
        if self.type == 'LONG':
            pnl = (price - self.entry_price) * close_size
        else:
            pnl = (self.entry_price - price) * close_size
        
        # Commission
        commission = (self.entry_price * close_size * 0.0005) + (price * close_size * 0.0005)
        net_pnl = pnl - commission
        
        self.partial_closes.append({
            'date': date,
            'price': price,
            'size': close_size,
            'reason': reason,
            'pnl': pnl,
            'commission': commission,
            'net_pnl': net_pnl
        })
        
        self.total_pnl += net_pnl
        self.total_commission += commission
        self.size -= close_size
    
    def check_exit(self, current_price, current_date, rsi, should_close_friday):
        """
        Check all exit conditions in order:
        1. Stop Loss
        2. TPs handled in update()
        3. Trailing stop
        4. RSI extreme exit
        5. Time-based exit
        6. Friday close
        
        Returns: (should_exit, exit_reason)
        """
        if self.size <= 0:
            return True, 'FULLY_CLOSED'
        
        # 1. Stop Loss
        if self.type == 'LONG':
            if current_price <= self.stop_loss:
                return True, 'STOP_LOSS'
        else:
            if current_price >= self.stop_loss:
                return True, 'STOP_LOSS'
        
        # 3. Trailing stop (after TP1)
        if self.trailing_stop_active and self.trailing_stop_price is not None:
            if self.type == 'LONG':
                if current_price <= self.trailing_stop_price:
                    return True, 'TRAILING_STOP'
            else:
                if current_price >= self.trailing_stop_price:
                    return True, 'TRAILING_STOP'
        
        # 4. RSI extreme exit
        if self.type == 'LONG' and rsi > 80:
            return True, 'RSI_OVERBOUGHT'
        if self.type == 'SHORT' and rsi < 15:
            return True, 'RSI_OVERSOLD'
        
        # 5. Time-based exit
        if self.candles_held >= self.max_duration and not self.tp1_hit:
            return True, 'TIME_LIMIT'
        
        # 6. Friday close
        if should_close_friday:
            return True, 'FRIDAY_CLOSE'
        
        return False, None
    
    def close_remaining(self, price, date, reason):
        """Close any remaining position"""
        if self.size > 0:
            self.execute_partial_close(price, date, reason, 1.0)

# =============================================================================
# BACKTESTING ENGINE
# =============================================================================

def run_backtest():
    """Main backtesting function"""
    print("=" * 80)
    print("ASYMMETRIC LONG/SHORT STRATEGY V4 - BACKTEST")
    print("=" * 80)
    print()
    
    # Load data
    print("Loading data...")
    df = pd.read_csv('ETHUSDT_15_Minutes_year_2025.txt', 
                     names=['Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume'],
                     skiprows=1)
    
    # Combine date and time
    df['DateTime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'], format='%m/%d/%Y %H:%M:%S')
    df = df.sort_values('DateTime').reset_index(drop=True)
    
    print(f"Loaded {len(df)} candles from {df['DateTime'].iloc[0]} to {df['DateTime'].iloc[-1]}")
    print()
    
    # Calculate all indicators
    print("Calculating indicators...")
    df['EMA_10'] = calculate_ema(df, 10)
    df['EMA_30'] = calculate_ema(df, 30)
    df['EMA_50'] = calculate_ema(df, 50)
    df['EMA_200'] = calculate_ema(df, 200)
    df['RSI'] = calculate_rsi(df, 14)
    df['ATR'] = calculate_atr(df, 14)
    
    # Standard MACD
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calculate_macd(df, 12, 26, 9)
    
    # Fast MACD for shorts
    df['MACD_Fast'], df['MACD_Fast_Signal'], df['MACD_Fast_Hist'] = calculate_macd(df, 8, 17, 5)
    
    # Volume SMA
    df['Volume_SMA'] = df['Volume'].rolling(window=20).mean()
    
    # Bollinger Bands
    df['BB_Upper'], df['BB_Middle'], df['BB_Lower'] = calculate_bollinger_bands(df, 20, 2.0)
    
    print("Indicators calculated.")
    print()
    
    # Initialize backtest state
    initial_capital = 100000.0
    capital = initial_capital
    peak_capital = initial_capital
    max_drawdown_pct = 0
    max_drawdown_usd = 0
    
    long_position = None
    short_position = None
    
    trades = []
    equity_curve = []
    
    daily_pnl = {}
    weekly_pnl = {}
    
    # Start from index 200 to have enough data for indicators
    start_idx = 200
    
    print("Starting backtest...")
    print()
    
    for i in range(start_idx, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None
        current_dt = row['DateTime']
        current_price = row['Close']
        
        # Get current indicators
        indicators = {
            'EMA_10': row['EMA_10'],
            'EMA_30': row['EMA_30'],
            'EMA_50': row['EMA_50'],
            'EMA_200': row['EMA_200'],
            'EMA_50_Prev': df.iloc[i-1]['EMA_50'] if i > 0 else row['EMA_50'],
            'EMA_50_Prev2': df.iloc[i-2]['EMA_50'] if i > 1 else row['EMA_50'],
            'Close_Prev2': df.iloc[i-2]['Close'] if i > 1 else row['Close'],
            'RSI': row['RSI'],
            'ATR': row['ATR'],
            'MACD_Hist': row['MACD_Hist'],
            'MACD_Hist_Prev': df.iloc[i-1]['MACD_Hist'] if i > 0 else 0,
            'MACD_Fast_Hist': row['MACD_Fast_Hist'],
            'MACD_Fast_Hist_Prev': df.iloc[i-1]['MACD_Fast_Hist'] if i > 0 else 0,
            'Volume_SMA': row['Volume_SMA'],
            'BB_Upper': row['BB_Upper'],
            'BB_Middle': row['BB_Middle'],
            'BB_Lower': row['BB_Lower']
        }
        
        # Check for NaN in critical indicators
        if pd.isna(indicators['ATR']) or pd.isna(indicators['RSI']):
            continue
        
        # Update existing positions
        friday_close = should_close_for_friday(current_dt)
        
        if long_position:
            long_position.update(current_price, current_dt)
            should_exit, exit_reason = long_position.check_exit(current_price, current_dt, 
                                                                indicators['RSI'], friday_close)
            if should_exit:
                # Close remaining position
                long_position.close_remaining(current_price, current_dt, exit_reason)
                
                # Record trade
                trades.append({
                    'Type': 'LONG',
                    'EntryDate': long_position.entry_date,
                    'EntryPrice': long_position.entry_price,
                    'ExitDate': current_dt,
                    'ExitPrice': current_price,
                    'PositionSize': long_position.initial_size,
                    'PnL_USDT': long_position.total_pnl,
                    'Commission': long_position.total_commission,
                    'NetPnL': long_position.total_pnl,
                    'Duration_Candles': long_position.candles_held,
                    'ExitReason': exit_reason,
                    'SessionMultiplier': long_position.session_multiplier,
                    'RiskPercent': long_position.risk_percent,
                    'SL_Distance': long_position.sl_distance,
                    'TP1_Price': long_position.tp1_price,
                    'TP2_Price': long_position.tp2_price,
                    'TP3_Price': long_position.tp3_price
                })
                
                # Update capital
                capital += long_position.total_pnl
                
                # Track daily/weekly PnL
                date_key = current_dt.date()
                week_key = current_dt.isocalendar()[:2]  # (year, week)
                daily_pnl[date_key] = daily_pnl.get(date_key, 0) + long_position.total_pnl
                weekly_pnl[week_key] = weekly_pnl.get(week_key, 0) + long_position.total_pnl
                
                long_position = None
        
        if short_position:
            short_position.update(current_price, current_dt)
            should_exit, exit_reason = short_position.check_exit(current_price, current_dt, 
                                                                  indicators['RSI'], friday_close)
            if should_exit:
                # Close remaining position
                short_position.close_remaining(current_price, current_dt, exit_reason)
                
                # Record trade
                trades.append({
                    'Type': 'SHORT',
                    'EntryDate': short_position.entry_date,
                    'EntryPrice': short_position.entry_price,
                    'ExitDate': current_dt,
                    'ExitPrice': current_price,
                    'PositionSize': short_position.initial_size,
                    'PnL_USDT': short_position.total_pnl,
                    'Commission': short_position.total_commission,
                    'NetPnL': short_position.total_pnl,
                    'Duration_Candles': short_position.candles_held,
                    'ExitReason': exit_reason,
                    'SessionMultiplier': short_position.session_multiplier,
                    'RiskPercent': short_position.risk_percent,
                    'SL_Distance': short_position.sl_distance,
                    'TP1_Price': short_position.tp1_price,
                    'TP2_Price': short_position.tp2_price,
                    'TP3_Price': short_position.tp3_price
                })
                
                # Update capital
                capital += short_position.total_pnl
                
                # Track daily/weekly PnL
                date_key = current_dt.date()
                week_key = current_dt.isocalendar()[:2]
                daily_pnl[date_key] = daily_pnl.get(date_key, 0) + short_position.total_pnl
                weekly_pnl[week_key] = weekly_pnl.get(week_key, 0) + short_position.total_pnl
                
                short_position = None
        
        # Check max daily/weekly loss
        date_key = current_dt.date()
        week_key = current_dt.isocalendar()[:2]
        
        if date_key in daily_pnl and daily_pnl[date_key] < -capital * 0.03:
            continue  # Pause trading for rest of day
        
        if week_key in weekly_pnl and weekly_pnl[week_key] < -capital * 0.05:
            continue  # Pause trading for rest of week
        
        # Check if trading is allowed
        long_allowed, long_session_mult = is_trading_allowed(current_dt, 'LONG')
        short_allowed, short_session_mult = is_trading_allowed(current_dt, 'SHORT')
        
        if not long_allowed and not short_allowed:
            # Record equity curve
            equity_curve.append({
                'DateTime': current_dt,
                'Equity': capital,
                'DrawdownPercent': ((peak_capital - capital) / peak_capital * 100) if peak_capital > 0 else 0
            })
            continue
        
        # Check consolidation filters
        long_filter_ok, short_filter_ok = check_consolidation_filters(row, indicators)
        
        # Check for entry signals
        # Counter-signal logic: if opposite signal fires, close current position
        short_signal = short_filter_ok and short_allowed and check_short_entry(row, prev_row, indicators)
        long_signal = long_filter_ok and long_allowed and check_long_entry(row, prev_row, indicators)
        
        # Counter-signal exits
        if short_signal and long_position:
            # Close long position
            long_position.close_remaining(current_price, current_dt, 'COUNTER_SIGNAL')
            trades.append({
                'Type': 'LONG',
                'EntryDate': long_position.entry_date,
                'EntryPrice': long_position.entry_price,
                'ExitDate': current_dt,
                'ExitPrice': current_price,
                'PositionSize': long_position.initial_size,
                'PnL_USDT': long_position.total_pnl,
                'Commission': long_position.total_commission,
                'NetPnL': long_position.total_pnl,
                'Duration_Candles': long_position.candles_held,
                'ExitReason': 'COUNTER_SIGNAL',
                'SessionMultiplier': long_position.session_multiplier,
                'RiskPercent': long_position.risk_percent,
                'SL_Distance': long_position.sl_distance,
                'TP1_Price': long_position.tp1_price,
                'TP2_Price': long_position.tp2_price,
                'TP3_Price': long_position.tp3_price
            })
            capital += long_position.total_pnl
            date_key = current_dt.date()
            week_key = current_dt.isocalendar()[:2]
            daily_pnl[date_key] = daily_pnl.get(date_key, 0) + long_position.total_pnl
            weekly_pnl[week_key] = weekly_pnl.get(week_key, 0) + long_position.total_pnl
            long_position = None
        
        if long_signal and short_position:
            # Close short position
            short_position.close_remaining(current_price, current_dt, 'COUNTER_SIGNAL')
            trades.append({
                'Type': 'SHORT',
                'EntryDate': short_position.entry_date,
                'EntryPrice': short_position.entry_price,
                'ExitDate': current_dt,
                'ExitPrice': current_price,
                'PositionSize': short_position.initial_size,
                'PnL_USDT': short_position.total_pnl,
                'Commission': short_position.total_commission,
                'NetPnL': short_position.total_pnl,
                'Duration_Candles': short_position.candles_held,
                'ExitReason': 'COUNTER_SIGNAL',
                'SessionMultiplier': short_position.session_multiplier,
                'RiskPercent': short_position.risk_percent,
                'SL_Distance': short_position.sl_distance,
                'TP1_Price': short_position.tp1_price,
                'TP2_Price': short_position.tp2_price,
                'TP3_Price': short_position.tp3_price
            })
            capital += short_position.total_pnl
            date_key = current_dt.date()
            week_key = current_dt.isocalendar()[:2]
            daily_pnl[date_key] = daily_pnl.get(date_key, 0) + short_position.total_pnl
            weekly_pnl[week_key] = weekly_pnl.get(week_key, 0) + short_position.total_pnl
            short_position = None
        
        # Open new positions
        if short_signal and short_position is None:
            # Calculate position size
            risk_usdt = capital * 0.02 * short_session_mult
            sl_distance = 0.7 * indicators['ATR']
            position_size = risk_usdt / sl_distance
            
            # Calculate TP levels - good R:R
            tp1_price = current_price - (1.5 * indicators['ATR'])
            tp2_price = current_price - (3.0 * indicators['ATR'])
            tp3_price = current_price - (5.0 * indicators['ATR'])
            
            # Open short position
            short_position = Position(
                'SHORT', current_price, current_dt, position_size, capital,
                sl_distance, tp1_price, tp2_price, tp3_price,
                0.5 * indicators['ATR'],  # Tight trailing stop
                48,  # Max duration (12 hours)
                short_session_mult, 0.02
            )
        
        if long_signal and long_position is None:
            # Calculate position size
            risk_usdt = capital * 0.015 * long_session_mult
            sl_distance = 1.3 * indicators['ATR']
            position_size = risk_usdt / sl_distance
            
            # Calculate TP levels - good R:R
            tp1_price = current_price + (2.5 * indicators['ATR'])
            tp2_price = current_price + (4.5 * indicators['ATR'])
            tp3_price = current_price + (7.0 * indicators['ATR'])
            
            # Open long position
            long_position = Position(
                'LONG', current_price, current_dt, position_size, capital,
                sl_distance, tp1_price, tp2_price, tp3_price,
                0.9 * indicators['ATR'],  # Trailing stop
                192,  # Max duration (48 hours)
                long_session_mult, 0.015
            )
        
        # Update peak capital and drawdown
        if capital > peak_capital:
            peak_capital = capital
        
        current_dd_pct = ((peak_capital - capital) / peak_capital * 100) if peak_capital > 0 else 0
        current_dd_usd = peak_capital - capital
        
        if current_dd_pct > max_drawdown_pct:
            max_drawdown_pct = current_dd_pct
        if current_dd_usd > max_drawdown_usd:
            max_drawdown_usd = current_dd_usd
        
        # Record equity curve
        equity_curve.append({
            'DateTime': current_dt,
            'Equity': capital,
            'DrawdownPercent': current_dd_pct
        })
    
    # Close any remaining positions at the end
    if long_position:
        final_price = df.iloc[-1]['Close']
        final_date = df.iloc[-1]['DateTime']
        long_position.close_remaining(final_price, final_date, 'END_OF_DATA')
        trades.append({
            'Type': 'LONG',
            'EntryDate': long_position.entry_date,
            'EntryPrice': long_position.entry_price,
            'ExitDate': final_date,
            'ExitPrice': final_price,
            'PositionSize': long_position.initial_size,
            'PnL_USDT': long_position.total_pnl,
            'Commission': long_position.total_commission,
            'NetPnL': long_position.total_pnl,
            'Duration_Candles': long_position.candles_held,
            'ExitReason': 'END_OF_DATA',
            'SessionMultiplier': long_position.session_multiplier,
            'RiskPercent': long_position.risk_percent,
            'SL_Distance': long_position.sl_distance,
            'TP1_Price': long_position.tp1_price,
            'TP2_Price': long_position.tp2_price,
            'TP3_Price': long_position.tp3_price
        })
        capital += long_position.total_pnl
    
    if short_position:
        final_price = df.iloc[-1]['Close']
        final_date = df.iloc[-1]['DateTime']
        short_position.close_remaining(final_price, final_date, 'END_OF_DATA')
        trades.append({
            'Type': 'SHORT',
            'EntryDate': short_position.entry_date,
            'EntryPrice': short_position.entry_price,
            'ExitDate': final_date,
            'ExitPrice': final_price,
            'PositionSize': short_position.initial_size,
            'PnL_USDT': short_position.total_pnl,
            'Commission': short_position.total_commission,
            'NetPnL': short_position.total_pnl,
            'Duration_Candles': short_position.candles_held,
            'ExitReason': 'END_OF_DATA',
            'SessionMultiplier': short_position.session_multiplier,
            'RiskPercent': short_position.risk_percent,
            'SL_Distance': short_position.sl_distance,
            'TP1_Price': short_position.tp1_price,
            'TP2_Price': short_position.tp2_price,
            'TP3_Price': short_position.tp3_price
        })
        capital += short_position.total_pnl
    
    print("Backtest complete!")
    print()
    
    # Save trade log
    print("Saving trade_log_v4.csv...")
    if trades:
        trades_df = pd.DataFrame(trades)
        trades_df['Trade#'] = range(1, len(trades_df) + 1)
        trades_df['PnL_Percent'] = (trades_df['NetPnL'] / initial_capital) * 100
        
        # Reorder columns
        cols = ['Trade#', 'Type', 'EntryDate', 'EntryPrice', 'ExitDate', 'ExitPrice', 
                'PositionSize', 'PnL_USDT', 'PnL_Percent', 'Commission', 'NetPnL', 
                'Duration_Candles', 'ExitReason', 'SessionMultiplier', 'RiskPercent', 
                'SL_Distance', 'TP1_Price', 'TP2_Price', 'TP3_Price']
        trades_df = trades_df[cols]
        
        trades_df.to_csv('trade_log_v4.csv', index=False)
        print("✓ trade_log_v4.csv saved")
    else:
        print("✗ No trades executed")
    
    # Save equity curve
    print("Saving equity_curve_v4.csv...")
    if equity_curve:
        equity_df = pd.DataFrame(equity_curve)
        equity_df.to_csv('equity_curve_v4.csv', index=False)
        print("✓ equity_curve_v4.csv saved")
    print()
    
    # Calculate statistics
    print_results(trades, capital, initial_capital, max_drawdown_pct, max_drawdown_usd, equity_curve)
    
    # Generate markdown report
    generate_markdown_report(trades, capital, initial_capital, max_drawdown_pct, max_drawdown_usd, equity_curve)

# =============================================================================
# RESULTS ANALYSIS
# =============================================================================

def print_results(trades, final_capital, initial_capital, max_dd_pct, max_dd_usd, equity_curve):
    """Print comprehensive backtest results"""
    print("=" * 80)
    print("BACKTEST RESULTS")
    print("=" * 80)
    print()
    
    if not trades:
        print("No trades executed.")
        return
    
    trades_df = pd.DataFrame(trades)
    
    # Overall stats
    total_return_usd = final_capital - initial_capital
    total_return_pct = (total_return_usd / initial_capital) * 100
    
    print(f"Initial Capital:      ${initial_capital:,.2f}")
    print(f"Final Capital:        ${final_capital:,.2f}")
    print(f"Total Return:         ${total_return_usd:,.2f} ({total_return_pct:.2f}%)")
    print(f"Max Drawdown:         {max_dd_pct:.2f}% (${max_dd_usd:,.2f})")
    print()
    
    # Separate by type
    long_trades = trades_df[trades_df['Type'] == 'LONG']
    short_trades = trades_df[trades_df['Type'] == 'SHORT']
    
    print("=" * 80)
    print("LONG TRADES ANALYSIS")
    print("=" * 80)
    analyze_trades(long_trades, 'LONG')
    print()
    
    print("=" * 80)
    print("SHORT TRADES ANALYSIS")
    print("=" * 80)
    analyze_trades(short_trades, 'SHORT')
    print()
    
    # Combined stats
    print("=" * 80)
    print("COMBINED STATISTICS")
    print("=" * 80)
    
    total_trades = len(trades_df)
    winning_trades = trades_df[trades_df['NetPnL'] > 0]
    losing_trades = trades_df[trades_df['NetPnL'] <= 0]
    
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
    avg_win = winning_trades['NetPnL'].mean() if len(winning_trades) > 0 else 0
    avg_loss = losing_trades['NetPnL'].mean() if len(losing_trades) > 0 else 0
    avg_pnl = trades_df['NetPnL'].mean()
    
    total_wins = winning_trades['NetPnL'].sum() if len(winning_trades) > 0 else 0
    total_losses = abs(losing_trades['NetPnL'].sum()) if len(losing_trades) > 0 else 0
    profit_factor = (total_wins / total_losses) if total_losses > 0 else float('inf')
    
    print(f"Total Trades:         {total_trades}")
    print(f"Winning Trades:       {len(winning_trades)} ({win_rate:.2f}%)")
    print(f"Losing Trades:        {len(losing_trades)}")
    print(f"Average Win:          ${avg_win:.2f}")
    print(f"Average Loss:         ${avg_loss:.2f}")
    print(f"Average PnL:          ${avg_pnl:.2f}")
    print(f"Profit Factor:        {profit_factor:.2f}")
    print()
    
    # Best and worst trades
    best_long = long_trades.loc[long_trades['NetPnL'].idxmax()] if len(long_trades) > 0 else None
    worst_long = long_trades.loc[long_trades['NetPnL'].idxmin()] if len(long_trades) > 0 else None
    best_short = short_trades.loc[short_trades['NetPnL'].idxmax()] if len(short_trades) > 0 else None
    worst_short = short_trades.loc[short_trades['NetPnL'].idxmin()] if len(short_trades) > 0 else None
    
    if best_long is not None:
        print(f"Best LONG Trade:      ${best_long['NetPnL']:.2f} on {best_long['EntryDate']}")
    if worst_long is not None:
        print(f"Worst LONG Trade:     ${worst_long['NetPnL']:.2f} on {worst_long['EntryDate']}")
    if best_short is not None:
        print(f"Best SHORT Trade:     ${best_short['NetPnL']:.2f} on {best_short['EntryDate']}")
    if worst_short is not None:
        print(f"Worst SHORT Trade:    ${worst_short['NetPnL']:.2f} on {worst_short['EntryDate']}")
    print()
    
    # Sharpe Ratio (simplified)
    if equity_curve:
        equity_df = pd.DataFrame(equity_curve)
        equity_df['Returns'] = equity_df['Equity'].pct_change()
        daily_returns = equity_df['Returns'].dropna()
        
        if len(daily_returns) > 0 and daily_returns.std() > 0:
            sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(365 * 24 * 4)  # Annualized for 15-min data
            print(f"Sharpe Ratio:         {sharpe:.2f}")
        print()
    
    # Monthly breakdown
    trades_df['Month'] = pd.to_datetime(trades_df['EntryDate']).dt.to_period('M')
    monthly_pnl = trades_df.groupby('Month')['NetPnL'].sum()
    
    print("Monthly Returns:")
    for month, pnl in monthly_pnl.items():
        pct = (pnl / initial_capital) * 100
        print(f"  {month}: ${pnl:,.2f} ({pct:.2f}%)")
    print()
    
    # Hour of day profitability
    trades_df['Hour'] = pd.to_datetime(trades_df['EntryDate']).dt.hour
    hourly_pnl = trades_df.groupby('Hour')['NetPnL'].agg(['sum', 'count', 'mean'])
    
    print("Hour of Day Profitability (UTC):")
    for hour, row in hourly_pnl.iterrows():
        print(f"  {hour:02d}:00 - Trades: {int(row['count']):3d}, Total: ${row['sum']:8,.2f}, Avg: ${row['mean']:7,.2f}")
    print()
    
    # Day of week profitability
    trades_df['DayOfWeek'] = pd.to_datetime(trades_df['EntryDate']).dt.day_name()
    daily_pnl = trades_df.groupby('DayOfWeek')['NetPnL'].agg(['sum', 'count', 'mean'])
    
    print("Day of Week Profitability:")
    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    for day in day_order:
        if day in daily_pnl.index:
            row = daily_pnl.loc[day]
            print(f"  {day:9s} - Trades: {int(row['count']):3d}, Total: ${row['sum']:8,.2f}, Avg: ${row['mean']:7,.2f}")
    print()

def analyze_trades(trades_df, trade_type):
    """Analyze trades for a specific type"""
    if len(trades_df) == 0:
        print(f"No {trade_type} trades executed.")
        return
    
    total = len(trades_df)
    winners = trades_df[trades_df['NetPnL'] > 0]
    losers = trades_df[trades_df['NetPnL'] <= 0]
    
    win_rate = (len(winners) / total * 100) if total > 0 else 0
    avg_win = winners['NetPnL'].mean() if len(winners) > 0 else 0
    avg_loss = losers['NetPnL'].mean() if len(losers) > 0 else 0
    avg_pnl = trades_df['NetPnL'].mean()
    avg_duration = trades_df['Duration_Candles'].mean()
    
    total_wins = winners['NetPnL'].sum() if len(winners) > 0 else 0
    total_losses = abs(losers['NetPnL'].sum()) if len(losers) > 0 else 0
    profit_factor = (total_wins / total_losses) if total_losses > 0 else float('inf')
    
    print(f"Total {trade_type} Trades:    {total}")
    print(f"Winning Trades:          {len(winners)} ({win_rate:.2f}%)")
    print(f"Losing Trades:           {len(losers)}")
    print(f"Average Win:             ${avg_win:.2f}")
    print(f"Average Loss:            ${avg_loss:.2f}")
    print(f"Average PnL:             ${avg_pnl:.2f}")
    print(f"Average Duration:        {avg_duration:.1f} candles ({avg_duration * 15 / 60:.1f} hours)")
    print(f"Profit Factor:           {profit_factor:.2f}")
    
    # Exit reason breakdown
    print(f"\nExit Reasons for {trade_type}:")
    exit_reasons = trades_df['ExitReason'].value_counts()
    for reason, count in exit_reasons.items():
        pct = (count / total) * 100
        print(f"  {reason:20s}: {count:3d} ({pct:.1f}%)")

def generate_markdown_report(trades, final_capital, initial_capital, max_dd_pct, max_dd_usd, equity_curve):
    """Generate markdown report"""
    print("Generating STRATEGY_V4_RESULTS.md...")
    
    if not trades:
        return
    
    trades_df = pd.DataFrame(trades)
    total_return_usd = final_capital - initial_capital
    total_return_pct = (total_return_usd / initial_capital) * 100
    
    long_trades = trades_df[trades_df['Type'] == 'LONG']
    short_trades = trades_df[trades_df['Type'] == 'SHORT']
    
    with open('STRATEGY_V4_RESULTS.md', 'w') as f:
        f.write("# Asymmetric Long/Short Strategy V4 - Results\n\n")
        f.write("## Strategy Overview\n\n")
        f.write("This strategy uses completely different approaches for LONG and SHORT trades:\n\n")
        f.write("- **SHORT = \"Panic Catcher\"**: Aggressive entries with fast indicators (EMA 10/30, fast MACD), tight SL (0.8×ATR), quick TPs\n")
        f.write("- **LONG = \"Trend Confirmer\"**: Conservative entries with slow indicators (EMA 50/200, standard MACD), wider SL (1.5×ATR), bigger TPs\n\n")
        
        f.write("## Overall Performance\n\n")
        f.write(f"- **Initial Capital**: ${initial_capital:,.2f}\n")
        f.write(f"- **Final Capital**: ${final_capital:,.2f}\n")
        f.write(f"- **Total Return**: ${total_return_usd:,.2f} ({total_return_pct:.2f}%)\n")
        f.write(f"- **Max Drawdown**: {max_dd_pct:.2f}% (${max_dd_usd:,.2f})\n")
        f.write(f"- **Total Trades**: {len(trades_df)}\n\n")
        
        # Sharpe
        if equity_curve:
            equity_df = pd.DataFrame(equity_curve)
            equity_df['Returns'] = equity_df['Equity'].pct_change()
            daily_returns = equity_df['Returns'].dropna()
            if len(daily_returns) > 0 and daily_returns.std() > 0:
                sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(365 * 24 * 4)
                f.write(f"- **Sharpe Ratio**: {sharpe:.2f}\n\n")
        
        # Long stats
        f.write("## LONG Trades Analysis\n\n")
        if len(long_trades) > 0:
            long_winners = long_trades[long_trades['NetPnL'] > 0]
            long_win_rate = (len(long_winners) / len(long_trades) * 100)
            long_avg_pnl = long_trades['NetPnL'].mean()
            long_avg_duration = long_trades['Duration_Candles'].mean()
            
            long_total_wins = long_winners['NetPnL'].sum() if len(long_winners) > 0 else 0
            long_losers = long_trades[long_trades['NetPnL'] <= 0]
            long_total_losses = abs(long_losers['NetPnL'].sum()) if len(long_losers) > 0 else 0
            long_pf = (long_total_wins / long_total_losses) if long_total_losses > 0 else float('inf')
            
            f.write(f"- **Total LONG Trades**: {len(long_trades)}\n")
            f.write(f"- **Win Rate**: {long_win_rate:.2f}%\n")
            f.write(f"- **Average PnL**: ${long_avg_pnl:.2f}\n")
            f.write(f"- **Average Duration**: {long_avg_duration:.1f} candles ({long_avg_duration * 15 / 60:.1f} hours)\n")
            f.write(f"- **Profit Factor**: {long_pf:.2f}\n\n")
        else:
            f.write("No LONG trades executed.\n\n")
        
        # Short stats
        f.write("## SHORT Trades Analysis\n\n")
        if len(short_trades) > 0:
            short_winners = short_trades[short_trades['NetPnL'] > 0]
            short_win_rate = (len(short_winners) / len(short_trades) * 100)
            short_avg_pnl = short_trades['NetPnL'].mean()
            short_avg_duration = short_trades['Duration_Candles'].mean()
            
            short_total_wins = short_winners['NetPnL'].sum() if len(short_winners) > 0 else 0
            short_losers = short_trades[short_trades['NetPnL'] <= 0]
            short_total_losses = abs(short_losers['NetPnL'].sum()) if len(short_losers) > 0 else 0
            short_pf = (short_total_wins / short_total_losses) if short_total_losses > 0 else float('inf')
            
            f.write(f"- **Total SHORT Trades**: {len(short_trades)}\n")
            f.write(f"- **Win Rate**: {short_win_rate:.2f}%\n")
            f.write(f"- **Average PnL**: ${short_avg_pnl:.2f}\n")
            f.write(f"- **Average Duration**: {short_avg_duration:.1f} candles ({short_avg_duration * 15 / 60:.1f} hours)\n")
            f.write(f"- **Profit Factor**: {short_pf:.2f}\n\n")
        else:
            f.write("No SHORT trades executed.\n\n")
        
        # Monthly breakdown
        f.write("## Monthly Returns\n\n")
        trades_df['Month'] = pd.to_datetime(trades_df['EntryDate']).dt.to_period('M')
        monthly_pnl = trades_df.groupby('Month')['NetPnL'].sum()
        
        f.write("| Month | PnL (USD) | PnL (%) |\n")
        f.write("|-------|-----------|----------|\n")
        for month, pnl in monthly_pnl.items():
            pct = (pnl / initial_capital) * 100
            f.write(f"| {month} | ${pnl:,.2f} | {pct:.2f}% |\n")
        f.write("\n")
        
        # Exit reasons
        f.write("## Exit Reasons\n\n")
        f.write("### LONG Trades\n\n")
        if len(long_trades) > 0:
            long_exits = long_trades['ExitReason'].value_counts()
            for reason, count in long_exits.items():
                pct = (count / len(long_trades)) * 100
                f.write(f"- {reason}: {count} ({pct:.1f}%)\n")
        f.write("\n")
        
        f.write("### SHORT Trades\n\n")
        if len(short_trades) > 0:
            short_exits = short_trades['ExitReason'].value_counts()
            for reason, count in short_exits.items():
                pct = (count / len(short_trades)) * 100
                f.write(f"- {reason}: {count} ({pct:.1f}%)\n")
        f.write("\n")
        
        f.write("## Strategy Parameters\n\n")
        f.write("### SHORT (Panic Catcher)\n")
        f.write("- Risk per trade: 1.5%\n")
        f.write("- Stop Loss: 0.8 × ATR\n")
        f.write("- Take Profit 1: 1.5 × ATR (50% close)\n")
        f.write("- Take Profit 2: 3.0 × ATR (30% close)\n")
        f.write("- Take Profit 3: 5.0 × ATR (20% close)\n")
        f.write("- Max Duration: 48 candles (12 hours)\n\n")
        
        f.write("### LONG (Trend Confirmer)\n")
        f.write("- Risk per trade: 1.0%\n")
        f.write("- Stop Loss: 1.5 × ATR\n")
        f.write("- Take Profit 1: 2.5 × ATR (40% close)\n")
        f.write("- Take Profit 2: 4.0 × ATR (30% close)\n")
        f.write("- Take Profit 3: 6.0 × ATR (30% close)\n")
        f.write("- Max Duration: 192 candles (48 hours)\n\n")
    
    print("✓ STRATEGY_V4_RESULTS.md saved")
    print()

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    run_backtest()
