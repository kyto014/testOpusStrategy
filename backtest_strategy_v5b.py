#!/usr/bin/env python3
"""
Backtest Strategy V5B - Improved Long Conditions
Keeps V4 profitable shorts (58% WR, 2.43 PF), tightens long entry to improve from 31% WR
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys

# Configuration
DATA_FILE = 'ETHUSDT_15_Minutes_year_2025.txt'
INITIAL_CAPITAL = 10000
COMMISSION_RATE = 0.0005  # 0.05% each side

# Risk Management
MAX_POSITIONS = 2  # 1 per direction
DAILY_LOSS_LIMIT = 0.03  # 3%
WEEKLY_LOSS_LIMIT = 0.05  # 5%

# Position Risk Settings
SHORT_RISK_PCT = 0.02  # 2%
LONG_RISK_PCT = 0.015  # 1.5%

# Stop Loss Multipliers
SHORT_SL_ATR_MULT = 0.7
LONG_SL_ATR_MULT = 1.3

# Take Profit Settings (ATR multipliers)
SHORT_TP1_MULT = 1.5
SHORT_TP2_MULT = 3.0
SHORT_TP3_MULT = 5.0
SHORT_TP1_PCT = 0.50  # 50% at TP1
SHORT_TP2_PCT = 0.30  # 30% at TP2
SHORT_TP3_PCT = 0.20  # 20% at TP3
SHORT_TRAILING_ATR = 0.6

LONG_TP1_MULT = 2.5
LONG_TP2_MULT = 4.0
LONG_TP3_MULT = 6.0
LONG_TP1_PCT = 0.40  # 40% at TP1
LONG_TP2_PCT = 0.30  # 30% at TP2
LONG_TP3_PCT = 0.30  # 30% at TP3
LONG_TRAILING_ATR = 1.0

# Max Duration
SHORT_MAX_DURATION = 48  # candles
LONG_MAX_DURATION = 192  # candles

# Time-based Position Sizing
SHORT_HOUR_SIZING = {
    range(8, 12): 1.0,   # 100%
    range(13, 18): 1.0,  # 100%
    range(18, 22): 0.8,  # 80%
    range(22, 24): 0.6,  # 60%
    range(0, 3): 0.6,    # 60%
    range(3, 8): 0.4     # 40%
}

LONG_HOUR_SIZING = {
    range(8, 18): 1.0,   # 100%
    range(6, 8): 0.8,    # 80%
    range(18, 22): 0.8,  # 80%
    range(0, 6): 0.6,    # 60%
    range(22, 24): 0.6   # 60%
}


def load_data(filename):
    """Load and parse the data file"""
    df = pd.read_csv(filename, skipinitialspace=True)
    df.columns = df.columns.str.strip()
    df.columns = df.columns.str.replace('<', '').str.replace('>', '')
    
    # Parse datetime
    df['DateTime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'], format='%m/%d/%Y %H:%M:%S')
    df = df.sort_values('DateTime').reset_index(drop=True)
    
    # Convert to numeric
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    return df


def calculate_indicators(df):
    """Calculate all technical indicators"""
    # EMAs
    df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
    df['EMA30'] = df['Close'].ewm(span=30, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # ATR
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = pd.Series(true_range).rolling(window=14).mean()
    
    # MACD for longs (12, 26, 9)
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    
    # MACD Fast for shorts (8, 17, 5)
    ema8 = df['Close'].ewm(span=8, adjust=False).mean()
    ema17 = df['Close'].ewm(span=17, adjust=False).mean()
    df['MACD_Fast'] = ema8 - ema17
    df['MACD_Fast_Signal'] = df['MACD_Fast'].ewm(span=5, adjust=False).mean()
    df['MACD_Fast_Hist'] = df['MACD_Fast'] - df['MACD_Fast_Signal']
    
    # Volume SMA
    df['Volume_SMA20'] = df['Volume'].rolling(window=20).mean()
    
    # Bollinger Bands
    df['BB_Mid'] = df['Close'].rolling(window=20).mean()
    bb_std = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Mid'] + (bb_std * 2.0)
    df['BB_Lower'] = df['BB_Mid'] - (bb_std * 2.0)
    
    # Additional helper columns
    df['Prev_Close'] = df['Close'].shift(1)
    df['Price_Change_Pct'] = ((df['Close'] - df['Prev_Close']) / df['Prev_Close']) * 100
    df['MACD_Fast_Hist_Prev'] = df['MACD_Fast_Hist'].shift(1)
    df['MACD_Hist_Prev'] = df['MACD_Hist'].shift(1)
    
    # Consecutive closes above EMA50
    df['Above_EMA50'] = (df['Close'] > df['EMA50']).astype(int)
    df['Consec_Above_EMA50'] = df['Above_EMA50'].groupby((df['Above_EMA50'] != df['Above_EMA50'].shift()).cumsum()).cumsum()
    
    return df


def get_hour_sizing_factor(hour, direction):
    """Get position sizing factor based on hour and direction"""
    sizing_dict = SHORT_HOUR_SIZING if direction == 'SHORT' else LONG_HOUR_SIZING
    
    for hour_range, factor in sizing_dict.items():
        if hour in hour_range:
            return factor
    return 0.4  # Default fallback


def check_short_entry(row, prev_row):
    """Check if SHORT entry conditions are met (V4 specs - DO NOT CHANGE)"""
    if pd.isna(row['EMA10']) or pd.isna(row['EMA30']):
        return False
    
    # 1. EMA 10 < EMA 30
    if row['EMA10'] >= row['EMA30']:
        return False
    
    # 2. Close < EMA 10
    if row['Close'] >= row['EMA10']:
        return False
    
    # 3. Fast MACD histogram < 0 AND declining
    if row['MACD_Fast_Hist'] >= 0:
        return False
    if pd.notna(row['MACD_Fast_Hist_Prev']) and row['MACD_Fast_Hist'] >= row['MACD_Fast_Hist_Prev']:
        return False
    
    # 4. RSI between 28 and 47
    if row['RSI'] < 28 or row['RSI'] > 47:
        return False
    
    # 5. Volume > 1.9 × Volume SMA 20
    if row['Volume'] <= 1.9 * row['Volume_SMA20']:
        return False
    
    # 6. Close < Lower BB OR close dropped > 0.6% from previous
    condition_6a = row['Close'] < row['BB_Lower']
    condition_6b = (pd.notna(row['Prev_Close']) and 
                    row['Price_Change_Pct'] < -0.6)
    
    if not (condition_6a or condition_6b):
        return False
    
    return True


def check_long_entry(row, prev_row, prev_prev_row):
    """Check if LONG entry conditions are met (V5B - STRICTER)"""
    if pd.isna(row['EMA50']) or pd.isna(row['EMA200']):
        return False
    
    # 1. EMA 50 > EMA 200 by at least 1.5% (was 1.2% in V4)
    ema_spread_pct = ((row['EMA50'] - row['EMA200']) / row['EMA200']) * 100
    if ema_spread_pct < 1.5:
        return False
    
    # 2. EMA 10 > EMA 30 (NEW - short-term momentum confirmation)
    if row['EMA10'] <= row['EMA30']:
        return False
    
    # 3. Close > EMA 50
    if row['Close'] <= row['EMA50']:
        return False
    
    # 4. MACD histogram > 0 AND rising AND MACD histogram > 3 (was >2)
    if row['MACD_Hist'] <= 0:
        return False
    if pd.notna(row['MACD_Hist_Prev']) and row['MACD_Hist'] <= row['MACD_Hist_Prev']:
        return False
    if row['MACD_Hist'] <= 3:
        return False
    
    # 5. RSI between 50 and 70 (was 45-65)
    if row['RSI'] < 50 or row['RSI'] > 70:
        return False
    
    # 6. Volume > 1.3 × Volume SMA 20 (was 1.0×)
    if row['Volume'] <= 1.3 * row['Volume_SMA20']:
        return False
    
    # 7. 3 consecutive closes above EMA 50 (was 2)
    if row['Consec_Above_EMA50'] < 3:
        return False
    
    # 8. Close in upper 50% of Bollinger Bands (NEW)
    bb_range = row['BB_Upper'] - row['BB_Lower']
    if bb_range > 0:
        position_in_bb = (row['Close'] - row['BB_Lower']) / bb_range
        if position_in_bb < 0.5:
            return False
    
    # 9. No long if Close < EMA 200 (NEW)
    if row['Close'] < row['EMA200']:
        return False
    
    return True


def check_day_filter(dt):
    """Check if trading is allowed on this day"""
    # No weekends
    if dt.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False
    
    # No new positions Friday after 18:00
    if dt.weekday() == 4 and dt.hour >= 18:
        return False
    
    return True


def should_close_friday(dt):
    """Check if we should close all positions (Friday 20:00)"""
    return dt.weekday() == 4 and dt.hour >= 20


class Position:
    """Represents an open position"""
    def __init__(self, direction, entry_price, entry_time, size, stop_loss, 
                 tp1, tp2, tp3, atr, entry_idx):
        self.direction = direction
        self.entry_price = entry_price
        self.entry_time = entry_time
        self.size = size
        self.original_size = size
        self.stop_loss = stop_loss
        self.tp1 = tp1
        self.tp2 = tp2
        self.tp3 = tp3
        self.atr = atr
        self.entry_idx = entry_idx
        self.highest_price = entry_price if direction == 'LONG' else None
        self.lowest_price = entry_price if direction == 'SHORT' else None
        self.tp1_hit = False
        self.tp2_hit = False
        self.trailing_active = False
        self.trailing_stop = None
        
        # For tracking partial exits
        if direction == 'SHORT':
            self.tp1_pct = SHORT_TP1_PCT
            self.tp2_pct = SHORT_TP2_PCT
            self.tp3_pct = SHORT_TP3_PCT
            self.trailing_atr = SHORT_TRAILING_ATR
            self.max_duration = SHORT_MAX_DURATION
        else:
            self.tp1_pct = LONG_TP1_PCT
            self.tp2_pct = LONG_TP2_PCT
            self.tp3_pct = LONG_TP3_PCT
            self.trailing_atr = LONG_TRAILING_ATR
            self.max_duration = LONG_MAX_DURATION


def calculate_position_size(capital, risk_pct, entry_price, stop_loss, hour_factor):
    """Calculate position size based on risk"""
    risk_amount = capital * risk_pct * hour_factor
    price_risk = abs(entry_price - stop_loss)
    if price_risk == 0:
        return 0
    size = risk_amount / price_risk
    return size


def run_backtest(df):
    """Run the backtest"""
    capital = INITIAL_CAPITAL
    equity = capital
    positions = {'LONG': None, 'SHORT': None}
    trades = []
    equity_curve = [{'DateTime': df.iloc[0]['DateTime'], 'Equity': equity}]
    
    # Track daily/weekly losses
    daily_losses = {}
    weekly_losses = {}
    
    print(f"Starting backtest with {len(df)} candles...")
    print(f"Initial capital: ${capital:.2f}")
    print("-" * 80)
    
    for idx in range(200, len(df)):  # Start after indicator warmup
        row = df.iloc[idx]
        prev_row = df.iloc[idx-1] if idx > 0 else None
        prev_prev_row = df.iloc[idx-2] if idx > 1 else None
        
        dt = row['DateTime']
        current_date = dt.date()
        current_week = dt.isocalendar()[1]
        
        # Initialize loss tracking
        if current_date not in daily_losses:
            daily_losses[current_date] = 0
        if current_week not in weekly_losses:
            weekly_losses[current_week] = 0
        
        # Check Friday close
        if should_close_friday(dt):
            for direction in ['LONG', 'SHORT']:
                pos = positions[direction]
                if pos:
                    exit_price = row['Close']
                    pnl = calculate_pnl(pos, exit_price)
                    commission = calculate_commission(pos.entry_price, exit_price, pos.size)
                    net_pnl = pnl - commission
                    
                    equity += net_pnl
                    capital += net_pnl
                    
                    daily_losses[current_date] += net_pnl if net_pnl < 0 else 0
                    weekly_losses[current_week] += net_pnl if net_pnl < 0 else 0
                    
                    trades.append({
                        'Direction': pos.direction,
                        'Entry_Time': pos.entry_time,
                        'Exit_Time': dt,
                        'Entry_Price': pos.entry_price,
                        'Exit_Price': exit_price,
                        'Size': pos.size,
                        'PnL': pnl,
                        'Commission': commission,
                        'Net_PnL': net_pnl,
                        'Exit_Reason': 'Friday_Close',
                        'Duration': idx - pos.entry_idx
                    })
                    
                    positions[direction] = None
        
        # Update existing positions
        for direction in ['LONG', 'SHORT']:
            pos = positions[direction]
            if pos:
                # Update highest/lowest
                if direction == 'LONG':
                    if pos.highest_price is None or row['High'] > pos.highest_price:
                        pos.highest_price = row['High']
                else:
                    if pos.lowest_price is None or row['Low'] < pos.lowest_price:
                        pos.lowest_price = row['Low']
                
                # Check stop loss
                hit_sl = False
                exit_price = None
                
                if direction == 'LONG':
                    if pos.trailing_active and pos.trailing_stop:
                        if row['Low'] <= pos.trailing_stop:
                            hit_sl = True
                            exit_price = pos.trailing_stop
                    elif row['Low'] <= pos.stop_loss:
                        hit_sl = True
                        exit_price = pos.stop_loss
                else:  # SHORT
                    if pos.trailing_active and pos.trailing_stop:
                        if row['High'] >= pos.trailing_stop:
                            hit_sl = True
                            exit_price = pos.trailing_stop
                    elif row['High'] >= pos.stop_loss:
                        hit_sl = True
                        exit_price = pos.stop_loss
                
                if hit_sl:
                    pnl = calculate_pnl(pos, exit_price)
                    commission = calculate_commission(pos.entry_price, exit_price, pos.size)
                    net_pnl = pnl - commission
                    
                    equity += net_pnl
                    capital += net_pnl
                    
                    daily_losses[current_date] += net_pnl if net_pnl < 0 else 0
                    weekly_losses[current_week] += net_pnl if net_pnl < 0 else 0
                    
                    exit_reason = 'Trailing_Stop' if pos.trailing_active else 'Stop_Loss'
                    trades.append({
                        'Direction': pos.direction,
                        'Entry_Time': pos.entry_time,
                        'Exit_Time': dt,
                        'Entry_Price': pos.entry_price,
                        'Exit_Price': exit_price,
                        'Size': pos.size,
                        'PnL': pnl,
                        'Commission': commission,
                        'Net_PnL': net_pnl,
                        'Exit_Reason': exit_reason,
                        'Duration': idx - pos.entry_idx
                    })
                    
                    positions[direction] = None
                    continue
                
                # Check take profits
                if not pos.tp1_hit:
                    tp_hit = False
                    if direction == 'LONG' and row['High'] >= pos.tp1:
                        tp_hit = True
                        exit_price = pos.tp1
                    elif direction == 'SHORT' and row['Low'] <= pos.tp1:
                        tp_hit = True
                        exit_price = pos.tp1
                    
                    if tp_hit:
                        pos.tp1_hit = True
                        exit_size = pos.original_size * pos.tp1_pct
                        pnl = calculate_pnl_with_size(pos, exit_price, exit_size)
                        commission = calculate_commission(pos.entry_price, exit_price, exit_size)
                        net_pnl = pnl - commission
                        
                        equity += net_pnl
                        capital += net_pnl
                        
                        daily_losses[current_date] += net_pnl if net_pnl < 0 else 0
                        weekly_losses[current_week] += net_pnl if net_pnl < 0 else 0
                        
                        trades.append({
                            'Direction': pos.direction,
                            'Entry_Time': pos.entry_time,
                            'Exit_Time': dt,
                            'Entry_Price': pos.entry_price,
                            'Exit_Price': exit_price,
                            'Size': exit_size,
                            'PnL': pnl,
                            'Commission': commission,
                            'Net_PnL': net_pnl,
                            'Exit_Reason': 'TP1',
                            'Duration': idx - pos.entry_idx
                        })
                        
                        pos.size -= exit_size
                        # Move SL to breakeven
                        pos.stop_loss = pos.entry_price
                        # Activate trailing
                        pos.trailing_active = True
                
                elif not pos.tp2_hit:
                    tp_hit = False
                    if direction == 'LONG' and row['High'] >= pos.tp2:
                        tp_hit = True
                        exit_price = pos.tp2
                    elif direction == 'SHORT' and row['Low'] <= pos.tp2:
                        tp_hit = True
                        exit_price = pos.tp2
                    
                    if tp_hit:
                        pos.tp2_hit = True
                        exit_size = pos.original_size * pos.tp2_pct
                        pnl = calculate_pnl_with_size(pos, exit_price, exit_size)
                        commission = calculate_commission(pos.entry_price, exit_price, exit_size)
                        net_pnl = pnl - commission
                        
                        equity += net_pnl
                        capital += net_pnl
                        
                        daily_losses[current_date] += net_pnl if net_pnl < 0 else 0
                        weekly_losses[current_week] += net_pnl if net_pnl < 0 else 0
                        
                        trades.append({
                            'Direction': pos.direction,
                            'Entry_Time': pos.entry_time,
                            'Exit_Time': dt,
                            'Entry_Price': pos.entry_price,
                            'Exit_Price': exit_price,
                            'Size': exit_size,
                            'PnL': pnl,
                            'Commission': commission,
                            'Net_PnL': net_pnl,
                            'Exit_Reason': 'TP2',
                            'Duration': idx - pos.entry_idx
                        })
                        
                        pos.size -= exit_size
                
                else:
                    # Check TP3
                    tp_hit = False
                    if direction == 'LONG' and row['High'] >= pos.tp3:
                        tp_hit = True
                        exit_price = pos.tp3
                    elif direction == 'SHORT' and row['Low'] <= pos.tp3:
                        tp_hit = True
                        exit_price = pos.tp3
                    
                    if tp_hit:
                        # Close remaining position
                        exit_size = pos.size
                        pnl = calculate_pnl_with_size(pos, exit_price, exit_size)
                        commission = calculate_commission(pos.entry_price, exit_price, exit_size)
                        net_pnl = pnl - commission
                        
                        equity += net_pnl
                        capital += net_pnl
                        
                        daily_losses[current_date] += net_pnl if net_pnl < 0 else 0
                        weekly_losses[current_week] += net_pnl if net_pnl < 0 else 0
                        
                        trades.append({
                            'Direction': pos.direction,
                            'Entry_Time': pos.entry_time,
                            'Exit_Time': dt,
                            'Entry_Price': pos.entry_price,
                            'Exit_Price': exit_price,
                            'Size': exit_size,
                            'PnL': pnl,
                            'Commission': commission,
                            'Net_PnL': net_pnl,
                            'Exit_Reason': 'TP3',
                            'Duration': idx - pos.entry_idx
                        })
                        
                        positions[direction] = None
                        continue
                
                # Update trailing stop
                if pos.trailing_active:
                    if direction == 'LONG':
                        new_trailing = pos.highest_price - (pos.trailing_atr * pos.atr)
                        if pos.trailing_stop is None or new_trailing > pos.trailing_stop:
                            pos.trailing_stop = new_trailing
                    else:  # SHORT
                        new_trailing = pos.lowest_price + (pos.trailing_atr * pos.atr)
                        if pos.trailing_stop is None or new_trailing < pos.trailing_stop:
                            pos.trailing_stop = new_trailing
                
                # Check max duration
                duration = idx - pos.entry_idx
                if duration >= pos.max_duration:
                    exit_price = row['Close']
                    pnl = calculate_pnl(pos, exit_price)
                    commission = calculate_commission(pos.entry_price, exit_price, pos.size)
                    net_pnl = pnl - commission
                    
                    equity += net_pnl
                    capital += net_pnl
                    
                    daily_losses[current_date] += net_pnl if net_pnl < 0 else 0
                    weekly_losses[current_week] += net_pnl if net_pnl < 0 else 0
                    
                    trades.append({
                        'Direction': pos.direction,
                        'Entry_Time': pos.entry_time,
                        'Exit_Time': dt,
                        'Entry_Price': pos.entry_price,
                        'Exit_Price': exit_price,
                        'Size': pos.size,
                        'PnL': pnl,
                        'Commission': commission,
                        'Net_PnL': net_pnl,
                        'Exit_Reason': 'Max_Duration',
                        'Duration': duration
                    })
                    
                    positions[direction] = None
                    continue
                
                # Check RSI extreme exits
                if direction == 'LONG' and row['RSI'] > 80:
                    exit_price = row['Close']
                    pnl = calculate_pnl(pos, exit_price)
                    commission = calculate_commission(pos.entry_price, exit_price, pos.size)
                    net_pnl = pnl - commission
                    
                    equity += net_pnl
                    capital += net_pnl
                    
                    daily_losses[current_date] += net_pnl if net_pnl < 0 else 0
                    weekly_losses[current_week] += net_pnl if net_pnl < 0 else 0
                    
                    trades.append({
                        'Direction': pos.direction,
                        'Entry_Time': pos.entry_time,
                        'Exit_Time': dt,
                        'Entry_Price': pos.entry_price,
                        'Exit_Price': exit_price,
                        'Size': pos.size,
                        'PnL': pnl,
                        'Commission': commission,
                        'Net_PnL': net_pnl,
                        'Exit_Reason': 'RSI_Extreme',
                        'Duration': idx - pos.entry_idx
                    })
                    
                    positions[direction] = None
                    continue
                
                elif direction == 'SHORT' and row['RSI'] < 20:
                    exit_price = row['Close']
                    pnl = calculate_pnl(pos, exit_price)
                    commission = calculate_commission(pos.entry_price, exit_price, pos.size)
                    net_pnl = pnl - commission
                    
                    equity += net_pnl
                    capital += net_pnl
                    
                    daily_losses[current_date] += net_pnl if net_pnl < 0 else 0
                    weekly_losses[current_week] += net_pnl if net_pnl < 0 else 0
                    
                    trades.append({
                        'Direction': pos.direction,
                        'Entry_Time': pos.entry_time,
                        'Exit_Time': dt,
                        'Entry_Price': pos.entry_price,
                        'Exit_Price': exit_price,
                        'Size': pos.size,
                        'PnL': pnl,
                        'Commission': commission,
                        'Net_PnL': net_pnl,
                        'Exit_Reason': 'RSI_Extreme',
                        'Duration': idx - pos.entry_idx
                    })
                    
                    positions[direction] = None
                    continue
        
        # Check loss limits
        if abs(daily_losses[current_date]) >= capital * DAILY_LOSS_LIMIT:
            continue
        if abs(weekly_losses[current_week]) >= capital * WEEKLY_LOSS_LIMIT:
            continue
        
        # Check for new entries
        if not check_day_filter(dt):
            equity_curve.append({'DateTime': dt, 'Equity': equity})
            continue
        
        hour_factor_short = get_hour_sizing_factor(dt.hour, 'SHORT')
        hour_factor_long = get_hour_sizing_factor(dt.hour, 'LONG')
        
        # Check SHORT entry
        if positions['SHORT'] is None and hour_factor_short > 0:
            if check_short_entry(row, prev_row):
                entry_price = row['Close']
                atr = row['ATR']
                stop_loss = entry_price + (SHORT_SL_ATR_MULT * atr)
                tp1 = entry_price - (SHORT_TP1_MULT * atr)
                tp2 = entry_price - (SHORT_TP2_MULT * atr)
                tp3 = entry_price - (SHORT_TP3_MULT * atr)
                
                size = calculate_position_size(capital, SHORT_RISK_PCT, entry_price, 
                                               stop_loss, hour_factor_short)
                
                if size > 0:
                    positions['SHORT'] = Position('SHORT', entry_price, dt, size, 
                                                  stop_loss, tp1, tp2, tp3, atr, idx)
        
        # Check LONG entry
        if positions['LONG'] is None and hour_factor_long > 0:
            if check_long_entry(row, prev_row, prev_prev_row):
                entry_price = row['Close']
                atr = row['ATR']
                stop_loss = entry_price - (LONG_SL_ATR_MULT * atr)
                tp1 = entry_price + (LONG_TP1_MULT * atr)
                tp2 = entry_price + (LONG_TP2_MULT * atr)
                tp3 = entry_price + (LONG_TP3_MULT * atr)
                
                size = calculate_position_size(capital, LONG_RISK_PCT, entry_price, 
                                               stop_loss, hour_factor_long)
                
                if size > 0:
                    positions['LONG'] = Position('LONG', entry_price, dt, size, 
                                                 stop_loss, tp1, tp2, tp3, atr, idx)
        
        equity_curve.append({'DateTime': dt, 'Equity': equity})
    
    # Close any remaining positions
    final_row = df.iloc[-1]
    for direction in ['LONG', 'SHORT']:
        pos = positions[direction]
        if pos:
            exit_price = final_row['Close']
            pnl = calculate_pnl(pos, exit_price)
            commission = calculate_commission(pos.entry_price, exit_price, pos.size)
            net_pnl = pnl - commission
            
            equity += net_pnl
            
            trades.append({
                'Direction': pos.direction,
                'Entry_Time': pos.entry_time,
                'Exit_Time': final_row['DateTime'],
                'Entry_Price': pos.entry_price,
                'Exit_Price': exit_price,
                'Size': pos.size,
                'PnL': pnl,
                'Commission': commission,
                'Net_PnL': net_pnl,
                'Exit_Reason': 'End_of_Data',
                'Duration': len(df) - pos.entry_idx
            })
    
    return trades, equity_curve, equity


def calculate_pnl(pos, exit_price):
    """Calculate P&L for a position"""
    if pos.direction == 'LONG':
        return (exit_price - pos.entry_price) * pos.size
    else:  # SHORT
        return (pos.entry_price - exit_price) * pos.size


def calculate_pnl_with_size(pos, exit_price, size):
    """Calculate P&L for a specific size"""
    if pos.direction == 'LONG':
        return (exit_price - pos.entry_price) * size
    else:  # SHORT
        return (pos.entry_price - exit_price) * size


def calculate_commission(entry_price, exit_price, size):
    """Calculate total commission (entry + exit)"""
    entry_commission = entry_price * size * COMMISSION_RATE
    exit_commission = exit_price * size * COMMISSION_RATE
    return entry_commission + exit_commission


def analyze_results(trades, equity_curve, final_equity):
    """Analyze and print backtest results"""
    if not trades:
        print("No trades executed!")
        return
    
    trades_df = pd.DataFrame(trades)
    
    # Overall stats
    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df['Net_PnL'] > 0])
    losing_trades = len(trades_df[trades_df['Net_PnL'] < 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    total_profit = trades_df[trades_df['Net_PnL'] > 0]['Net_PnL'].sum()
    total_loss = abs(trades_df[trades_df['Net_PnL'] < 0]['Net_PnL'].sum())
    profit_factor = (total_profit / total_loss) if total_loss > 0 else float('inf')
    
    total_return = ((final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100
    
    # Calculate drawdown
    equity_df = pd.DataFrame(equity_curve)
    equity_df['Peak'] = equity_df['Equity'].cummax()
    equity_df['Drawdown'] = (equity_df['Equity'] - equity_df['Peak']) / equity_df['Peak'] * 100
    max_drawdown = equity_df['Drawdown'].min()
    
    # Sharpe ratio (simplified, assuming risk-free rate = 0)
    equity_df['Returns'] = equity_df['Equity'].pct_change()
    sharpe = (equity_df['Returns'].mean() / equity_df['Returns'].std() * np.sqrt(252 * 24 * 4)) if equity_df['Returns'].std() > 0 else 0
    
    print("\n" + "=" * 80)
    print("BACKTEST RESULTS - Strategy V5B")
    print("=" * 80)
    
    print(f"\nOVERALL PERFORMANCE:")
    print(f"  Initial Capital:        ${INITIAL_CAPITAL:,.2f}")
    print(f"  Final Equity:           ${final_equity:,.2f}")
    print(f"  Total Return:           {total_return:.2f}%")
    print(f"  Max Drawdown:           {max_drawdown:.2f}%")
    print(f"  Sharpe Ratio:           {sharpe:.2f}")
    
    print(f"\nTRADE STATISTICS:")
    print(f"  Total Trades:           {total_trades}")
    print(f"  Winning Trades:         {winning_trades} ({win_rate:.2f}%)")
    print(f"  Losing Trades:          {losing_trades}")
    print(f"  Profit Factor:          {profit_factor:.2f}")
    print(f"  Average Win:            ${trades_df[trades_df['Net_PnL'] > 0]['Net_PnL'].mean():.2f}" if winning_trades > 0 else "  Average Win:            $0.00")
    print(f"  Average Loss:           ${trades_df[trades_df['Net_PnL'] < 0]['Net_PnL'].mean():.2f}" if losing_trades > 0 else "  Average Loss:           $0.00")
    print(f"  Best Trade:             ${trades_df['Net_PnL'].max():.2f}")
    print(f"  Worst Trade:            ${trades_df['Net_PnL'].min():.2f}")
    
    # Long vs Short breakdown
    long_trades = trades_df[trades_df['Direction'] == 'LONG']
    short_trades = trades_df[trades_df['Direction'] == 'SHORT']
    
    print("\n" + "-" * 80)
    print("LONG TRADES BREAKDOWN:")
    if len(long_trades) > 0:
        long_wins = len(long_trades[long_trades['Net_PnL'] > 0])
        long_wr = (long_wins / len(long_trades) * 100)
        long_profit = long_trades[long_trades['Net_PnL'] > 0]['Net_PnL'].sum()
        long_loss = abs(long_trades[long_trades['Net_PnL'] < 0]['Net_PnL'].sum())
        long_pf = (long_profit / long_loss) if long_loss > 0 else float('inf')
        
        print(f"  Total Long Trades:      {len(long_trades)}")
        print(f"  Long Win Rate:          {long_wr:.2f}%")
        print(f"  Long Profit Factor:     {long_pf:.2f}")
        print(f"  Long Total P&L:         ${long_trades['Net_PnL'].sum():.2f}")
        print(f"  Long Avg Win:           ${long_trades[long_trades['Net_PnL'] > 0]['Net_PnL'].mean():.2f}" if long_wins > 0 else "  Long Avg Win:           $0.00")
        print(f"  Long Avg Loss:          ${long_trades[long_trades['Net_PnL'] < 0]['Net_PnL'].mean():.2f}" if len(long_trades[long_trades['Net_PnL'] < 0]) > 0 else "  Long Avg Loss:          $0.00")
    else:
        print("  No long trades executed")
    
    print("\n" + "-" * 80)
    print("SHORT TRADES BREAKDOWN:")
    if len(short_trades) > 0:
        short_wins = len(short_trades[short_trades['Net_PnL'] > 0])
        short_wr = (short_wins / len(short_trades) * 100)
        short_profit = short_trades[short_trades['Net_PnL'] > 0]['Net_PnL'].sum()
        short_loss = abs(short_trades[short_trades['Net_PnL'] < 0]['Net_PnL'].sum())
        short_pf = (short_profit / short_loss) if short_loss > 0 else float('inf')
        
        print(f"  Total Short Trades:     {len(short_trades)}")
        print(f"  Short Win Rate:         {short_wr:.2f}%")
        print(f"  Short Profit Factor:    {short_pf:.2f}")
        print(f"  Short Total P&L:        ${short_trades['Net_PnL'].sum():.2f}")
        print(f"  Short Avg Win:          ${short_trades[short_trades['Net_PnL'] > 0]['Net_PnL'].mean():.2f}" if short_wins > 0 else "  Short Avg Win:          $0.00")
        print(f"  Short Avg Loss:         ${short_trades[short_trades['Net_PnL'] < 0]['Net_PnL'].mean():.2f}" if len(short_trades[short_trades['Net_PnL'] < 0]) > 0 else "  Short Avg Loss:         $0.00")
    else:
        print("  No short trades executed")
    
    # Exit reasons breakdown
    print("\n" + "-" * 80)
    print("EXIT REASONS:")
    exit_reasons = trades_df['Exit_Reason'].value_counts()
    for reason, count in exit_reasons.items():
        print(f"  {reason:20s}    {count:3d} ({count/total_trades*100:.1f}%)")
    
    # Monthly breakdown
    trades_df['Month'] = pd.to_datetime(trades_df['Exit_Time']).dt.to_period('M')
    monthly = trades_df.groupby('Month').agg({
        'Net_PnL': ['sum', 'count']
    }).round(2)
    
    print("\n" + "-" * 80)
    print("MONTHLY BREAKDOWN:")
    print(f"  {'Month':<10s} {'Trades':>8s} {'P&L':>12s}")
    for month, row in monthly.iterrows():
        print(f"  {str(month):<10s} {int(row[('Net_PnL', 'count')]):>8d} ${row[('Net_PnL', 'sum')]:>11.2f}")
    
    # Hourly breakdown
    trades_df['Hour'] = pd.to_datetime(trades_df['Entry_Time']).dt.hour
    hourly = trades_df.groupby('Hour').agg({
        'Net_PnL': ['sum', 'count']
    }).round(2)
    
    print("\n" + "-" * 80)
    print("HOURLY BREAKDOWN (Top 10):")
    print(f"  {'Hour':>4s} {'Trades':>8s} {'P&L':>12s}")
    hourly_sorted = hourly.sort_values(('Net_PnL', 'sum'), ascending=False).head(10)
    for hour, row in hourly_sorted.iterrows():
        print(f"  {int(hour):>4d} {int(row[('Net_PnL', 'count')]):>8d} ${row[('Net_PnL', 'sum')]:>11.2f}")
    
    # Daily breakdown (day of week)
    trades_df['DayOfWeek'] = pd.to_datetime(trades_df['Entry_Time']).dt.day_name()
    daily = trades_df.groupby('DayOfWeek').agg({
        'Net_PnL': ['sum', 'count']
    }).round(2)
    
    print("\n" + "-" * 80)
    print("DAY OF WEEK BREAKDOWN:")
    print(f"  {'Day':<10s} {'Trades':>8s} {'P&L':>12s}")
    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    for day in day_order:
        if day in daily.index:
            row = daily.loc[day]
            print(f"  {day:<10s} {int(row[('Net_PnL', 'count')]):>8d} ${row[('Net_PnL', 'sum')]:>11.2f}")
    
    print("\n" + "=" * 80)


def main():
    """Main function"""
    print("Loading data...")
    df = load_data(DATA_FILE)
    print(f"Loaded {len(df)} candles from {df.iloc[0]['DateTime']} to {df.iloc[-1]['DateTime']}")
    
    print("\nCalculating indicators...")
    df = calculate_indicators(df)
    
    print("\nRunning backtest...")
    trades, equity_curve, final_equity = run_backtest(df)
    
    # Save results
    print("\nSaving results...")
    trades_df = pd.DataFrame(trades)
    trades_df.to_csv('trade_log_v5b.csv', index=False)
    print(f"  Saved trade_log_v5b.csv ({len(trades_df)} trades)")
    
    equity_df = pd.DataFrame(equity_curve)
    equity_df.to_csv('equity_curve_v5b.csv', index=False)
    print(f"  Saved equity_curve_v5b.csv ({len(equity_df)} points)")
    
    # Analyze results
    analyze_results(trades, equity_curve, final_equity)
    
    # Generate markdown report
    generate_markdown_report(trades_df, equity_curve, final_equity)
    
    print("\n" + "=" * 80)
    print(f"Backtest complete! Final equity: ${final_equity:,.2f}")
    print("=" * 80)


def generate_markdown_report(trades_df, equity_curve, final_equity):
    """Generate detailed markdown report"""
    if trades_df.empty:
        return
    
    equity_df = pd.DataFrame(equity_curve)
    equity_df['Peak'] = equity_df['Equity'].cummax()
    equity_df['Drawdown'] = (equity_df['Equity'] - equity_df['Peak']) / equity_df['Peak'] * 100
    max_drawdown = equity_df['Drawdown'].min()
    
    equity_df['Returns'] = equity_df['Equity'].pct_change()
    sharpe = (equity_df['Returns'].mean() / equity_df['Returns'].std() * np.sqrt(252 * 24 * 4)) if equity_df['Returns'].std() > 0 else 0
    
    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df['Net_PnL'] > 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    total_profit = trades_df[trades_df['Net_PnL'] > 0]['Net_PnL'].sum()
    total_loss = abs(trades_df[trades_df['Net_PnL'] < 0]['Net_PnL'].sum())
    profit_factor = (total_profit / total_loss) if total_loss > 0 else float('inf')
    
    total_return = ((final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100
    
    long_trades = trades_df[trades_df['Direction'] == 'LONG']
    short_trades = trades_df[trades_df['Direction'] == 'SHORT']
    
    with open('STRATEGY_V5B_RESULTS.md', 'w') as f:
        f.write("# Strategy V5B Backtest Results\n\n")
        f.write("## Objective\n\n")
        f.write("Improved Long Conditions version of V4. V4 showed longs with only 31% win rate and 0.50 profit factor.\n")
        f.write("V5B keeps profitable V4 shorts (58% WR, 2.43 PF) but significantly tightens long entry conditions.\n\n")
        
        f.write("## Overall Performance\n\n")
        f.write(f"- **Initial Capital:** ${INITIAL_CAPITAL:,.2f}\n")
        f.write(f"- **Final Equity:** ${final_equity:,.2f}\n")
        f.write(f"- **Total Return:** {total_return:.2f}%\n")
        f.write(f"- **Max Drawdown:** {max_drawdown:.2f}%\n")
        f.write(f"- **Sharpe Ratio:** {sharpe:.2f}\n\n")
        
        f.write("## Trade Statistics\n\n")
        f.write(f"- **Total Trades:** {total_trades}\n")
        f.write(f"- **Winning Trades:** {winning_trades} ({win_rate:.2f}%)\n")
        f.write(f"- **Losing Trades:** {total_trades - winning_trades}\n")
        f.write(f"- **Profit Factor:** {profit_factor:.2f}\n")
        f.write(f"- **Average Win:** ${trades_df[trades_df['Net_PnL'] > 0]['Net_PnL'].mean():.2f}\n" if winning_trades > 0 else "- **Average Win:** $0.00\n")
        f.write(f"- **Average Loss:** ${trades_df[trades_df['Net_PnL'] < 0]['Net_PnL'].mean():.2f}\n" if len(trades_df[trades_df['Net_PnL'] < 0]) > 0 else "- **Average Loss:** $0.00\n")
        f.write(f"- **Best Trade:** ${trades_df['Net_PnL'].max():.2f}\n")
        f.write(f"- **Worst Trade:** ${trades_df['Net_PnL'].min():.2f}\n\n")
        
        f.write("## Long Trades Performance\n\n")
        if len(long_trades) > 0:
            long_wins = len(long_trades[long_trades['Net_PnL'] > 0])
            long_wr = (long_wins / len(long_trades) * 100)
            long_profit = long_trades[long_trades['Net_PnL'] > 0]['Net_PnL'].sum()
            long_loss = abs(long_trades[long_trades['Net_PnL'] < 0]['Net_PnL'].sum())
            long_pf = (long_profit / long_loss) if long_loss > 0 else float('inf')
            
            f.write(f"- **Total Long Trades:** {len(long_trades)}\n")
            f.write(f"- **Long Win Rate:** {long_wr:.2f}% (Target: >40%)\n")
            f.write(f"- **Long Profit Factor:** {long_pf:.2f} (Target: >0.8)\n")
            f.write(f"- **Long Total P&L:** ${long_trades['Net_PnL'].sum():.2f}\n")
            f.write(f"- **Long Avg Win:** ${long_trades[long_trades['Net_PnL'] > 0]['Net_PnL'].mean():.2f}\n" if long_wins > 0 else "- **Long Avg Win:** $0.00\n")
            f.write(f"- **Long Avg Loss:** ${long_trades[long_trades['Net_PnL'] < 0]['Net_PnL'].mean():.2f}\n\n" if len(long_trades[long_trades['Net_PnL'] < 0]) > 0 else "- **Long Avg Loss:** $0.00\n\n")
        else:
            f.write("No long trades executed.\n\n")
        
        f.write("## Short Trades Performance\n\n")
        if len(short_trades) > 0:
            short_wins = len(short_trades[short_trades['Net_PnL'] > 0])
            short_wr = (short_wins / len(short_trades) * 100)
            short_profit = short_trades[short_trades['Net_PnL'] > 0]['Net_PnL'].sum()
            short_loss = abs(short_trades[short_trades['Net_PnL'] < 0]['Net_PnL'].sum())
            short_pf = (short_profit / short_loss) if short_loss > 0 else float('inf')
            
            f.write(f"- **Total Short Trades:** {len(short_trades)}\n")
            f.write(f"- **Short Win Rate:** {short_wr:.2f}% (V4 baseline: 58%)\n")
            f.write(f"- **Short Profit Factor:** {short_pf:.2f} (V4 baseline: 2.43)\n")
            f.write(f"- **Short Total P&L:** ${short_trades['Net_PnL'].sum():.2f}\n")
            f.write(f"- **Short Avg Win:** ${short_trades[short_trades['Net_PnL'] > 0]['Net_PnL'].mean():.2f}\n" if short_wins > 0 else "- **Short Avg Win:** $0.00\n")
            f.write(f"- **Short Avg Loss:** ${short_trades[short_trades['Net_PnL'] < 0]['Net_PnL'].mean():.2f}\n\n" if len(short_trades[short_trades['Net_PnL'] < 0]) > 0 else "- **Short Avg Loss:** $0.00\n\n")
        else:
            f.write("No short trades executed.\n\n")
        
        f.write("## Key Changes from V4\n\n")
        f.write("### Long Entry Conditions (Tightened):\n")
        f.write("1. EMA 50 > EMA 200 by at least **1.5%** (was 1.2%)\n")
        f.write("2. **NEW:** EMA 10 > EMA 30 (short-term momentum confirmation)\n")
        f.write("3. Close > EMA 50 (kept)\n")
        f.write("4. MACD histogram > 0 AND rising AND > **3** (was >2)\n")
        f.write("5. RSI between **50 and 70** (was 45-65)\n")
        f.write("6. Volume > **1.3×** Volume SMA 20 (was 1.0×)\n")
        f.write("7. **3 consecutive** closes above EMA 50 (was 2)\n")
        f.write("8. **NEW:** Close in upper 50% of Bollinger Bands\n")
        f.write("9. **NEW:** No long if Close < EMA 200\n\n")
        
        f.write("### Short Entry Conditions (Unchanged - Working Well):\n")
        f.write("Kept exactly as V4 specifications.\n\n")
        
        f.write("## Conclusion\n\n")
        
        if len(long_trades) > 0:
            long_wins = len(long_trades[long_trades['Net_PnL'] > 0])
            long_wr = (long_wins / len(long_trades) * 100)
            long_profit = long_trades[long_trades['Net_PnL'] > 0]['Net_PnL'].sum()
            long_loss = abs(long_trades[long_trades['Net_PnL'] < 0]['Net_PnL'].sum())
            long_pf = (long_profit / long_loss) if long_loss > 0 else float('inf')
            
            if long_wr >= 40 and long_pf >= 0.8:
                f.write("✅ **SUCCESS:** Long trade quality improved significantly!\n")
            elif long_wr >= 40 or long_pf >= 0.8:
                f.write("⚠️ **PARTIAL SUCCESS:** Long trades improved but need further tuning.\n")
            else:
                f.write("❌ **NEEDS IMPROVEMENT:** Long trade conditions still too loose.\n")
        else:
            f.write("⚠️ **WARNING:** No long trades generated - conditions may be too strict.\n")
        
        f.write(f"\nFinal Return: {total_return:.2f}% (Target: 35-40%)\n")
        f.write(f"Max Drawdown: {max_drawdown:.2f}% (Target: <18%)\n")
    
    print(f"  Saved STRATEGY_V5B_RESULTS.md")


if __name__ == '__main__':
    main()
