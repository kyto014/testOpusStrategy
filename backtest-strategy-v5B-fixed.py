#!/usr/bin/env python3
"""
Backtest Strategy V5B-Fixed
Combines V5B LONG conditions with V4 SHORT conditions (exact parameters)

V5B LONG conditions (UNCHANGED):
- RSI < 33
- Close price < Lower Bollinger Band
- Volume > 1.8x Volume SMA 20
- Price change < -0.6%

SHORT conditions (EXACT V4 — PF 2.43, 58% WR, 36 trades):
1. EMA 10 < EMA 30 (V4 trend filter)
2. Close < EMA 10 (V4 price below trend)
3. Fast MACD (8,17,5) histogram < 0 AND declining (V4 momentum)
4. RSI < 50 (simple bearish territory)
5. Volume > 1.5× Volume SMA 20
6. Close < Lower BB OR price dropped > 0.5% (OR logic!)

V4 SHORT Risk Management (ATR-based):
- Risk per trade: 1.5% of capital
- Stop Loss: 0.8 × ATR
- Take Profit levels at 1.5×, 3.0×, and 5.0× ATR
- Trailing stop: 0.6 × ATR (when profitable)
- Max trade duration: 48 candles
"""

import pandas as pd
import numpy as np
from datetime import datetime


class BacktestStrategy:
    def __init__(self, data_file, initial_balance=10000, 
                 long_position_size_pct=0.10, long_stop_loss_pct=0.03, long_take_profit_pct=0.05,
                 short_risk_pct=0.015):
        """
        Initialize the backtesting strategy
        
        Args:
            data_file: Path to CSV data file
            initial_balance: Starting capital
            long_position_size_pct: Position size for LONG trades (V5B)
            long_stop_loss_pct: Stop loss % for LONG trades (V5B)
            long_take_profit_pct: Take profit % for LONG trades (V5B)
            short_risk_pct: Risk per SHORT trade as % of capital (V4: 1.5% = 0.015)
        """
        self.data_file = data_file
        self.initial_balance = initial_balance
        self.long_position_size_pct = long_position_size_pct
        self.long_stop_loss_pct = long_stop_loss_pct
        self.long_take_profit_pct = long_take_profit_pct
        self.short_risk_pct = short_risk_pct
        
        self.balance = initial_balance
        self.positions = []
        self.trades = []
        self.current_position = None
        
    def load_data(self):
        """Load and prepare market data"""
        # Read the data file - CSV format with date and time columns
        df = pd.read_csv(self.data_file)
        
        # Clean column names (remove <> and spaces)
        df.columns = df.columns.str.strip().str.replace('<', '').str.replace('>', '').str.lower()
        
        # Combine date and time into timestamp
        df['timestamp'] = pd.to_datetime(df['date'] + ' ' + df['time'])
        
        # Rename columns to standard format
        df = df.rename(columns={
            'open': 'open',
            'high': 'high', 
            'low': 'low',
            'close': 'close',
            'volume': 'volume'
        })
        
        # Sort by timestamp
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        return df
    
    def calculate_indicators(self, df):
        """Calculate technical indicators"""
        # RSI calculation
        df['rsi'] = self.calculate_rsi(df['close'], period=14)
        
        # EMA indicators for V4 SHORT conditions
        df['ema_10'] = df['close'].ewm(span=10, adjust=False).mean()
        df['ema_30'] = df['close'].ewm(span=30, adjust=False).mean()
        
        # Bollinger Bands
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        
        # Volume SMA
        df['volume_sma_20'] = df['volume'].rolling(window=20).mean()
        
        # Price change percentage
        df['price_change_pct'] = df['close'].pct_change() * 100
        
        # Fast MACD (8,17,5) for V4 SHORT conditions
        fast_ema = df['close'].ewm(span=8, adjust=False).mean()
        slow_ema = df['close'].ewm(span=17, adjust=False).mean()
        df['fast_macd'] = fast_ema - slow_ema
        df['fast_macd_signal'] = df['fast_macd'].ewm(span=5, adjust=False).mean()
        df['fast_macd_hist'] = df['fast_macd'] - df['fast_macd_signal']
        df['prev_fast_macd_hist'] = df['fast_macd_hist'].shift(1)
        
        # ATR for V4 risk parameters
        df['atr'] = self.calculate_atr(df, period=14)
        
        return df
    
    def calculate_rsi(self, prices, period=14):
        """Calculate RSI indicator"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calculate_atr(self, df, period=14):
        """Calculate Average True Range (ATR) indicator"""
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean()
        
        return atr
    
    def check_long_entry(self, row):
        """
        V5B LONG Entry Logic
        
        Conditions:
        1. RSI < 33 (oversold)
        2. Close price < Lower Bollinger Band
        3. Volume > Volume SMA 20 * 1.8 (high volume)
        4. Price change < -0.6% (significant drop)
        """
        if pd.isna(row['rsi']) or pd.isna(row['bb_lower']) or pd.isna(row['volume_sma_20']):
            return False
        
        # 1. RSI oversold
        rsi_condition = row['rsi'] < 33
        
        # 2. Price below lower BB
        bb_condition = row['close'] < row['bb_lower']
        
        # 3. Volume confirmation
        volume_condition = row['volume'] > row['volume_sma_20'] * 1.8
        
        # 4. Price action: significant drop
        price_change_condition = row['price_change_pct'] < -0.6
        
        return rsi_condition and bb_condition and volume_condition and price_change_condition
    
    def check_short_entry(self, row):
        """
        SHORT Entry Logic - EXACT V4 conditions (PF 2.43, 58% WR, 36 trades)
        
        Entry requires ALL of the following:
        1. EMA 10 < EMA 30 (bearish trend)
        2. Close < EMA 10 (price below short-term trend)
        3. Fast MACD histogram < 0 AND declining (momentum confirmation)
        4. RSI < 50 (bearish territory - simple, no lower bound)
        5. Volume > 1.5× Volume SMA 20 (volume spike)
        6. Close < Lower BB OR price dropped > 0.5% (OR logic!)
        """
        if (pd.isna(row['rsi']) or pd.isna(row['bb_lower']) or pd.isna(row['volume_sma_20']) 
            or pd.isna(row['ema_10']) or pd.isna(row['ema_30'])
            or pd.isna(row['fast_macd_hist']) or pd.isna(row['prev_fast_macd_hist'])):
            return False
        
        # V4 trend indicators
        ema10_below_ema30 = row['ema_10'] < row['ema_30']
        close_below_ema10 = row['close'] < row['ema_10']
        fast_macd_bearish = row['fast_macd_hist'] < 0 and row['fast_macd_hist'] < row['prev_fast_macd_hist']
        
        # EXACT V4 filters
        rsi_condition = row['rsi'] < 50  # V4: simple RSI < 50, no lower bound
        volume_condition = row['volume'] > row['volume_sma_20'] * 1.5  # V4: 1.5x, not 1.8x
        breakdown = row['close'] < row['bb_lower'] or row['price_change_pct'] < -0.5  # V4: OR logic, -0.5%
        
        return all([ema10_below_ema30, close_below_ema10, fast_macd_bearish,
                   rsi_condition, volume_condition, breakdown])
    
    def check_long_exit(self, row, entry_price):
        """LONG Exit Logic (from V5B)"""
        if pd.isna(row['rsi']):
            return False, None
        
        current_price = row['close']
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Take profit
        if profit_pct >= self.long_take_profit_pct * 100:
            return True, 'take_profit'
        
        # Stop loss
        if profit_pct <= -self.long_stop_loss_pct * 100:
            return True, 'stop_loss'
        
        # RSI overbought exit
        if row['rsi'] > 70:
            return True, 'rsi_overbought'
        
        return False, None
    
    def check_short_exit(self, row, position):
        """SHORT Exit Logic - V4 ATR-based risk management"""
        if pd.isna(row['rsi']) or pd.isna(row['atr']):
            return False, None
        
        current_price = row['close']
        entry_price = position['entry_price']
        entry_atr = position.get('entry_atr', row['atr'])
        candles_held = position.get('candles_held', 0)
        best_price = position.get('best_price', current_price)
        
        # For short positions, profit when price goes down
        price_move = entry_price - current_price
        
        # Max trade duration: 48 candles
        if candles_held >= 48:
            return True, 'max_duration'
        
        # Stop Loss: 0.8 × ATR (price moved against us)
        stop_loss_distance = 0.8 * entry_atr
        if price_move < -stop_loss_distance:
            return True, 'stop_loss'
        
        # Take Profit levels (use the highest reached)
        tp1_distance = 1.5 * entry_atr
        tp2_distance = 3.0 * entry_atr
        tp3_distance = 5.0 * entry_atr
        
        # Check for take profits in order of highest first
        if price_move >= tp3_distance:
            return True, 'tp3'
        elif price_move >= tp2_distance:
            return True, 'tp2'
        elif price_move >= tp1_distance:
            return True, 'tp1'
        
        # Trailing stop: 0.6 × ATR from best price if we're profitable
        if price_move > 0:  # We're in profit
            trailing_distance = 0.6 * entry_atr
            pullback_from_best = best_price - current_price
            if pullback_from_best > trailing_distance:
                return True, 'trailing_stop'
        
        # RSI oversold exit (cover short)
        if row['rsi'] < 30:
            return True, 'rsi_oversold'
        
        return False, None
    
    def run_backtest(self):
        """Execute the backtest"""
        # Load and prepare data
        df = self.load_data()
        df = self.calculate_indicators(df)
        
        print(f"Backtesting V5B-Fixed Strategy with EXACT V4 SHORT conditions")
        print(f"Data period: {df['timestamp'].min()} to {df['timestamp'].max()}")
        print(f"Total bars: {len(df)}")
        print(f"Initial balance: ${self.initial_balance:,.2f}\n")
        
        # Iterate through the data
        for idx, row in df.iterrows():
            # Skip if we don't have enough data for indicators
            if idx < 30:  # Need more data for EMA 30
                continue
            
            # Update position tracking if we have an open position
            if self.current_position is not None:
                self.current_position['candles_held'] = self.current_position.get('candles_held', 0) + 1
                
                # Track best price for SHORT trailing stop
                if self.current_position['side'] == 'SHORT':
                    current_best = self.current_position.get('best_price', row['close'])
                    if row['close'] < current_best:
                        self.current_position['best_price'] = row['close']
            
            # Check for exit conditions if we have an open position
            if self.current_position is not None:
                position = self.current_position
                
                if position['side'] == 'LONG':
                    should_exit, exit_reason = self.check_long_exit(row, position['entry_price'])
                    if should_exit:
                        self.close_position(row, exit_reason)
                else:  # SHORT
                    should_exit, exit_reason = self.check_short_exit(row, position)
                    if should_exit:
                        self.close_position(row, exit_reason)
            
            # Check for entry conditions if no position
            if self.current_position is None:
                # Check LONG entry
                if self.check_long_entry(row):
                    self.open_position(row, 'LONG')
                
                # Check SHORT entry (only if no long position opened)
                elif self.check_short_entry(row):
                    self.open_position(row, 'SHORT')
        
        # Close any remaining position at the end
        if self.current_position is not None:
            last_row = df.iloc[-1]
            self.close_position(last_row, 'end_of_data')
        
        # Calculate and display results
        self.display_results()
    
    def open_position(self, row, side):
        """Open a new position with appropriate risk parameters"""
        entry_price = row['close']
        
        if side == 'LONG':
            # V5B LONG: 10% position sizing
            position_value = self.balance * self.long_position_size_pct
            quantity = position_value / entry_price
            
            self.current_position = {
                'side': side,
                'entry_time': row['timestamp'],
                'entry_price': entry_price,
                'quantity': quantity,
                'position_value': position_value,
                'candles_held': 0
            }
        else:  # SHORT
            # V4 SHORT: Calculate position size based on 1.5% risk and 0.8 ATR stop loss
            risk_amount = self.balance * self.short_risk_pct
            atr = row['atr']
            stop_loss_distance = 0.8 * atr
            
            # Position size = Risk / Stop Loss Distance
            quantity = risk_amount / stop_loss_distance
            position_value = quantity * entry_price
            
            self.current_position = {
                'side': side,
                'entry_time': row['timestamp'],
                'entry_price': entry_price,
                'quantity': quantity,
                'position_value': position_value,
                'entry_atr': atr,
                'candles_held': 0,
                'best_price': entry_price
            }
        
        # Deduct from balance (simulating margin)
        self.balance -= position_value
    
    def close_position(self, row, exit_reason):
        """Close the current position"""
        if self.current_position is None:
            return
        
        position = self.current_position
        exit_price = row['close']
        
        # Calculate profit/loss
        if position['side'] == 'LONG':
            pnl = (exit_price - position['entry_price']) * position['quantity']
        else:  # SHORT
            pnl = (position['entry_price'] - exit_price) * position['quantity']
        
        # Update balance
        self.balance += position['position_value'] + pnl
        
        # Record trade
        trade = {
            'side': position['side'],
            'entry_time': position['entry_time'],
            'exit_time': row['timestamp'],
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'quantity': position['quantity'],
            'pnl': pnl,
            'pnl_pct': (pnl / position['position_value']) * 100 if position['position_value'] > 0 else 0,
            'exit_reason': exit_reason,
            'candles_held': position.get('candles_held', 0)
        }
        
        self.trades.append(trade)
        self.current_position = None
    
    def display_results(self):
        """Display backtest results"""
        if not self.trades:
            print("No trades executed")
            return
        
        df_trades = pd.DataFrame(self.trades)
        
        # Overall statistics
        total_trades = len(df_trades)
        winning_trades = len(df_trades[df_trades['pnl'] > 0])
        losing_trades = len(df_trades[df_trades['pnl'] <= 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        total_profit = df_trades[df_trades['pnl'] > 0]['pnl'].sum()
        total_loss = abs(df_trades[df_trades['pnl'] <= 0]['pnl'].sum())
        profit_factor = (total_profit / total_loss) if total_loss > 0 else float('inf')
        
        net_profit = df_trades['pnl'].sum()
        total_return = ((self.balance - self.initial_balance) / self.initial_balance) * 100
        
        # Calculate drawdown
        cumulative_pnl = df_trades['pnl'].cumsum()
        running_max = cumulative_pnl.cummax()
        drawdown = cumulative_pnl - running_max
        max_drawdown_value = drawdown.min()
        max_drawdown_pct = (max_drawdown_value / self.initial_balance) * 100
        
        print("\n" + "="*70)
        print("OVERALL RESULTS - V5B-Fixed Strategy (EXACT V4 SHORT conditions)")
        print("="*70)
        print(f"Total Trades: {total_trades}")
        print(f"Winning Trades: {winning_trades}")
        print(f"Losing Trades: {losing_trades}")
        print(f"Win Rate: {win_rate:.2f}%")
        print(f"Profit Factor: {profit_factor:.2f}")
        print(f"Net Profit: ${net_profit:,.2f}")
        print(f"Total Return: {total_return:.2f}%")
        print(f"Final Balance: ${self.balance:,.2f}")
        print(f"Max Drawdown: ${max_drawdown_value:,.2f} ({max_drawdown_pct:.2f}%)")
        
        # LONG statistics
        long_trades = df_trades[df_trades['side'] == 'LONG']
        if len(long_trades) > 0:
            long_winning = len(long_trades[long_trades['pnl'] > 0])
            long_wr = (long_winning / len(long_trades) * 100)
            long_profit = long_trades[long_trades['pnl'] > 0]['pnl'].sum()
            long_loss = abs(long_trades[long_trades['pnl'] <= 0]['pnl'].sum())
            long_pf = (long_profit / long_loss) if long_loss > 0 else float('inf')
            
            print("\n" + "-"*70)
            print("LONG TRADES (V5B Conditions)")
            print("-"*70)
            print(f"Total: {len(long_trades)}")
            print(f"Winning: {long_winning}")
            print(f"Win Rate: {long_wr:.2f}%")
            print(f"Profit Factor: {long_pf:.2f}")
            print(f"Net P&L: ${long_trades['pnl'].sum():,.2f}")
        
        # SHORT statistics
        short_trades = df_trades[df_trades['side'] == 'SHORT']
        if len(short_trades) > 0:
            short_winning = len(short_trades[short_trades['pnl'] > 0])
            short_wr = (short_winning / len(short_trades) * 100)
            short_profit = short_trades[short_trades['pnl'] > 0]['pnl'].sum()
            short_loss = abs(short_trades[short_trades['pnl'] <= 0]['pnl'].sum())
            short_pf = (short_profit / short_loss) if short_loss > 0 else float('inf')
            
            print("\n" + "-"*70)
            print("SHORT TRADES (EXACT V4 Conditions)")
            print("-"*70)
            print(f"Total: {len(short_trades)}")
            print(f"Winning: {short_winning}")
            print(f"Win Rate: {short_wr:.2f}%")
            print(f"Profit Factor: {short_pf:.2f}")
            print(f"Net P&L: ${short_trades['pnl'].sum():,.2f}")
        
        print("\n" + "="*70)
        
        # Display sample trades
        print("\nFirst 5 Trades:")
        print(df_trades[['side', 'entry_time', 'entry_price', 'exit_price', 'pnl', 'pnl_pct', 'exit_reason']].head(5).to_string(index=False))
        
        print("\nLast 5 Trades:")
        print(df_trades[['side', 'entry_time', 'entry_price', 'exit_price', 'pnl', 'pnl_pct', 'exit_reason']].tail(5).to_string(index=False))


def main():
    """Main execution function"""
    # Configuration
    data_file = '/home/runner/work/testOpusStrategy/testOpusStrategy/ETHUSDT_15_Minutes_year_2025.txt'
    
    # Initialize and run backtest with V5B LONG and EXACT V4 SHORT parameters
    backtest = BacktestStrategy(
        data_file=data_file,
        initial_balance=10000,
        long_position_size_pct=0.10,  # V5B LONG: 10% position sizing
        long_stop_loss_pct=0.03,      # V5B LONG: 3% stop loss
        long_take_profit_pct=0.05,    # V5B LONG: 5% take profit
        short_risk_pct=0.015          # V4 SHORT: 1.5% risk per trade
    )
    
    backtest.run_backtest()


if __name__ == "__main__":
    main()