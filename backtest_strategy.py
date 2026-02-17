#!/usr/bin/env python3
"""
ETHUSDT Trading Strategy Backtest
Complete backtest implementation with risk management, multiple indicators, and comprehensive reporting.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys

# ============================================================================
# INDICATOR CALCULATION FUNCTIONS
# ============================================================================

def calculate_ema(series, period):
    """Calculate Exponential Moving Average"""
    return series.ewm(span=period, adjust=False).mean()

def calculate_sma(series, period):
    """Calculate Simple Moving Average"""
    return series.rolling(window=period).mean()

def calculate_rsi(series, period=14):
    """Calculate Relative Strength Index"""
    delta = series.diff()
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

def calculate_macd(series, fast=12, slow=26, signal=9):
    """Calculate MACD, Signal Line, and Histogram"""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

# ============================================================================
# DATA LOADING
# ============================================================================

def load_data(filename):
    """Load and parse ETHUSDT candlestick data"""
    print(f"Loading data from {filename}...")
    
    # Read CSV with proper parsing
    df = pd.read_csv(
        filename,
        skipinitialspace=True,
        names=['Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume'],
        skiprows=1  # Skip header
    )
    
    # Create datetime column
    df['DateTime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'], format='%m/%d/%Y %H:%M:%S')
    
    # Convert price and volume columns to numeric
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Sort by datetime
    df = df.sort_values('DateTime').reset_index(drop=True)
    
    print(f"Loaded {len(df)} candles from {df['DateTime'].iloc[0]} to {df['DateTime'].iloc[-1]}")
    
    return df

# ============================================================================
# INDICATOR COMPUTATION
# ============================================================================

def compute_indicators(df):
    """Compute all technical indicators"""
    print("Computing indicators...")
    
    # EMA
    df['EMA50'] = calculate_ema(df['Close'], 50)
    df['EMA200'] = calculate_ema(df['Close'], 200)
    
    # RSI
    df['RSI'] = calculate_rsi(df['Close'], 14)
    
    # ATR
    df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
    
    # MACD
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calculate_macd(df['Close'], 12, 26, 9)
    
    # Volume SMA
    df['Volume_SMA20'] = calculate_sma(df['Volume'], 20)
    
    # Previous MACD histogram for trend detection
    df['MACD_Hist_Prev'] = df['MACD_Hist'].shift(1)
    
    print("Indicators computed successfully.")
    
    return df

# ============================================================================
# SIGNAL DETECTION
# ============================================================================

def check_long_entry(row, prev_row):
    """Check if all LONG entry conditions are met"""
    if pd.isna(row['EMA50']) or pd.isna(row['EMA200']) or pd.isna(row['RSI']):
        return False
    if pd.isna(row['MACD_Hist']) or pd.isna(row['MACD_Hist_Prev']):
        return False
    if pd.isna(row['Volume_SMA20']):
        return False
    
    # 1. EMA50 > EMA200 (bullish trend)
    if row['EMA50'] <= row['EMA200']:
        return False
    
    # 2. MACD histogram > 0 AND rising
    if row['MACD_Hist'] <= 0 or row['MACD_Hist'] <= row['MACD_Hist_Prev']:
        return False
    
    # 3. RSI between 35 and 65
    if row['RSI'] < 35 or row['RSI'] > 65:
        return False
    
    # 4. Close > EMA50
    if row['Close'] <= row['EMA50']:
        return False
    
    # 5. Volume > 1.2 × Volume_SMA20
    if row['Volume'] <= 1.2 * row['Volume_SMA20']:
        return False
    
    return True

def check_short_entry(row, prev_row):
    """Check if all SHORT entry conditions are met"""
    if pd.isna(row['EMA50']) or pd.isna(row['EMA200']) or pd.isna(row['RSI']):
        return False
    if pd.isna(row['MACD_Hist']) or pd.isna(row['MACD_Hist_Prev']):
        return False
    if pd.isna(row['Volume_SMA20']):
        return False
    
    # 1. EMA50 < EMA200 (bearish trend)
    if row['EMA50'] >= row['EMA200']:
        return False
    
    # 2. MACD histogram < 0 AND falling
    if row['MACD_Hist'] >= 0 or row['MACD_Hist'] >= row['MACD_Hist_Prev']:
        return False
    
    # 3. RSI between 35 and 65
    if row['RSI'] < 35 or row['RSI'] > 65:
        return False
    
    # 4. Close < EMA50
    if row['Close'] >= row['EMA50']:
        return False
    
    # 5. Volume > 1.2 × Volume_SMA20
    if row['Volume'] <= 1.2 * row['Volume_SMA20']:
        return False
    
    return True

def check_consolidation_filter(row):
    """Check if market is in consolidation (avoid trading)"""
    if pd.isna(row['EMA50']) or pd.isna(row['EMA200']):
        return True  # Conservative: avoid if we can't determine
    
    ema_diff = abs(row['EMA50'] - row['EMA200']) / row['Close']
    return ema_diff < 0.005  # 0.5% threshold

def is_weekend_restriction(dt):
    """Check if it's Friday after 20:00 UTC (no new positions)"""
    # Friday is weekday 4
    if dt.weekday() == 4 and dt.hour >= 20:
        return True
    return False

# ============================================================================
# POSITION AND TRADE MANAGEMENT
# ============================================================================

class Position:
    """Represents an open trading position"""
    def __init__(self, trade_num, position_type, entry_date, entry_price, position_size, 
                 stop_loss, tp1, tp2, capital, atr):
        self.trade_num = trade_num
        self.type = position_type  # 'LONG' or 'SHORT'
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.position_size = position_size  # In ETH
        self.original_size = position_size
        self.stop_loss = stop_loss
        self.tp1 = tp1
        self.tp2 = tp2
        self.tp1_hit = False
        self.capital_at_entry = capital
        self.atr_at_entry = atr
        self.trailing_stop = None
        
        # Calculate opening commission
        trade_value = position_size * entry_price
        self.commission_open = trade_value * 0.0005
    
    def update_trailing_stop(self, current_price, atr):
        """Update trailing stop after TP1 is hit"""
        if not self.tp1_hit:
            return
        
        if self.type == 'LONG':
            # Trail 1 × ATR below price
            new_trailing = current_price - atr
            if self.trailing_stop is None or new_trailing > self.trailing_stop:
                self.trailing_stop = new_trailing
        else:  # SHORT
            # Trail 1 × ATR above price
            new_trailing = current_price + atr
            if self.trailing_stop is None or new_trailing < self.trailing_stop:
                self.trailing_stop = new_trailing

class Trade:
    """Represents a completed trade for logging"""
    def __init__(self, trade_num, position_type, entry_date, entry_price, exit_date, 
                 exit_price, position_size, pnl_usdt, pnl_percent, commission, net_pnl):
        self.trade_num = trade_num
        self.type = position_type
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.exit_date = exit_date
        self.exit_price = exit_price
        self.position_size = position_size
        self.pnl_usdt = pnl_usdt
        self.pnl_percent = pnl_percent
        self.commission = commission
        self.net_pnl = net_pnl

# ============================================================================
# BACKTEST ENGINE
# ============================================================================

def run_backtest(df, initial_capital=100000):
    """Run the complete backtest simulation"""
    print("\nStarting backtest simulation...")
    print(f"Initial Capital: ${initial_capital:,.2f}")
    
    # Initialize backtest state
    capital = initial_capital
    position = None
    trades = []
    equity_curve = []
    trade_counter = 0
    
    # Daily loss tracking (last 96 candles = 24 hours)
    recent_pnl = []
    trading_paused_until = None
    
    # Main backtest loop
    for i in range(len(df)):
        row = df.iloc[i]
        
        # Record equity
        equity_curve.append({
            'DateTime': row['DateTime'],
            'Equity': capital,
            'DrawdownPercent': 0  # Will calculate later
        })
        
        # Check if trading is paused due to daily loss limit
        if trading_paused_until is not None:
            if row['DateTime'] < trading_paused_until:
                continue
            else:
                trading_paused_until = None
                print(f"Trading resumed at {row['DateTime']}")
        
        # ====================================================================
        # MANAGE EXISTING POSITION
        # ====================================================================
        if position is not None:
            exit_triggered = False
            exit_reason = ""
            exit_price = None
            partial_close = False
            close_size = position.position_size
            
            # Check RSI extreme exit
            if position.type == 'LONG' and row['RSI'] > 80:
                exit_triggered = True
                exit_reason = "RSI > 80 (overbought)"
                exit_price = row['Close']
            elif position.type == 'SHORT' and row['RSI'] < 20:
                exit_triggered = True
                exit_reason = "RSI < 20 (oversold)"
                exit_price = row['Close']
            
            # Check Stop Loss
            if not exit_triggered:
                if position.type == 'LONG' and row['Low'] <= position.stop_loss:
                    exit_triggered = True
                    exit_reason = "Stop Loss"
                    exit_price = position.stop_loss
                elif position.type == 'SHORT' and row['High'] >= position.stop_loss:
                    exit_triggered = True
                    exit_reason = "Stop Loss"
                    exit_price = position.stop_loss
            
            # Check Trailing Stop (if TP1 was hit)
            if not exit_triggered and position.trailing_stop is not None:
                if position.type == 'LONG' and row['Low'] <= position.trailing_stop:
                    exit_triggered = True
                    exit_reason = "Trailing Stop"
                    exit_price = position.trailing_stop
                elif position.type == 'SHORT' and row['High'] >= position.trailing_stop:
                    exit_triggered = True
                    exit_reason = "Trailing Stop"
                    exit_price = position.trailing_stop
            
            # Check TP2
            if not exit_triggered and position.tp1_hit:
                if position.type == 'LONG' and row['High'] >= position.tp2:
                    exit_triggered = True
                    exit_reason = "TP2"
                    exit_price = position.tp2
                elif position.type == 'SHORT' and row['Low'] <= position.tp2:
                    exit_triggered = True
                    exit_reason = "TP2"
                    exit_price = position.tp2
            
            # Check TP1 (partial close)
            if not exit_triggered and not position.tp1_hit:
                if position.type == 'LONG' and row['High'] >= position.tp1:
                    partial_close = True
                    exit_reason = "TP1 (50% close)"
                    exit_price = position.tp1
                    close_size = position.position_size * 0.5
                elif position.type == 'SHORT' and row['Low'] <= position.tp1:
                    partial_close = True
                    exit_reason = "TP1 (50% close)"
                    exit_price = position.tp1
                    close_size = position.position_size * 0.5
            
            # Check counter-signal
            if not exit_triggered and not partial_close:
                prev_row = df.iloc[i-1] if i > 0 else row
                if position.type == 'LONG' and check_short_entry(row, prev_row):
                    exit_triggered = True
                    exit_reason = "Counter-signal (SHORT entry)"
                    exit_price = row['Close']
                elif position.type == 'SHORT' and check_long_entry(row, prev_row):
                    exit_triggered = True
                    exit_reason = "Counter-signal (LONG entry)"
                    exit_price = row['Close']
            
            # Execute exit
            if exit_triggered or partial_close:
                # Calculate P&L
                if position.type == 'LONG':
                    pnl_usdt = (exit_price - position.entry_price) * close_size
                else:  # SHORT
                    pnl_usdt = (position.entry_price - exit_price) * close_size
                
                # Calculate commission for closing
                close_value = close_size * exit_price
                commission_close = close_value * 0.0005
                
                # Net P&L
                if partial_close:
                    # For partial close, only count proportional opening commission
                    proportion = close_size / position.original_size
                    commission_total = (position.commission_open * proportion) + commission_close
                else:
                    commission_total = position.commission_open + commission_close
                
                net_pnl = pnl_usdt - commission_total
                capital += net_pnl
                
                # Track recent P&L for daily loss limit
                recent_pnl.append(net_pnl)
                if len(recent_pnl) > 96:
                    recent_pnl.pop(0)
                
                # Calculate percentage return
                entry_value = close_size * position.entry_price
                pnl_percent = (pnl_usdt / entry_value) * 100
                
                # Log trade
                trade = Trade(
                    trade_num=position.trade_num,
                    position_type=position.type,
                    entry_date=position.entry_date,
                    entry_price=position.entry_price,
                    exit_date=row['DateTime'],
                    exit_price=exit_price,
                    position_size=close_size,
                    pnl_usdt=pnl_usdt,
                    pnl_percent=pnl_percent,
                    commission=commission_total,
                    net_pnl=net_pnl
                )
                trades.append(trade)
                
                if partial_close:
                    # TP1 hit: reduce position size, move SL to break-even
                    position.position_size -= close_size
                    position.tp1_hit = True
                    position.stop_loss = position.entry_price
                    position.commission_open -= position.commission_open * (close_size / position.original_size)
                    print(f"  TP1 hit at {row['DateTime']}: Closed 50%, moved SL to break-even")
                else:
                    # Full exit
                    print(f"  Exit {position.type} at {row['DateTime']}: {exit_reason}, Net P&L: ${net_pnl:,.2f}")
                    position = None
            
            # Update trailing stop if TP1 was hit
            if position is not None and position.tp1_hit:
                position.update_trailing_stop(row['Close'], row['ATR'])
        
        # ====================================================================
        # CHECK FOR NEW ENTRY (only if no position)
        # ====================================================================
        if position is None and i > 0:
            # Skip if indicators not ready
            if pd.isna(row['EMA200']) or pd.isna(row['ATR']):
                continue
            
            # Check daily loss limit
            if len(recent_pnl) >= 96:
                recent_loss = sum([x for x in recent_pnl if x < 0])
                if recent_loss < -0.03 * initial_capital:
                    if trading_paused_until is None:
                        trading_paused_until = row['DateTime'] + timedelta(hours=24)
                        print(f"Daily loss limit exceeded at {row['DateTime']}, pausing trading for 24h")
                    continue
            
            # Check consolidation filter
            if check_consolidation_filter(row):
                continue
            
            # Check weekend filter
            if is_weekend_restriction(row['DateTime']):
                continue
            
            prev_row = df.iloc[i-1]
            
            # Check for LONG entry
            if check_long_entry(row, prev_row):
                trade_counter += 1
                
                # Calculate position size
                risk_usdt = capital * 0.01
                sl_distance = 1.5 * row['ATR']
                position_size_eth = risk_usdt / sl_distance
                entry_price = row['Close']
                
                # Set stop loss and take profits
                stop_loss = entry_price - sl_distance
                tp1 = entry_price + (2.0 * row['ATR'])
                tp2 = entry_price + (3.5 * row['ATR'])
                
                # Create position
                position = Position(
                    trade_num=trade_counter,
                    position_type='LONG',
                    entry_date=row['DateTime'],
                    entry_price=entry_price,
                    position_size=position_size_eth,
                    stop_loss=stop_loss,
                    tp1=tp1,
                    tp2=tp2,
                    capital=capital,
                    atr=row['ATR']
                )
                
                capital -= position.commission_open
                
                print(f"  Enter LONG #{trade_counter} at {row['DateTime']}: Price=${entry_price:.2f}, Size={position_size_eth:.4f} ETH, SL=${stop_loss:.2f}, TP1=${tp1:.2f}, TP2=${tp2:.2f}")
            
            # Check for SHORT entry
            elif check_short_entry(row, prev_row):
                trade_counter += 1
                
                # Calculate position size
                risk_usdt = capital * 0.01
                sl_distance = 1.5 * row['ATR']
                position_size_eth = risk_usdt / sl_distance
                entry_price = row['Close']
                
                # Set stop loss and take profits
                stop_loss = entry_price + sl_distance
                tp1 = entry_price - (2.0 * row['ATR'])
                tp2 = entry_price - (3.5 * row['ATR'])
                
                # Create position
                position = Position(
                    trade_num=trade_counter,
                    position_type='SHORT',
                    entry_date=row['DateTime'],
                    entry_price=entry_price,
                    position_size=position_size_eth,
                    stop_loss=stop_loss,
                    tp1=tp1,
                    tp2=tp2,
                    capital=capital,
                    atr=row['ATR']
                )
                
                capital -= position.commission_open
                
                print(f"  Enter SHORT #{trade_counter} at {row['DateTime']}: Price=${entry_price:.2f}, Size={position_size_eth:.4f} ETH, SL=${stop_loss:.2f}, TP1=${tp1:.2f}, TP2=${tp2:.2f}")
    
    # Close any remaining open position at the end
    if position is not None:
        final_row = df.iloc[-1]
        exit_price = final_row['Close']
        
        if position.type == 'LONG':
            pnl_usdt = (exit_price - position.entry_price) * position.position_size
        else:
            pnl_usdt = (position.entry_price - exit_price) * position.position_size
        
        close_value = position.position_size * exit_price
        commission_close = close_value * 0.0005
        commission_total = position.commission_open + commission_close
        net_pnl = pnl_usdt - commission_total
        capital += net_pnl
        
        entry_value = position.position_size * position.entry_price
        pnl_percent = (pnl_usdt / entry_value) * 100
        
        trade = Trade(
            trade_num=position.trade_num,
            position_type=position.type,
            entry_date=position.entry_date,
            entry_price=position.entry_price,
            exit_date=final_row['DateTime'],
            exit_price=exit_price,
            position_size=position.position_size,
            pnl_usdt=pnl_usdt,
            pnl_percent=pnl_percent,
            commission=commission_total,
            net_pnl=net_pnl
        )
        trades.append(trade)
        print(f"  Closed final position at end of backtest: Net P&L: ${net_pnl:,.2f}")
    
    print(f"\nBacktest completed. Total trades: {len(trades)}")
    
    return trades, equity_curve, capital

# ============================================================================
# PERFORMANCE METRICS
# ============================================================================

def calculate_performance_metrics(trades, equity_curve, initial_capital, final_capital):
    """Calculate comprehensive performance statistics"""
    print("\nCalculating performance metrics...")
    
    metrics = {}
    
    # Basic metrics
    total_trades = len(trades)
    metrics['Total Trades'] = total_trades
    
    if total_trades == 0:
        print("No trades executed during backtest period.")
        return metrics
    
    # Count long and short trades
    long_trades = [t for t in trades if t.type == 'LONG']
    short_trades = [t for t in trades if t.type == 'SHORT']
    metrics['Long Trades'] = len(long_trades)
    metrics['Short Trades'] = len(short_trades)
    
    # Win rate
    winning_trades = [t for t in trades if t.net_pnl > 0]
    losing_trades = [t for t in trades if t.net_pnl <= 0]
    win_rate = (len(winning_trades) / total_trades) * 100 if total_trades > 0 else 0
    metrics['Win Rate'] = win_rate
    metrics['Winning Trades'] = len(winning_trades)
    metrics['Losing Trades'] = len(losing_trades)
    
    # Profit metrics
    total_pnl = final_capital - initial_capital
    total_return = (total_pnl / initial_capital) * 100
    metrics['Total Net P&L'] = total_pnl
    metrics['Total Return %'] = total_return
    metrics['Final Equity'] = final_capital
    
    # Best and worst trades
    if trades:
        best_trade = max(trades, key=lambda t: t.net_pnl)
        worst_trade = min(trades, key=lambda t: t.net_pnl)
        metrics['Best Trade'] = best_trade.net_pnl
        metrics['Worst Trade'] = worst_trade.net_pnl
        
        avg_trade = total_pnl / total_trades
        metrics['Average Trade P&L'] = avg_trade
    
    # Profit factor
    gross_profit = sum([t.net_pnl for t in trades if t.net_pnl > 0])
    gross_loss = abs(sum([t.net_pnl for t in trades if t.net_pnl < 0]))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    metrics['Gross Profit'] = gross_profit
    metrics['Gross Loss'] = gross_loss
    metrics['Profit Factor'] = profit_factor
    
    # Drawdown calculation
    equity_series = pd.Series([e['Equity'] for e in equity_curve])
    running_max = equity_series.expanding().max()
    drawdown = (equity_series - running_max) / running_max * 100
    max_drawdown = drawdown.min()
    max_drawdown_usdt = (equity_series - running_max).min()
    
    metrics['Max Drawdown %'] = max_drawdown
    metrics['Max Drawdown USDT'] = max_drawdown_usdt
    
    # Update equity curve with drawdown
    for i, e in enumerate(equity_curve):
        e['DrawdownPercent'] = drawdown.iloc[i]
    
    # Sharpe Ratio (annualized)
    # Calculate daily returns
    equity_df = pd.DataFrame(equity_curve)
    equity_df['Return'] = equity_df['Equity'].pct_change()
    
    # Assuming 15-minute candles, there are 96 candles per day
    # Annualization factor: sqrt(365 * 96) for 15-min data
    daily_returns = equity_df['Return'].dropna()
    
    if len(daily_returns) > 0 and daily_returns.std() > 0:
        avg_return = daily_returns.mean()
        std_return = daily_returns.std()
        # Annualize assuming 96 periods per day * 365 days
        sharpe_ratio = (avg_return / std_return) * np.sqrt(96 * 365)
        metrics['Sharpe Ratio'] = sharpe_ratio
    else:
        metrics['Sharpe Ratio'] = 0
    
    return metrics

# ============================================================================
# OUTPUT FUNCTIONS
# ============================================================================

def print_results(metrics):
    """Print comprehensive results to console"""
    print("\n" + "="*70)
    print(" BACKTEST RESULTS SUMMARY")
    print("="*70)
    
    print("\n--- TRADE STATISTICS ---")
    print(f"Total Trades:          {metrics.get('Total Trades', 0)}")
    print(f"  Long Trades:         {metrics.get('Long Trades', 0)}")
    print(f"  Short Trades:        {metrics.get('Short Trades', 0)}")
    print(f"Winning Trades:        {metrics.get('Winning Trades', 0)}")
    print(f"Losing Trades:         {metrics.get('Losing Trades', 0)}")
    print(f"Win Rate:              {metrics.get('Win Rate', 0):.2f}%")
    
    print("\n--- PROFIT & LOSS ---")
    print(f"Initial Capital:       ${metrics.get('Final Equity', 100000) - metrics.get('Total Net P&L', 0):,.2f}")
    print(f"Final Equity:          ${metrics.get('Final Equity', 0):,.2f}")
    print(f"Total Net P&L:         ${metrics.get('Total Net P&L', 0):,.2f}")
    print(f"Total Return:          {metrics.get('Total Return %', 0):.2f}%")
    print(f"Gross Profit:          ${metrics.get('Gross Profit', 0):,.2f}")
    print(f"Gross Loss:            ${metrics.get('Gross Loss', 0):,.2f}")
    print(f"Profit Factor:         {metrics.get('Profit Factor', 0):.2f}")
    print(f"Average Trade P&L:     ${metrics.get('Average Trade P&L', 0):,.2f}")
    
    print("\n--- BEST & WORST ---")
    print(f"Best Trade:            ${metrics.get('Best Trade', 0):,.2f}")
    print(f"Worst Trade:           ${metrics.get('Worst Trade', 0):,.2f}")
    
    print("\n--- RISK METRICS ---")
    print(f"Max Drawdown:          {metrics.get('Max Drawdown %', 0):.2f}%")
    print(f"Max Drawdown (USDT):   ${metrics.get('Max Drawdown USDT', 0):,.2f}")
    print(f"Sharpe Ratio:          {metrics.get('Sharpe Ratio', 0):.2f}")
    
    print("\n" + "="*70)
    
    # Check if targets are met
    total_return = metrics.get('Total Return %', 0)
    max_dd = abs(metrics.get('Max Drawdown %', 0))
    
    print("\n--- TARGET ASSESSMENT ---")
    target_return_met = total_return >= 30
    target_dd_met = max_dd <= 20
    
    print(f"Annual Return Target (≥30%):    {'✓ PASS' if target_return_met else '✗ FAIL'} ({total_return:.2f}%)")
    print(f"Max Drawdown Target (≤20%):     {'✓ PASS' if target_dd_met else '✗ FAIL'} ({max_dd:.2f}%)")
    
    if target_return_met and target_dd_met:
        print("\n🎉 Strategy meets all performance targets!")
    else:
        print("\n⚠️  Strategy does not meet all performance targets.")
    
    print("="*70 + "\n")

def save_trade_log(trades, filename='trade_log.csv'):
    """Save trade log to CSV file"""
    print(f"Saving trade log to {filename}...")
    
    if not trades:
        print("No trades to save.")
        return
    
    trade_data = []
    for t in trades:
        trade_data.append({
            'Trade#': t.trade_num,
            'Type': t.type,
            'EntryDate': t.entry_date,
            'EntryPrice': f"{t.entry_price:.2f}",
            'ExitDate': t.exit_date,
            'ExitPrice': f"{t.exit_price:.2f}",
            'PositionSize': f"{t.position_size:.6f}",
            'PnL_USDT': f"{t.pnl_usdt:.2f}",
            'PnL_Percent': f"{t.pnl_percent:.2f}",
            'Commission': f"{t.commission:.2f}",
            'NetPnL': f"{t.net_pnl:.2f}"
        })
    
    df = pd.DataFrame(trade_data)
    df.to_csv(filename, index=False)
    print(f"Trade log saved successfully ({len(trades)} trades).")

def save_equity_curve(equity_curve, filename='equity_curve.csv'):
    """Save equity curve to CSV file"""
    print(f"Saving equity curve to {filename}...")
    
    df = pd.DataFrame(equity_curve)
    df['Equity'] = df['Equity'].round(2)
    df['DrawdownPercent'] = df['DrawdownPercent'].round(2)
    df.to_csv(filename, index=False)
    print(f"Equity curve saved successfully ({len(equity_curve)} data points).")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function"""
    print("="*70)
    print(" ETHUSDT TRADING STRATEGY BACKTEST")
    print("="*70)
    
    # Configuration
    DATA_FILE = 'ETHUSDT_15_Minutes_year_2025.txt'
    INITIAL_CAPITAL = 100000
    
    # Load data
    df = load_data(DATA_FILE)
    
    # Compute indicators
    df = compute_indicators(df)
    
    # Run backtest
    trades, equity_curve, final_capital = run_backtest(df, INITIAL_CAPITAL)
    
    # Calculate performance metrics
    metrics = calculate_performance_metrics(trades, equity_curve, INITIAL_CAPITAL, final_capital)
    
    # Print results
    print_results(metrics)
    
    # Save outputs
    save_trade_log(trades)
    save_equity_curve(equity_curve)
    
    print("\nBacktest completed successfully!")
    print("Output files created:")
    print("  - trade_log.csv")
    print("  - equity_curve.csv")

if __name__ == "__main__":
    main()
