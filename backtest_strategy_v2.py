#!/usr/bin/env python3
"""
Adaptive Momentum Scalper v2 - ETHUSDT Trading Strategy Backtest
Targets 50%+ annual return with 1.0-1.2% risk per trade
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys

# ============================================================================
# INDICATOR CALCULATIONS
# ============================================================================

def calculate_ema(data, period):
    """Calculate Exponential Moving Average"""
    return data.ewm(span=period, adjust=False).mean()

def calculate_sma(data, period):
    """Calculate Simple Moving Average"""
    return data.rolling(window=period).mean()

def calculate_rsi(data, period=14):
    """Calculate Relative Strength Index"""
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_atr(high, low, close, period=14):
    """Calculate Average True Range"""
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

def calculate_macd(data, fast=8, slow=21, signal=5):
    """Calculate MACD with custom periods (8, 21, 5)"""
    ema_fast = calculate_ema(data, fast)
    ema_slow = calculate_ema(data, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calculate_bollinger_bands(data, period=20, std_dev=2.0):
    """Calculate Bollinger Bands"""
    middle = calculate_sma(data, period)
    std = data.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    return upper, middle, lower

def calculate_donchian_channel(high, low, period=20):
    """Calculate Donchian Channel"""
    upper = high.rolling(window=period).max()
    lower = low.rolling(window=period).min()
    return upper, lower

def calculate_adx(high, low, close, period=14):
    """Calculate Average Directional Index"""
    # Calculate +DM and -DM
    high_diff = high.diff()
    low_diff = -low.diff()
    
    plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0)
    minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0)
    
    # Calculate True Range
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Smooth the values
    atr = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
    
    # Calculate DX and ADX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window=period).mean()
    
    return adx

# ============================================================================
# TIME FILTERS
# ============================================================================

def get_session_multiplier(hour):
    """
    Get position size multiplier based on hour of day
    Primary session (100%): 08:00-11:00 and 13:00-17:00 UTC
    Secondary session (75%): 06:00-08:00 and 17:00-21:00 UTC
    Quiet session (50%): 00:00-06:00 and 21:00-00:00 UTC
    """
    if (8 <= hour < 11) or (13 <= hour < 17):
        return 1.0  # Primary session
    elif (6 <= hour < 8) or (17 <= hour < 21):
        return 0.75  # Secondary session
    else:
        return 0.5  # Quiet session

def should_trade_day(date):
    """Check if we should trade on this day (not Saturday/Sunday)"""
    day_of_week = date.weekday()  # Monday=0, Sunday=6
    return day_of_week < 5  # Monday-Friday only

def should_open_position(date):
    """Check if we should open new positions (not Friday after 18:00)"""
    day_of_week = date.weekday()
    hour = date.hour
    if day_of_week == 4 and hour >= 18:  # Friday after 18:00
        return False
    return should_trade_day(date)

def should_close_for_weekend(date):
    """Check if we should close all positions for weekend (Friday 20:00)"""
    day_of_week = date.weekday()
    hour = date.hour
    return day_of_week == 4 and hour >= 20  # Friday 20:00 or later

# ============================================================================
# SIGNAL GENERATION
# ============================================================================

def generate_trend_signal(row, prev_hist):
    """
    Generate trend-following signals - ULTRA-CONSERVATIVE, HIGH QUALITY ONLY
    Returns: 'LONG', 'SHORT', or None
    """
    # Require strong trend
    if row['ADX'] < 26:
        return None
    
    # EMAs must show clear direction with good separation
    ema_20_100_sep = abs(row['EMA_20'] - row['EMA_100']) / row['Close']
    ema_100_200_sep = abs(row['EMA_100'] - row['EMA_200']) / row['Close']
    
    if ema_20_100_sep < 0.010 or ema_100_200_sep < 0.008:  # Strong separation
        return None
    
    # Bollinger Band position
    bb_range = row['BB_Upper'] - row['BB_Lower']
    if bb_range == 0:
        return None
    bb_position = (row['Close'] - row['BB_Lower']) / bb_range
    
    # LONG Trend Signal - high quality
    if (row['EMA_20'] > row['EMA_100'] > row['EMA_200'] and  # Perfect cascade
        row['Close'] > row['EMA_20'] and
        row['MACD_Hist'] > 0 and
        row['MACD_Hist'] > prev_hist and
        44 < row['RSI'] < 66 and  # Sweet spot range
        row['Volume'] > 1.5 * row['Volume_SMA'] and  # Strong volume
        0.48 < bb_position < 0.78):  # Middle-upper range
        return 'LONG'
    
    # SHORT Trend Signal - high quality
    if (row['EMA_20'] < row['EMA_100'] < row['EMA_200'] and  # Perfect cascade
        row['Close'] < row['EMA_20'] and
        row['MACD_Hist'] < 0 and
        row['MACD_Hist'] < prev_hist and
        34 < row['RSI'] < 56 and  # Sweet spot range
        row['Volume'] > 1.5 * row['Volume_SMA'] and  # Strong volume
        0.22 < bb_position < 0.52):  # Middle-lower range
        return 'SHORT'
    
    return None

def generate_breakout_signal(row, prev_row):
    """
    Generate breakout signals - DISABLED (not working in this market)
    Returns: None
    """
    return None  # Disable breakouts - losing too much money

def generate_mean_reversion_signal(row, prev_hist):
    """
    Generate mean reversion signals - DISABLED (not working in this market)
    Returns: None
    """
    return None  # Disable mean reversion - losing too much money

def check_spread_filter(row):
    """Check if ATR/Close is sufficient (> 0.001)"""
    return (row['ATR'] / row['Close']) > 0.001

# ============================================================================
# POSITION CLASS
# ============================================================================

class Position:
    def __init__(self, entry_date, entry_price, position_size, direction, 
                 signal_type, stop_loss, tp1, tp2, tp3, session_type, atr):
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.position_size = position_size  # In ETH
        self.direction = direction  # 'LONG' or 'SHORT'
        self.signal_type = signal_type  # 'Trend', 'Breakout', 'MeanReversion'
        self.stop_loss = stop_loss
        self.tp1 = tp1
        self.tp2 = tp2
        self.tp3 = tp3
        self.session_type = session_type
        self.atr = atr
        
        # Track partial exits
        self.remaining_size = position_size
        self.tp1_hit = False
        self.tp2_hit = False
        self.tp3_hit = False
        self.breakeven_moved = False
        self.trailing_active = False
        self.trailing_stop = None
        
    def get_unrealized_pnl(self, current_price):
        """Calculate unrealized P&L"""
        if self.direction == 'LONG':
            pnl = (current_price - self.entry_price) * self.remaining_size
        else:
            pnl = (self.entry_price - current_price) * self.remaining_size
        return pnl
    
    def is_profitable(self, current_price):
        """Check if position is in profit"""
        return self.get_unrealized_pnl(current_price) > 0
    
    def update_stops(self, current_price, row):
        """Update stops after TP hits"""
        # Check TP1
        if not self.tp1_hit:
            if (self.direction == 'LONG' and current_price >= self.tp1) or \
               (self.direction == 'SHORT' and current_price <= self.tp1):
                self.tp1_hit = True
                self.remaining_size *= 0.6  # Close 40%, keep 60%
                self.stop_loss = self.entry_price  # Move to breakeven
                self.breakeven_moved = True
                return 0.4 * self.position_size, 'TP1'
        
        # Check TP2
        if self.tp1_hit and not self.tp2_hit:
            if (self.direction == 'LONG' and current_price >= self.tp2) or \
               (self.direction == 'SHORT' and current_price <= self.tp2):
                self.tp2_hit = True
                partial_size = 0.3 * self.position_size
                self.remaining_size -= partial_size
                self.trailing_active = True
                # Set trailing stop
                if self.direction == 'LONG':
                    self.trailing_stop = current_price - row['ATR']
                else:
                    self.trailing_stop = current_price + row['ATR']
                return partial_size, 'TP2'
        
        # Check TP3
        if self.tp2_hit and not self.tp3_hit:
            if (self.direction == 'LONG' and current_price >= self.tp3) or \
               (self.direction == 'SHORT' and current_price <= self.tp3):
                self.tp3_hit = True
                return self.remaining_size, 'TP3'
        
        # Update trailing stop after TP2
        if self.trailing_active:
            if self.direction == 'LONG':
                new_trail = current_price - row['ATR']
                if new_trail > self.trailing_stop:
                    self.trailing_stop = new_trail
            else:
                new_trail = current_price + row['ATR']
                if new_trail < self.trailing_stop:
                    self.trailing_stop = new_trail
        
        return None, None
    
    def check_exit(self, current_price, row, candles_held):
        """Check if any exit condition is met"""
        # Stop Loss
        if self.direction == 'LONG' and current_price <= self.stop_loss:
            return True, 'StopLoss'
        if self.direction == 'SHORT' and current_price >= self.stop_loss:
            return True, 'StopLoss'
        
        # Trailing Stop
        if self.trailing_active and self.trailing_stop:
            if self.direction == 'LONG' and current_price <= self.trailing_stop:
                return True, 'TrailingStop'
            if self.direction == 'SHORT' and current_price >= self.trailing_stop:
                return True, 'TrailingStop'
        
        # RSI extreme exit
        if self.direction == 'LONG' and row['RSI'] > 80:
            return True, 'RSI_Extreme'
        if self.direction == 'SHORT' and row['RSI'] < 20:
            return True, 'RSI_Extreme'
        
        # Time-based exit (48 hours = 192 candles without TP1)
        if not self.tp1_hit and candles_held >= 192:
            return True, 'TimeExit_48h'
        
        return False, None

# ============================================================================
# BACKTEST ENGINE
# ============================================================================

def run_backtest(df, initial_capital=100000):
    """Run the complete backtest"""
    
    capital = initial_capital
    positions = []  # Active positions
    trades = []  # Completed trades
    equity_curve = []
    
    # Track daily/weekly losses
    daily_loss = {}
    weekly_loss = {}
    
    trade_count = 0
    
    print("Starting backtest...")
    print(f"Initial Capital: ${capital:,.2f}")
    print(f"Data points: {len(df)}")
    print("-" * 80)
    
    for i in range(250, len(df)):  # Start after warm-up period
        row = df.iloc[i]
        date = row['DateTime']
        current_price = row['Close']
        
        # Track equity
        total_equity = capital
        for pos in positions:
            total_equity += pos.get_unrealized_pnl(current_price)
        
        equity_curve.append({
            'DateTime': date,
            'Equity': total_equity
        })
        
        # Get day and week keys
        day_key = date.date()
        week_key = date.isocalendar()[:2]  # (year, week)
        
        # Check daily/weekly loss limits
        current_day_loss = daily_loss.get(day_key, 0)
        current_week_loss = weekly_loss.get(week_key, 0)
        
        paused_day = current_day_loss <= -0.03 * initial_capital
        paused_week = current_week_loss <= -0.06 * initial_capital
        
        # Friday weekend close
        if should_close_for_weekend(date) and positions:
            for pos in positions[:]:
                exit_price = current_price
                pnl = pos.get_unrealized_pnl(exit_price)
                commission = 0.0005 * (pos.entry_price * pos.position_size + 
                                      exit_price * pos.remaining_size)
                net_pnl = pnl - commission
                
                capital += net_pnl
                
                # Track losses
                if net_pnl < 0:
                    daily_loss[day_key] = daily_loss.get(day_key, 0) + net_pnl
                    weekly_loss[week_key] = weekly_loss.get(week_key, 0) + net_pnl
                
                trade_count += 1
                trades.append({
                    'Trade': trade_count,
                    'SignalType': pos.signal_type,
                    'Type': pos.direction,
                    'EntryDate': pos.entry_date,
                    'EntryPrice': pos.entry_price,
                    'ExitDate': date,
                    'ExitPrice': exit_price,
                    'PositionSize': pos.position_size,
                    'PnL_USDT': pnl,
                    'PnL_Percent': (pnl / (pos.entry_price * pos.position_size)) * 100,
                    'Commission': commission,
                    'NetPnL': net_pnl,
                    'SessionType': pos.session_type,
                    'ExitReason': 'FridayClose'
                })
                
                positions.remove(pos)
        
        # Process existing positions
        for pos in positions[:]:
            candles_held = i - df.index[df['DateTime'] == pos.entry_date].tolist()[0]
            
            # Check for partial exits
            partial_exit, exit_reason = pos.update_stops(current_price, row)
            if partial_exit:
                pnl = (current_price - pos.entry_price) * partial_exit if pos.direction == 'LONG' else (pos.entry_price - current_price) * partial_exit
                commission = 0.0005 * current_price * partial_exit
                net_pnl = pnl - commission
                capital += net_pnl
                
                # Track losses
                if net_pnl < 0:
                    daily_loss[day_key] = daily_loss.get(day_key, 0) + net_pnl
                    weekly_loss[week_key] = weekly_loss.get(week_key, 0) + net_pnl
            
            # Check for full exit
            should_exit, exit_reason = pos.check_exit(current_price, row, candles_held)
            
            # Check for counter-signal
            if not should_exit:
                prev_hist = df.iloc[i-1]['MACD_Hist'] if i > 0 else 0
                trend_signal = generate_trend_signal(row, prev_hist)
                if trend_signal and trend_signal != pos.direction:
                    should_exit = True
                    exit_reason = 'CounterSignal'
            
            if should_exit:
                exit_price = current_price
                pnl = pos.get_unrealized_pnl(exit_price)
                commission = 0.0005 * (pos.entry_price * pos.position_size + 
                                      exit_price * pos.remaining_size)
                net_pnl = pnl - commission
                
                capital += net_pnl
                
                # Track losses
                if net_pnl < 0:
                    daily_loss[day_key] = daily_loss.get(day_key, 0) + net_pnl
                    weekly_loss[week_key] = weekly_loss.get(week_key, 0) + net_pnl
                
                trade_count += 1
                trades.append({
                    'Trade': trade_count,
                    'SignalType': pos.signal_type,
                    'Type': pos.direction,
                    'EntryDate': pos.entry_date,
                    'EntryPrice': pos.entry_price,
                    'ExitDate': date,
                    'ExitPrice': exit_price,
                    'PositionSize': pos.position_size,
                    'PnL_USDT': pnl,
                    'PnL_Percent': (pnl / (pos.entry_price * pos.position_size)) * 100,
                    'Commission': commission,
                    'NetPnL': net_pnl,
                    'SessionType': pos.session_type,
                    'ExitReason': exit_reason
                })
                
                positions.remove(pos)
        
        # Check for new signals (if not paused and can open positions)
        if not paused_day and not paused_week and should_open_position(date) and \
           len(positions) < 2 and check_spread_filter(row):
            
            prev_hist = df.iloc[i-1]['MACD_Hist'] if i > 0 else 0
            prev_row = df.iloc[i-1] if i > 0 else None
            
            # Try each signal type - ONLY TREND SIGNALS (others disabled)
            signal = None
            signal_type = None
            risk_percent = None
            
            # Trend signal ONLY (1.2% risk as per requirements)
            trend_signal = generate_trend_signal(row, prev_hist)
            if trend_signal:
                signal = trend_signal
                signal_type = 'Trend'
                risk_percent = 0.012
            
            # If signal found, check pyramiding rules
            if signal:
                can_open = True
                
                # Pyramiding: can add 2nd position if existing is profitable and same direction
                if len(positions) == 1:
                    existing_pos = positions[0]
                    if existing_pos.direction == signal:
                        if not existing_pos.is_profitable(current_price):
                            can_open = False
                        else:
                            # Second position uses 50% size
                            risk_percent *= 0.5
                    else:
                        # Different direction - don't open
                        can_open = False
                
                if can_open:
                    # Calculate position size
                    hour = date.hour
                    session_multiplier = get_session_multiplier(hour)
                    
                    # Determine session type for logging
                    if session_multiplier == 1.0:
                        session_type = 'Primary'
                    elif session_multiplier == 0.75:
                        session_type = 'Secondary'
                    else:
                        session_type = 'Quiet'
                    
                    base_risk_usdt = capital * risk_percent
                    adjusted_risk = base_risk_usdt * session_multiplier
                    sl_distance = 0.7 * row['ATR']  # Match tighter SL
                    position_size = adjusted_risk / sl_distance
                    
                    # Calculate SL and TP levels - tight stops, reasonable targets
                    if signal == 'LONG':
                        stop_loss = current_price - 0.7 * row['ATR']  # Tighter SL
                        tp1 = current_price + 1.8 * row['ATR']  # 2.57:1 R:R
                        tp2 = current_price + 3.2 * row['ATR']  # 4.57:1 R:R
                        tp3 = current_price + 5.0 * row['ATR']  # 7.14:1 R:R
                    else:  # SHORT
                        stop_loss = current_price + 0.7 * row['ATR']
                        tp1 = current_price - 1.8 * row['ATR']
                        tp2 = current_price - 3.2 * row['ATR']
                        tp3 = current_price - 5.0 * row['ATR']
                    
                    # Entry commission
                    entry_commission = 0.0005 * current_price * position_size
                    capital -= entry_commission
                    
                    # Create position
                    pos = Position(
                        entry_date=date,
                        entry_price=current_price,
                        position_size=position_size,
                        direction=signal,
                        signal_type=signal_type,
                        stop_loss=stop_loss,
                        tp1=tp1,
                        tp2=tp2,
                        tp3=tp3,
                        session_type=session_type,
                        atr=row['ATR']
                    )
                    positions.append(pos)
    
    # Close any remaining positions at end
    if positions:
        final_row = df.iloc[-1]
        final_price = final_row['Close']
        final_date = final_row['DateTime']
        
        for pos in positions:
            pnl = pos.get_unrealized_pnl(final_price)
            commission = 0.0005 * (pos.entry_price * pos.position_size + 
                                  final_price * pos.remaining_size)
            net_pnl = pnl - commission
            
            capital += net_pnl
            
            trade_count += 1
            trades.append({
                'Trade': trade_count,
                'SignalType': pos.signal_type,
                'Type': pos.direction,
                'EntryDate': pos.entry_date,
                'EntryPrice': pos.entry_price,
                'ExitDate': final_date,
                'ExitPrice': final_price,
                'PositionSize': pos.position_size,
                'PnL_USDT': pnl,
                'PnL_Percent': (pnl / (pos.entry_price * pos.position_size)) * 100,
                'Commission': commission,
                'NetPnL': net_pnl,
                'SessionType': pos.session_type,
                'ExitReason': 'EndOfBacktest'
            })
    
    return trades, equity_curve, capital

# ============================================================================
# PERFORMANCE METRICS
# ============================================================================

def calculate_metrics(trades, equity_curve, initial_capital, final_capital):
    """Calculate comprehensive performance metrics"""
    
    if not trades:
        print("No trades executed!")
        return {}
    
    df_trades = pd.DataFrame(trades)
    df_equity = pd.DataFrame(equity_curve)
    
    # Basic metrics
    total_trades = len(df_trades)
    winning_trades = len(df_trades[df_trades['NetPnL'] > 0])
    losing_trades = len(df_trades[df_trades['NetPnL'] <= 0])
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
    
    total_return_usdt = final_capital - initial_capital
    total_return_pct = (total_return_usdt / initial_capital) * 100
    
    # Drawdown
    df_equity['Peak'] = df_equity['Equity'].cummax()
    df_equity['Drawdown'] = df_equity['Equity'] - df_equity['Peak']
    df_equity['DrawdownPercent'] = (df_equity['Drawdown'] / df_equity['Peak']) * 100
    max_drawdown_pct = df_equity['DrawdownPercent'].min()
    max_drawdown_usdt = df_equity['Drawdown'].min()
    
    # Profit factor
    gross_profit = df_trades[df_trades['NetPnL'] > 0]['NetPnL'].sum()
    gross_loss = abs(df_trades[df_trades['NetPnL'] <= 0]['NetPnL'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Sharpe ratio (annualized)
    df_equity['Returns'] = df_equity['Equity'].pct_change()
    avg_return = df_equity['Returns'].mean()
    std_return = df_equity['Returns'].std()
    # Theoretical periods per year for 15-min candles: 4 per hour * 24 * 365 = 35,040
    # Note: Using theoretical count for standardized annualization
    periods_per_year = 35040
    sharpe_ratio = (avg_return / std_return) * np.sqrt(periods_per_year) if std_return > 0 else 0
    
    # Average trade duration
    df_trades['Duration'] = (pd.to_datetime(df_trades['ExitDate']) - 
                             pd.to_datetime(df_trades['EntryDate'])).dt.total_seconds() / 3600  # hours
    avg_duration = df_trades['Duration'].mean()
    
    # Best/worst trades
    best_trade = df_trades.loc[df_trades['NetPnL'].idxmax()]
    worst_trade = df_trades.loc[df_trades['NetPnL'].idxmin()]
    
    # By signal type
    signal_type_stats = df_trades.groupby('SignalType').agg({
        'NetPnL': ['count', 'sum'],
        'Trade': ['count']  # dummy for wins calculation
    })
    
    # Calculate wins separately
    wins_by_type = df_trades[df_trades['NetPnL'] > 0].groupby('SignalType').size()
    
    # Long vs Short
    long_trades = df_trades[df_trades['Type'] == 'LONG']
    short_trades = df_trades[df_trades['Type'] == 'SHORT']
    
    # Monthly breakdown
    df_trades['Month'] = pd.to_datetime(df_trades['ExitDate']).dt.to_period('M')
    monthly_pnl = df_trades.groupby('Month')['NetPnL'].sum()
    
    # Trading hours analysis
    df_trades['Hour'] = pd.to_datetime(df_trades['EntryDate']).dt.hour
    hourly_pnl = df_trades.groupby('Hour')['NetPnL'].sum().sort_values(ascending=False)
    
    # Day of week analysis
    df_trades['DayOfWeek'] = pd.to_datetime(df_trades['EntryDate']).dt.day_name()
    daily_pnl = df_trades.groupby('DayOfWeek')['NetPnL'].sum().sort_values(ascending=False)
    
    metrics = {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'total_return_usdt': total_return_usdt,
        'total_return_pct': total_return_pct,
        'max_drawdown_pct': max_drawdown_pct,
        'max_drawdown_usdt': max_drawdown_usdt,
        'profit_factor': profit_factor,
        'sharpe_ratio': sharpe_ratio,
        'avg_duration': avg_duration,
        'best_trade': best_trade,
        'worst_trade': worst_trade,
        'long_trades': long_trades,
        'short_trades': short_trades,
        'signal_type_stats': signal_type_stats,
        'wins_by_type': wins_by_type,
        'monthly_pnl': monthly_pnl,
        'hourly_pnl': hourly_pnl,
        'daily_pnl': daily_pnl,
        'final_capital': final_capital
    }
    
    return metrics

def print_results(metrics):
    """Print comprehensive results"""
    
    print("\n" + "=" * 80)
    print("BACKTEST RESULTS - ADAPTIVE MOMENTUM SCALPER V2")
    print("=" * 80)
    
    print(f"\n{'OVERALL PERFORMANCE':^80}")
    print("-" * 80)
    print(f"Total Trades: {metrics['total_trades']}")
    print(f"Winning Trades: {metrics['winning_trades']} ({metrics['win_rate']:.2f}%)")
    print(f"Losing Trades: {metrics['losing_trades']}")
    print(f"Total Return: ${metrics['total_return_usdt']:,.2f} ({metrics['total_return_pct']:.2f}%)")
    print(f"Final Capital: ${metrics['final_capital']:,.2f}")
    print(f"Max Drawdown: {metrics['max_drawdown_pct']:.2f}% (${metrics['max_drawdown_usdt']:,.2f})")
    print(f"Profit Factor: {metrics['profit_factor']:.2f}")
    print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"Average Trade Duration: {metrics['avg_duration']:.2f} hours")
    
    print(f"\n{'BEST/WORST TRADES':^80}")
    print("-" * 80)
    best = metrics['best_trade']
    print(f"Best Trade: ${best['NetPnL']:,.2f} ({best['Type']} {best['SignalType']} on {best['EntryDate']})")
    worst = metrics['worst_trade']
    print(f"Worst Trade: ${worst['NetPnL']:,.2f} ({worst['Type']} {worst['SignalType']} on {worst['EntryDate']})")
    
    print(f"\n{'LONG VS SHORT':^80}")
    print("-" * 80)
    long_count = len(metrics['long_trades'])
    long_pnl = metrics['long_trades']['NetPnL'].sum()
    long_win = len(metrics['long_trades'][metrics['long_trades']['NetPnL'] > 0])
    long_winrate = (long_win / long_count * 100) if long_count > 0 else 0
    
    short_count = len(metrics['short_trades'])
    short_pnl = metrics['short_trades']['NetPnL'].sum()
    short_win = len(metrics['short_trades'][metrics['short_trades']['NetPnL'] > 0])
    short_winrate = (short_win / short_count * 100) if short_count > 0 else 0
    
    print(f"LONG: {long_count} trades, ${long_pnl:,.2f} PnL, {long_winrate:.2f}% win rate")
    print(f"SHORT: {short_count} trades, ${short_pnl:,.2f} PnL, {short_winrate:.2f}% win rate")
    
    print(f"\n{'BY SIGNAL TYPE':^80}")
    print("-" * 80)
    for signal_type in ['Trend', 'Breakout', 'MeanReversion']:
        if signal_type in metrics['signal_type_stats'].index:
            stats = metrics['signal_type_stats'].loc[signal_type]
            count = int(stats['NetPnL']['count'])
            total_pnl = stats['NetPnL']['sum']
            wins = int(metrics['wins_by_type'].get(signal_type, 0))
            winrate = (wins / count * 100) if count > 0 else 0
            print(f"{signal_type}: {count} trades, ${total_pnl:,.2f} PnL, {winrate:.2f}% win rate")
    
    print(f"\n{'MONTHLY BREAKDOWN':^80}")
    print("-" * 80)
    for month, pnl in metrics['monthly_pnl'].items():
        print(f"{month}: ${pnl:,.2f}")
    
    print(f"\n{'TOP 5 PROFITABLE HOURS (UTC)':^80}")
    print("-" * 80)
    for hour, pnl in metrics['hourly_pnl'].head(5).items():
        print(f"Hour {hour:02d}:00: ${pnl:,.2f}")
    
    print(f"\n{'DAY OF WEEK ANALYSIS':^80}")
    print("-" * 80)
    for day, pnl in metrics['daily_pnl'].items():
        print(f"{day}: ${pnl:,.2f}")
    
    print("\n" + "=" * 80)

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("Loading data...")
    
    # Load data
    df = pd.read_csv('ETHUSDT_15_Minutes_year_2025.txt', 
                     names=['Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume'],
                     skiprows=1)
    
    # Combine date and time
    df['DateTime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'], 
                                     format='%m/%d/%Y %H:%M:%S')
    
    # Convert to numeric
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        df[col] = pd.to_numeric(df[col])
    
    print(f"Loaded {len(df)} candles")
    print(f"Date range: {df['DateTime'].min()} to {df['DateTime'].max()}")
    
    # Calculate indicators
    print("\nCalculating indicators...")
    df['EMA_20'] = calculate_ema(df['Close'], 20)
    df['EMA_100'] = calculate_ema(df['Close'], 100)
    df['EMA_200'] = calculate_ema(df['Close'], 200)
    df['RSI'] = calculate_rsi(df['Close'], 14)
    df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
    
    macd_line, signal_line, histogram = calculate_macd(df['Close'], 8, 21, 5)
    df['MACD_Line'] = macd_line
    df['MACD_Signal'] = signal_line
    df['MACD_Hist'] = histogram
    
    df['Volume_SMA'] = calculate_sma(df['Volume'], 20)
    
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(df['Close'], 20, 2.0)
    df['BB_Upper'] = bb_upper
    df['BB_Middle'] = bb_middle
    df['BB_Lower'] = bb_lower
    
    donchian_upper, donchian_lower = calculate_donchian_channel(df['High'], df['Low'], 20)
    df['Donchian_Upper'] = donchian_upper
    df['Donchian_Lower'] = donchian_lower
    
    df['ADX'] = calculate_adx(df['High'], df['Low'], df['Close'], 14)
    
    # Run backtest
    print("\nRunning backtest...")
    initial_capital = 100000
    trades, equity_curve, final_capital = run_backtest(df, initial_capital)
    
    # Calculate metrics
    print("\nCalculating metrics...")
    metrics = calculate_metrics(trades, equity_curve, initial_capital, final_capital)
    
    # Print results
    print_results(metrics)
    
    # Save outputs
    print("\nSaving outputs...")
    
    # Trade log
    if trades:
        df_trades = pd.DataFrame(trades)
        df_trades.to_csv('trade_log_v2.csv', index=False)
        print(f"Saved trade_log_v2.csv ({len(trades)} trades)")
    
    # Equity curve
    if equity_curve:
        df_equity = pd.DataFrame(equity_curve)
        df_equity['Peak'] = df_equity['Equity'].cummax()
        df_equity['DrawdownPercent'] = ((df_equity['Equity'] - df_equity['Peak']) / df_equity['Peak']) * 100
        df_equity[['DateTime', 'Equity', 'DrawdownPercent']].to_csv('equity_curve_v2.csv', index=False)
        print(f"Saved equity_curve_v2.csv ({len(equity_curve)} data points)")
    
    print("\nBacktest complete!")
    
    return metrics

if __name__ == "__main__":
    main()
