#!/usr/bin/env python3
"""
Backtest Strategy V5A - Short-Only "Panic Catcher"
Based on V4 shorts which had 58.33% WR and 2.43 PF
Only takes short positions to maximize profitable setups
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import csv

# ============================================================================
# CONFIGURATION
# ============================================================================
INITIAL_CAPITAL = 100000.0
RISK_PER_TRADE = 0.02  # 2% of capital per trade
COMMISSION = 0.0005  # 0.05% per side
MAX_POSITIONS = 2  # Max simultaneous short positions
MAX_DAILY_LOSS = 0.03  # 3% max daily loss
MAX_WEEKLY_LOSS = 0.05  # 5% max weekly loss
MAX_TRADE_DURATION = 48  # 48 candles = 12 hours

# Risk parameters
STOP_LOSS_ATR_MULT = 0.7
TP1_ATR_MULT = 1.5
TP2_ATR_MULT = 3.0
TP3_ATR_MULT = 5.0
TRAILING_STOP_ATR_MULT = 0.6

# Partial close percentages
TP1_CLOSE_PCT = 0.50  # Close 50% at TP1
TP2_CLOSE_PCT = 0.30  # Close 30% at TP2
TP3_CLOSE_PCT = 0.20  # Close 20% at TP3

# Time-based position sizing multipliers
HOUR_MULTIPLIERS = {
    range(8, 11): 1.0,    # 08:00-11:00 UTC → 100%
    range(13, 17): 1.0,   # 13:00-17:00 UTC → 100%
    range(17, 21): 0.8,   # 17:00-21:00 UTC → 80%
    range(21, 24): 0.6,   # 21:00-02:00 UTC → 60%
    range(0, 2): 0.6,     # 21:00-02:00 UTC → 60%
    range(2, 8): 0.4,     # 02:00-08:00 UTC → 40%
}

# Indicator parameters
EMA_FAST = 10
EMA_MEDIUM = 30
RSI_PERIOD = 14
ATR_PERIOD = 14
MACD_FAST = 8
MACD_SLOW = 17
MACD_SIGNAL = 5
VOLUME_SMA = 20
BB_PERIOD = 20
BB_STD = 2.0

# Entry conditions
RSI_MIN = 28
RSI_MAX = 47
VOLUME_MULT = 1.9
PRICE_DROP_THRESHOLD = 0.006  # 0.6%
MIN_ATR_RATIO = 0.005  # 0.5%

# ============================================================================
# TECHNICAL INDICATORS
# ============================================================================

def calculate_ema(data, period):
    """Calculate Exponential Moving Average"""
    return data.ewm(span=period, adjust=False).mean()

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
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

def calculate_macd(data, fast=12, slow=26, signal=9):
    """Calculate MACD"""
    ema_fast = data.ewm(span=fast, adjust=False).mean()
    ema_slow = data.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calculate_bollinger_bands(data, period=20, std_dev=2.0):
    """Calculate Bollinger Bands"""
    sma = data.rolling(window=period).mean()
    std = data.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return upper, sma, lower

# ============================================================================
# TIME FILTERS
# ============================================================================

def get_hour_multiplier(hour):
    """Get position size multiplier based on hour"""
    for hour_range, mult in HOUR_MULTIPLIERS.items():
        if hour in hour_range:
            return mult
    return 0.4  # Default to lowest multiplier

def is_trading_allowed(timestamp):
    """Check if trading is allowed at this time"""
    weekday = timestamp.weekday()  # 0=Monday, 6=Sunday
    hour = timestamp.hour
    
    # No trading on weekends
    if weekday in [5, 6]:  # Saturday, Sunday
        return False
    
    # No new positions Friday after 18:00 UTC
    if weekday == 4 and hour >= 18:
        return False
    
    return True

def should_close_for_weekend(timestamp):
    """Check if positions should be closed for weekend"""
    weekday = timestamp.weekday()
    hour = timestamp.hour
    
    # Close all positions by Friday 20:00 UTC
    if weekday == 4 and hour >= 20:
        return True
    
    return False

# ============================================================================
# POSITION MANAGEMENT
# ============================================================================

class Position:
    """Track individual short position"""
    def __init__(self, entry_price, entry_time, size, stop_loss, tp1, tp2, tp3, entry_idx):
        self.entry_price = entry_price
        self.entry_time = entry_time
        self.size = size
        self.original_size = size
        self.stop_loss = stop_loss
        self.tp1 = tp1
        self.tp2 = tp2
        self.tp3 = tp3
        self.entry_idx = entry_idx
        self.trailing_stop = None
        self.tp1_hit = False
        self.tp2_hit = False
        self.breakeven_moved = False
        self.remaining_pct = 1.0
    
    def update_trailing_stop(self, current_price, atr):
        """Update trailing stop after TP2"""
        if self.tp2_hit and self.trailing_stop is None:
            self.trailing_stop = current_price + (TRAILING_STOP_ATR_MULT * atr)
        elif self.trailing_stop is not None:
            # Trail the stop up as price moves down (for shorts)
            new_trailing = current_price + (TRAILING_STOP_ATR_MULT * atr)
            if new_trailing < self.trailing_stop:
                self.trailing_stop = new_trailing

# ============================================================================
# BACKTEST ENGINE
# ============================================================================

def load_data(filename):
    """Load and prepare market data"""
    df = pd.read_csv(filename, skiprows=1, 
                     names=['Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume'])
    
    # Combine date and time
    df['Timestamp'] = pd.to_datetime(df['Date'] + ' ' + df['Time'])
    
    # Convert to numeric
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        df[col] = pd.to_numeric(df[col])
    
    df = df.sort_values('Timestamp').reset_index(drop=True)
    return df

def calculate_indicators(df):
    """Calculate all technical indicators"""
    # EMAs
    df['EMA_10'] = calculate_ema(df['Close'], EMA_FAST)
    df['EMA_30'] = calculate_ema(df['Close'], EMA_MEDIUM)
    
    # RSI
    df['RSI'] = calculate_rsi(df['Close'], RSI_PERIOD)
    
    # ATR
    df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], ATR_PERIOD)
    
    # Fast MACD (8, 17, 5)
    macd_line, signal_line, histogram = calculate_macd(df['Close'], MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    df['MACD_Line'] = macd_line
    df['MACD_Signal'] = signal_line
    df['MACD_Hist'] = histogram
    
    # Volume SMA
    df['Volume_SMA'] = df['Volume'].rolling(window=VOLUME_SMA).mean()
    
    # Bollinger Bands
    bb_upper, bb_mid, bb_lower = calculate_bollinger_bands(df['Close'], BB_PERIOD, BB_STD)
    df['BB_Upper'] = bb_upper
    df['BB_Mid'] = bb_mid
    df['BB_Lower'] = bb_lower
    
    # Price change percentage
    df['Price_Change_Pct'] = df['Close'].pct_change()
    
    # Previous histogram for declining check
    df['MACD_Hist_Prev'] = df['MACD_Hist'].shift(1)
    
    return df

def check_short_entry(row, prev_row):
    """Check if all SHORT entry conditions are met"""
    # 1. EMA 10 < EMA 30 (fast bearish cross)
    if row['EMA_10'] >= row['EMA_30']:
        return False, "EMA not bearish"
    
    # 2. Close < EMA 10
    if row['Close'] >= row['EMA_10']:
        return False, "Price not below EMA10"
    
    # 3. Fast MACD histogram < 0 AND declining
    if row['MACD_Hist'] >= 0:
        return False, "MACD not negative"
    
    if pd.isna(row['MACD_Hist_Prev']) or row['MACD_Hist'] >= row['MACD_Hist_Prev']:
        return False, "MACD not declining"
    
    # 4. RSI between 28 and 47
    if row['RSI'] < RSI_MIN or row['RSI'] > RSI_MAX:
        return False, f"RSI {row['RSI']:.1f} not in range"
    
    # 5. Volume > 1.9 × Volume SMA
    if pd.isna(row['Volume_SMA']) or row['Volume'] <= VOLUME_MULT * row['Volume_SMA']:
        return False, "Volume not elevated"
    
    # 6. Close < Lower BB OR price dropped > 0.6%
    bb_condition = row['Close'] < row['BB_Lower']
    drop_condition = row['Price_Change_Pct'] < -PRICE_DROP_THRESHOLD
    
    if not (bb_condition or drop_condition):
        return False, "No breakdown momentum"
    
    # ATR filter - skip if volatility too low
    atr_ratio = row['ATR'] / row['Close']
    if atr_ratio < MIN_ATR_RATIO:
        return False, f"ATR too low {atr_ratio:.4f}"
    
    return True, "All conditions met"

def calculate_position_size(capital, entry_price, stop_loss, hour_mult):
    """Calculate position size based on risk and time"""
    risk_amount = capital * RISK_PER_TRADE * hour_mult
    price_risk = abs(entry_price - stop_loss)
    
    if price_risk <= 0:
        return 0
    
    # Position size in USDT
    position_size = risk_amount / price_risk
    
    # Don't exceed 10% of capital in single position
    max_size = capital * 0.10
    position_size = min(position_size, max_size)
    
    return position_size

def run_backtest(df):
    """Execute the backtest"""
    capital = INITIAL_CAPITAL
    equity_curve = [INITIAL_CAPITAL]
    trades = []
    positions = []
    
    # Track daily and weekly performance
    daily_start_capital = capital
    weekly_start_capital = capital
    current_date = None
    current_week = None
    daily_paused = False
    weekly_paused = False
    
    print(f"\n{'='*80}")
    print(f"BACKTEST V5A - SHORT ONLY STRATEGY")
    print(f"{'='*80}")
    print(f"Initial Capital: ${INITIAL_CAPITAL:,.2f}")
    print(f"Data Period: {df['Timestamp'].iloc[0]} to {df['Timestamp'].iloc[-1]}")
    print(f"Total Candles: {len(df)}")
    print(f"\nStarting backtest...\n")
    
    for idx, row in df.iterrows():
        timestamp = row['Timestamp']
        
        # Reset daily pause at start of new day
        if current_date != timestamp.date():
            current_date = timestamp.date()
            daily_start_capital = capital
            daily_paused = False
        
        # Reset weekly pause at start of new week
        week_num = timestamp.isocalendar()[1]
        if current_week != week_num:
            if timestamp.weekday() == 0:  # Monday
                current_week = week_num
                weekly_start_capital = capital
                weekly_paused = False
        
        # Check daily loss limit
        if not daily_paused and capital < daily_start_capital * (1 - MAX_DAILY_LOSS):
            daily_paused = True
            print(f"[{timestamp}] Daily loss limit hit. Pausing trading for rest of day.")
        
        # Check weekly loss limit
        if not weekly_paused and capital < weekly_start_capital * (1 - MAX_WEEKLY_LOSS):
            weekly_paused = True
            print(f"[{timestamp}] Weekly loss limit hit. Pausing until Monday.")
        
        # Manage existing positions
        positions_to_remove = []
        for pos in positions:
            current_high = row['High']
            current_low = row['Low']
            current_close = row['Close']
            current_atr = row['ATR']
            current_rsi = row['RSI']
            candles_held = idx - pos.entry_idx
            
            exit_price = None
            exit_reason = None
            exit_size = 0
            
            # Check stop loss (price moved UP against short)
            if current_high >= pos.stop_loss:
                exit_price = pos.stop_loss
                exit_reason = "Stop Loss"
                exit_size = pos.size
                
            # Check trailing stop
            elif pos.trailing_stop is not None and current_high >= pos.trailing_stop:
                exit_price = pos.trailing_stop
                exit_reason = "Trailing Stop"
                exit_size = pos.size
                
            # Check TP levels (price moved DOWN for short profit)
            elif not pos.tp1_hit and current_low <= pos.tp1:
                exit_price = pos.tp1
                exit_reason = "TP1"
                exit_size = pos.size * TP1_CLOSE_PCT
                pos.tp1_hit = True
                pos.remaining_pct -= TP1_CLOSE_PCT
                pos.size -= exit_size
                
                # Move stop to breakeven
                if not pos.breakeven_moved:
                    pos.stop_loss = pos.entry_price
                    pos.breakeven_moved = True
                
            elif pos.tp1_hit and not pos.tp2_hit and current_low <= pos.tp2:
                exit_price = pos.tp2
                exit_reason = "TP2"
                exit_size = pos.original_size * TP2_CLOSE_PCT
                pos.tp2_hit = True
                pos.remaining_pct -= TP2_CLOSE_PCT
                pos.size -= exit_size
                
                # Activate trailing stop
                pos.update_trailing_stop(current_close, current_atr)
                
            elif pos.tp2_hit and current_low <= pos.tp3:
                exit_price = pos.tp3
                exit_reason = "TP3"
                exit_size = pos.size
                
            # RSI extreme oversold - potential bounce coming
            elif current_rsi < 15:
                exit_price = current_close
                exit_reason = "RSI Extreme (<15)"
                exit_size = pos.size
                
            # Time-based exit
            elif candles_held >= MAX_TRADE_DURATION and not pos.tp1_hit:
                exit_price = current_close
                exit_reason = f"Time Limit ({MAX_TRADE_DURATION} candles)"
                exit_size = pos.size
                
            # Friday close
            elif should_close_for_weekend(timestamp):
                exit_price = current_close
                exit_reason = "Friday Close (20:00 UTC)"
                exit_size = pos.size
            
            # Update trailing stop if active
            if pos.tp2_hit and pos.trailing_stop is not None:
                pos.update_trailing_stop(current_close, current_atr)
            
            # Execute exit if triggered
            if exit_price is not None:
                # For shorts: profit when exit price < entry price
                gross_pnl = (pos.entry_price - exit_price) * exit_size / pos.entry_price
                commission_cost = exit_size * COMMISSION * 2  # Entry + exit
                net_pnl = gross_pnl - commission_cost
                
                capital += net_pnl
                
                # Log trade
                trades.append({
                    'Entry_Time': pos.entry_time,
                    'Exit_Time': timestamp,
                    'Direction': 'SHORT',
                    'Entry_Price': pos.entry_price,
                    'Exit_Price': exit_price,
                    'Size': exit_size,
                    'Gross_PnL': gross_pnl,
                    'Commission': commission_cost,
                    'Net_PnL': net_pnl,
                    'Exit_Reason': exit_reason,
                    'Candles_Held': candles_held,
                    'Partial': 'Yes' if exit_size < pos.original_size else 'No'
                })
                
                # Remove position if fully closed
                if exit_size >= pos.size or exit_reason in ["Stop Loss", "TP3", "Time Limit", "Friday Close", "RSI Extreme (<15)"]:
                    positions_to_remove.append(pos)
        
        # Remove closed positions
        for pos in positions_to_remove:
            positions.remove(pos)
        
        # Entry logic - only if trading allowed and not paused
        if (not daily_paused and not weekly_paused and 
            is_trading_allowed(timestamp) and 
            len(positions) < MAX_POSITIONS and
            idx > 50):  # Need indicators to warm up
            
            prev_row = df.iloc[idx-1]
            entry_signal, reason = check_short_entry(row, prev_row)
            
            if entry_signal:
                entry_price = row['Close']
                atr = row['ATR']
                hour_mult = get_hour_multiplier(timestamp.hour)
                
                # Calculate position levels
                stop_loss = entry_price + (STOP_LOSS_ATR_MULT * atr)
                tp1 = entry_price - (TP1_ATR_MULT * atr)
                tp2 = entry_price - (TP2_ATR_MULT * atr)
                tp3 = entry_price - (TP3_ATR_MULT * atr)
                
                # Calculate position size
                position_size = calculate_position_size(capital, entry_price, stop_loss, hour_mult)
                
                if position_size > 0:
                    # Deduct entry commission
                    entry_commission = position_size * COMMISSION
                    capital -= entry_commission
                    
                    # Create position
                    pos = Position(entry_price, timestamp, position_size, stop_loss, 
                                 tp1, tp2, tp3, idx)
                    positions.append(pos)
                    
                    print(f"[{timestamp}] SHORT ENTRY #{len(trades)+1}: "
                          f"Price=${entry_price:.2f}, Size=${position_size:.2f} ({hour_mult*100:.0f}%), "
                          f"SL=${stop_loss:.2f}, TP1=${tp1:.2f}")
        
        # Track equity
        equity_curve.append(capital)
    
    # Close any remaining positions at end of data
    for pos in positions:
        final_price = df.iloc[-1]['Close']
        final_time = df.iloc[-1]['Timestamp']
        
        gross_pnl = (pos.entry_price - final_price) * pos.size / pos.entry_price
        commission_cost = pos.size * COMMISSION * 2
        net_pnl = gross_pnl - commission_cost
        
        capital += net_pnl
        
        trades.append({
            'Entry_Time': pos.entry_time,
            'Exit_Time': final_time,
            'Direction': 'SHORT',
            'Entry_Price': pos.entry_price,
            'Exit_Price': final_price,
            'Size': pos.size,
            'Gross_PnL': gross_pnl,
            'Commission': commission_cost,
            'Net_PnL': net_pnl,
            'Exit_Reason': 'End of Data',
            'Candles_Held': len(df) - pos.entry_idx,
            'Partial': 'Yes' if pos.size < pos.original_size else 'No'
        })
    
    return trades, equity_curve, capital

# ============================================================================
# PERFORMANCE METRICS
# ============================================================================

def calculate_metrics(trades, equity_curve, final_capital):
    """Calculate comprehensive performance metrics"""
    if not trades:
        return None
    
    trades_df = pd.DataFrame(trades)
    
    # Basic metrics
    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df['Net_PnL'] > 0])
    losing_trades = len(trades_df[trades_df['Net_PnL'] <= 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    # PnL metrics
    total_pnl = trades_df['Net_PnL'].sum()
    gross_profit = trades_df[trades_df['Net_PnL'] > 0]['Net_PnL'].sum()
    gross_loss = abs(trades_df[trades_df['Net_PnL'] <= 0]['Net_PnL'].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')
    
    # Return metrics
    total_return = ((final_capital - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100
    
    # Best/Worst trades
    best_trade = trades_df['Net_PnL'].max()
    worst_trade = trades_df['Net_PnL'].min()
    avg_win = trades_df[trades_df['Net_PnL'] > 0]['Net_PnL'].mean() if winning_trades > 0 else 0
    avg_loss = trades_df[trades_df['Net_PnL'] <= 0]['Net_PnL'].mean() if losing_trades > 0 else 0
    
    # Drawdown
    equity_series = pd.Series(equity_curve)
    rolling_max = equity_series.expanding().max()
    drawdown = (equity_series - rolling_max) / rolling_max * 100
    max_drawdown = drawdown.min()
    
    # Sharpe ratio (simplified - using daily returns)
    returns = equity_series.pct_change().dropna()
    if len(returns) > 0 and returns.std() > 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(365 * 96)  # Annualized (15-min data)
    else:
        sharpe = 0
    
    # Trade duration stats
    avg_duration = trades_df['Candles_Held'].mean()
    
    # Exit reason breakdown
    exit_reasons = trades_df['Exit_Reason'].value_counts().to_dict()
    
    return {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'profit_factor': profit_factor,
        'total_return': total_return,
        'final_capital': final_capital,
        'best_trade': best_trade,
        'worst_trade': worst_trade,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'max_drawdown': max_drawdown,
        'sharpe_ratio': sharpe,
        'avg_duration': avg_duration,
        'exit_reasons': exit_reasons
    }

def analyze_by_time(trades_df):
    """Analyze performance by hour and day"""
    if trades_df.empty:
        return {}, {}
    
    trades_df['Entry_Hour'] = pd.to_datetime(trades_df['Entry_Time']).dt.hour
    trades_df['Entry_Day'] = pd.to_datetime(trades_df['Entry_Time']).dt.day_name()
    
    # Hour analysis
    hour_stats = {}
    for hour in range(24):
        hour_trades = trades_df[trades_df['Entry_Hour'] == hour]
        if len(hour_trades) > 0:
            hour_stats[hour] = {
                'count': len(hour_trades),
                'win_rate': len(hour_trades[hour_trades['Net_PnL'] > 0]) / len(hour_trades) * 100,
                'avg_pnl': hour_trades['Net_PnL'].mean()
            }
    
    # Day analysis
    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    day_stats = {}
    for day in day_order:
        day_trades = trades_df[trades_df['Entry_Day'] == day]
        if len(day_trades) > 0:
            day_stats[day] = {
                'count': len(day_trades),
                'win_rate': len(day_trades[day_trades['Net_PnL'] > 0]) / len(day_trades) * 100,
                'avg_pnl': day_trades['Net_PnL'].mean()
            }
    
    return hour_stats, day_stats

def analyze_by_month(trades_df):
    """Analyze performance by month"""
    if trades_df.empty:
        return {}
    
    trades_df['Exit_Month'] = pd.to_datetime(trades_df['Exit_Time']).dt.to_period('M')
    
    monthly_stats = {}
    for month in trades_df['Exit_Month'].unique():
        month_trades = trades_df[trades_df['Exit_Month'] == month]
        monthly_pnl = month_trades['Net_PnL'].sum()
        monthly_stats[str(month)] = {
            'trades': len(month_trades),
            'pnl': monthly_pnl,
            'wins': len(month_trades[month_trades['Net_PnL'] > 0])
        }
    
    return monthly_stats

# ============================================================================
# OUTPUT AND REPORTING
# ============================================================================

def save_trade_log(trades, filename='trade_log_v5a.csv'):
    """Save detailed trade log"""
    if not trades:
        print(f"No trades to save.")
        return
    
    df = pd.DataFrame(trades)
    df.to_csv(filename, index=False)
    print(f"\nTrade log saved to: {filename}")

def save_equity_curve(equity_curve, filename='equity_curve_v5a.csv'):
    """Save equity curve data"""
    df = pd.DataFrame({
        'Step': range(len(equity_curve)),
        'Equity': equity_curve
    })
    df.to_csv(filename, index=False)
    print(f"Equity curve saved to: {filename}")

def print_results(metrics, trades_df, hour_stats, day_stats, monthly_stats):
    """Print comprehensive results to console"""
    print(f"\n{'='*80}")
    print(f"BACKTEST RESULTS - V5A SHORT ONLY")
    print(f"{'='*80}\n")
    
    print(f"OVERALL PERFORMANCE:")
    print(f"  Initial Capital:    ${INITIAL_CAPITAL:,.2f}")
    print(f"  Final Capital:      ${metrics['final_capital']:,.2f}")
    print(f"  Total Return:       {metrics['total_return']:.2f}%")
    print(f"  Total PnL:          ${metrics['total_pnl']:,.2f}")
    print(f"  Max Drawdown:       {metrics['max_drawdown']:.2f}%")
    print(f"  Sharpe Ratio:       {metrics['sharpe_ratio']:.2f}")
    
    print(f"\nTRADE STATISTICS:")
    print(f"  Total Trades:       {metrics['total_trades']}")
    print(f"  Winning Trades:     {metrics['winning_trades']}")
    print(f"  Losing Trades:      {metrics['losing_trades']}")
    print(f"  Win Rate:           {metrics['win_rate']:.2f}%")
    print(f"  Profit Factor:      {metrics['profit_factor']:.2f}")
    
    print(f"\nPROFIT/LOSS:")
    print(f"  Gross Profit:       ${metrics['gross_profit']:,.2f}")
    print(f"  Gross Loss:         ${metrics['gross_loss']:,.2f}")
    print(f"  Best Trade:         ${metrics['best_trade']:,.2f}")
    print(f"  Worst Trade:        ${metrics['worst_trade']:,.2f}")
    print(f"  Avg Winning Trade:  ${metrics['avg_win']:,.2f}")
    print(f"  Avg Losing Trade:   ${metrics['avg_loss']:,.2f}")
    
    print(f"\nTRADE DURATION:")
    print(f"  Avg Duration:       {metrics['avg_duration']:.1f} candles ({metrics['avg_duration']*0.25:.1f} hours)")
    
    print(f"\nEXIT REASONS:")
    for reason, count in metrics['exit_reasons'].items():
        pct = (count / metrics['total_trades']) * 100
        print(f"  {reason:20s}: {count:3d} ({pct:5.1f}%)")
    
    if monthly_stats:
        print(f"\nMONTHLY BREAKDOWN:")
        for month, stats in sorted(monthly_stats.items()):
            print(f"  {month}: {stats['trades']:2d} trades, "
                  f"${stats['pnl']:8,.2f} PnL, "
                  f"{stats['wins']:2d} wins")
    
    if hour_stats:
        print(f"\nHOURLY ANALYSIS (Top 5 by count):")
        sorted_hours = sorted(hour_stats.items(), key=lambda x: x[1]['count'], reverse=True)[:5]
        for hour, stats in sorted_hours:
            print(f"  {hour:02d}:00 - {stats['count']:2d} trades, "
                  f"WR: {stats['win_rate']:5.1f}%, "
                  f"Avg PnL: ${stats['avg_pnl']:7,.2f}")
    
    if day_stats:
        print(f"\nDAILY ANALYSIS:")
        for day, stats in day_stats.items():
            print(f"  {day:9s}: {stats['count']:2d} trades, "
                  f"WR: {stats['win_rate']:5.1f}%, "
                  f"Avg PnL: ${stats['avg_pnl']:7,.2f}")
    
    print(f"\n{'='*80}")

def create_results_markdown(metrics, trades_df, hour_stats, day_stats, monthly_stats, filename='STRATEGY_V5A_RESULTS.md'):
    """Create detailed results markdown file"""
    with open(filename, 'w') as f:
        f.write("# Strategy V5A - Short-Only Results\n\n")
        f.write("## Overview\n")
        f.write(f"**Strategy**: Short-Only 'Panic Catcher' based on V4 shorts\n\n")
        f.write(f"**Data Period**: Year 2025 ETHUSDT 15-minute data\n\n")
        f.write(f"**Strategy Type**: Mean-reversion short entries during panic selling\n\n")
        
        f.write("## Key Performance Metrics\n\n")
        f.write(f"| Metric | Value |\n")
        f.write(f"|--------|-------|\n")
        f.write(f"| Initial Capital | ${INITIAL_CAPITAL:,.2f} |\n")
        f.write(f"| Final Capital | ${metrics['final_capital']:,.2f} |\n")
        f.write(f"| **Total Return** | **{metrics['total_return']:.2f}%** |\n")
        f.write(f"| **Max Drawdown** | **{metrics['max_drawdown']:.2f}%** |\n")
        f.write(f"| Sharpe Ratio | {metrics['sharpe_ratio']:.2f} |\n")
        f.write(f"| **Win Rate** | **{metrics['win_rate']:.2f}%** |\n")
        f.write(f"| **Profit Factor** | **{metrics['profit_factor']:.2f}** |\n")
        f.write(f"| Total Trades | {metrics['total_trades']} |\n")
        f.write(f"| Winning Trades | {metrics['winning_trades']} |\n")
        f.write(f"| Losing Trades | {metrics['losing_trades']} |\n\n")
        
        f.write("## Trade Analysis\n\n")
        f.write(f"| Metric | Value |\n")
        f.write(f"|--------|-------|\n")
        f.write(f"| Gross Profit | ${metrics['gross_profit']:,.2f} |\n")
        f.write(f"| Gross Loss | ${metrics['gross_loss']:,.2f} |\n")
        f.write(f"| Best Trade | ${metrics['best_trade']:,.2f} |\n")
        f.write(f"| Worst Trade | ${metrics['worst_trade']:,.2f} |\n")
        f.write(f"| Avg Winning Trade | ${metrics['avg_win']:,.2f} |\n")
        f.write(f"| Avg Losing Trade | ${metrics['avg_loss']:,.2f} |\n")
        f.write(f"| Avg Trade Duration | {metrics['avg_duration']:.1f} candles ({metrics['avg_duration']*0.25:.1f} hours) |\n\n")
        
        f.write("## Exit Reason Breakdown\n\n")
        f.write(f"| Exit Reason | Count | Percentage |\n")
        f.write(f"|-------------|-------|------------|\n")
        for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: x[1], reverse=True):
            pct = (count / metrics['total_trades']) * 100
            f.write(f"| {reason} | {count} | {pct:.1f}% |\n")
        
        if monthly_stats:
            f.write("\n## Monthly Performance\n\n")
            f.write(f"| Month | Trades | PnL | Wins |\n")
            f.write(f"|-------|--------|-----|------|\n")
            for month, stats in sorted(monthly_stats.items()):
                f.write(f"| {month} | {stats['trades']} | ${stats['pnl']:,.2f} | {stats['wins']} |\n")
        
        if hour_stats:
            f.write("\n## Hourly Performance\n\n")
            f.write(f"| Hour (UTC) | Trades | Win Rate | Avg PnL |\n")
            f.write(f"|------------|--------|----------|----------|\n")
            for hour in sorted(hour_stats.keys()):
                stats = hour_stats[hour]
                f.write(f"| {hour:02d}:00 | {stats['count']} | {stats['win_rate']:.1f}% | ${stats['avg_pnl']:,.2f} |\n")
        
        if day_stats:
            f.write("\n## Daily Performance\n\n")
            f.write(f"| Day | Trades | Win Rate | Avg PnL |\n")
            f.write(f"|-----|--------|----------|----------|\n")
            for day, stats in day_stats.items():
                f.write(f"| {day} | {stats['count']} | {stats['win_rate']:.1f}% | ${stats['avg_pnl']:,.2f} |\n")
        
        f.write("\n## Strategy Configuration\n\n")
        f.write("### Entry Conditions (ALL must be true)\n")
        f.write("1. EMA 10 < EMA 30 (bearish trend)\n")
        f.write("2. Close < EMA 10 (price below fast EMA)\n")
        f.write("3. Fast MACD (8,17,5) histogram < 0 AND declining\n")
        f.write("4. RSI between 28 and 47 (bearish but not oversold)\n")
        f.write("5. Volume > 1.9 × Volume SMA 20 (panic spike)\n")
        f.write("6. Close < Lower Bollinger Band OR price drop > 0.6%\n\n")
        
        f.write("### Risk Parameters\n")
        f.write(f"- Risk per trade: {RISK_PER_TRADE*100}%\n")
        f.write(f"- Stop Loss: {STOP_LOSS_ATR_MULT} × ATR\n")
        f.write(f"- Take Profit 1: {TP1_ATR_MULT} × ATR (close {TP1_CLOSE_PCT*100:.0f}%)\n")
        f.write(f"- Take Profit 2: {TP2_ATR_MULT} × ATR (close {TP2_CLOSE_PCT*100:.0f}%)\n")
        f.write(f"- Take Profit 3: {TP3_ATR_MULT} × ATR (close {TP3_CLOSE_PCT*100:.0f}%)\n")
        f.write(f"- Trailing Stop: {TRAILING_STOP_ATR_MULT} × ATR (after TP2)\n")
        f.write(f"- Max simultaneous positions: {MAX_POSITIONS}\n")
        f.write(f"- Max trade duration: {MAX_TRADE_DURATION} candles ({MAX_TRADE_DURATION*0.25:.0f} hours)\n\n")
        
        f.write("### Time Filters\n")
        f.write("- No trading Saturday/Sunday\n")
        f.write("- No new positions Friday after 18:00 UTC\n")
        f.write("- Close all positions by Friday 20:00 UTC\n")
        f.write("- Position sizing varies by hour (40%-100%)\n\n")
        
        f.write("## Comparison with V4 Shorts\n\n")
        f.write("V4 shorts had:\n")
        f.write("- 58.33% win rate\n")
        f.write("- 2.43 profit factor\n")
        f.write("- 36 short trades\n\n")
        
        f.write("V5A achieved:\n")
        f.write(f"- {metrics['win_rate']:.2f}% win rate\n")
        f.write(f"- {metrics['profit_factor']:.2f} profit factor\n")
        f.write(f"- {metrics['total_trades']} trades\n")
        f.write(f"- {metrics['total_return']:.2f}% return\n\n")
        
        f.write("## Conclusion\n\n")
        if metrics['total_return'] >= 20 and metrics['max_drawdown'] > -15 and metrics['win_rate'] >= 55:
            f.write("✅ **Strategy meets all target objectives**\n\n")
        else:
            f.write("⚠️ **Strategy performance notes**\n\n")
        
        f.write(f"The strategy {'achieved' if metrics['total_return'] >= 20 else 'did not achieve'} the target return of 20-28%.\n")
        f.write(f"Max drawdown was {'within' if metrics['max_drawdown'] > -15 else 'outside'} the target of <15%.\n")
        f.write(f"Win rate was {'within' if metrics['win_rate'] >= 55 else 'below'} the target range of 55-60%.\n\n")
    
    print(f"Results markdown saved to: {filename}")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function"""
    # Load data
    print("Loading market data...")
    df = load_data('ETHUSDT_15_Minutes_year_2025.txt')
    
    # Calculate indicators
    print("Calculating technical indicators...")
    df = calculate_indicators(df)
    
    # Run backtest
    trades, equity_curve, final_capital = run_backtest(df)
    
    if not trades:
        print("\nNo trades were executed. Check entry conditions.")
        return
    
    # Calculate metrics
    metrics = calculate_metrics(trades, equity_curve, final_capital)
    
    # Analyze performance
    trades_df = pd.DataFrame(trades)
    hour_stats, day_stats = analyze_by_time(trades_df)
    monthly_stats = analyze_by_month(trades_df)
    
    # Print results
    print_results(metrics, trades_df, hour_stats, day_stats, monthly_stats)
    
    # Save outputs
    save_trade_log(trades, 'trade_log_v5a.csv')
    save_equity_curve(equity_curve, 'equity_curve_v5a.csv')
    create_results_markdown(metrics, trades_df, hour_stats, day_stats, monthly_stats, 'STRATEGY_V5A_RESULTS.md')
    
    print(f"\n{'='*80}")
    print("Backtest complete! All files saved.")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
