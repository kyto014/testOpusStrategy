#!/usr/bin/env python3
"""
Backtest Strategy V5B-Fixed
Combines best of V5B (LONG) and V4 (SHORT) strategies

V5B LONG conditions:
- RSI < 33
- Close price < Lower Bollinger Band
- Volume > 1.8x Volume SMA 20
- Price change < -0.6%

V4 SHORT conditions (highly selective):
- RSI between 38 and 46 (bearish range, not extreme oversold)
- Volume > 1.8x Volume SMA 20
- Close price < Lower BB AND price change < -0.6% (both required)
- Close < BB middle (bearish market structure)
"""

import pandas as pd
import numpy as np
from datetime import datetime


class BacktestStrategy:
    def __init__(self, data_file, initial_balance=10000, position_size_pct=0.10, 
                 stop_loss_pct=0.03, take_profit_pct=0.05):
        """
        Initialize the backtesting strategy
        
        Args:
            data_file: Path to CSV data file
            initial_balance: Starting capital
            position_size_pct: Percentage of balance to use per trade (changed to 10% for better risk management)
            stop_loss_pct: Stop loss percentage
            take_profit_pct: Take profit percentage
        """
        self.data_file = data_file
        self.initial_balance = initial_balance
        self.position_size_pct = position_size_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
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
        
        # Bollinger Bands
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        
        # Volume SMA
        df['volume_sma_20'] = df['volume'].rolling(window=20).mean()
        
        # Price change percentage
        df['price_change_pct'] = df['close'].pct_change() * 100
        
        return df
    
    def calculate_rsi(self, prices, period=14):
        """Calculate RSI indicator"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
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
        V4 SHORT Entry Logic - Highly selective for ~36 quality trades
        
        Enter SHORT on specific bearish setup:
        1. RSI between 38 and 46 (specific bearish range, not extreme)
        2. Volume > Volume SMA 20 * 1.8 (high volume like LONG)
        3. Close < Lower BB (must be below BB)
        4. Price change < -0.6% (significant drop like LONG)
        5. Close < BB middle (bearish structure)
        
        Note: Very selective to match V4's ~36 trades with high PF
        """
        if pd.isna(row['rsi']) or pd.isna(row['bb_lower']) or pd.isna(row['volume_sma_20']) or pd.isna(row['bb_middle']):
            return False
        
        # 1. RSI in specific bearish range (not extreme oversold)
        rsi_condition = 38 <= row['rsi'] < 46
        
        # 2. Volume confirmation (high volume matching LONG)
        volume_condition = row['volume'] > row['volume_sma_20'] * 1.8
        
        # 3. Price below lower BB (required, not optional)
        price_below_bb = row['close'] < row['bb_lower']
        
        # 4. Significant price drop (matching LONG's -0.6%)
        significant_drop = row['price_change_pct'] < -0.6
        
        # 5. Bearish market structure
        market_bearish = row['close'] < row['bb_middle']
        
        return rsi_condition and volume_condition and price_below_bb and significant_drop and market_bearish
    
    def check_long_exit(self, row, entry_price):
        """
        LONG Exit Logic (from V5B)
        
        Exit conditions:
        1. Take profit: Price rises by take_profit_pct
        2. Stop loss: Price drops by stop_loss_pct
        3. RSI > 70 (overbought, take profit)
        """
        if pd.isna(row['rsi']):
            return False, None
        
        current_price = row['close']
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Take profit
        if profit_pct >= self.take_profit_pct * 100:
            return True, 'take_profit'
        
        # Stop loss
        if profit_pct <= -self.stop_loss_pct * 100:
            return True, 'stop_loss'
        
        # RSI overbought exit
        if row['rsi'] > 70:
            return True, 'rsi_overbought'
        
        return False, None
    
    def check_short_exit(self, row, entry_price):
        """
        SHORT Exit Logic (from V5B - NO CHANGES)
        
        Exit conditions:
        1. Take profit: Price drops by take_profit_pct (profit for short)
        2. Stop loss: Price rises by stop_loss_pct (loss for short)
        3. RSI < 30 (oversold, cover short)
        """
        if pd.isna(row['rsi']):
            return False, None
        
        current_price = row['close']
        # For short positions, profit when price goes down
        profit_pct = ((entry_price - current_price) / entry_price) * 100
        
        # Take profit
        if profit_pct >= self.take_profit_pct * 100:
            return True, 'take_profit'
        
        # Stop loss
        if profit_pct <= -self.stop_loss_pct * 100:
            return True, 'stop_loss'
        
        # RSI oversold exit (cover short)
        if row['rsi'] < 30:
            return True, 'rsi_oversold'
        
        return False, None
    
    def run_backtest(self):
        """Execute the backtest"""
        # Load and prepare data
        df = self.load_data()
        df = self.calculate_indicators(df)
        
        print(f"Backtesting V5B-Fixed Strategy")
        print(f"Data period: {df['timestamp'].min()} to {df['timestamp'].max()}")
        print(f"Total bars: {len(df)}")
        print(f"Initial balance: ${self.initial_balance:,.2f}\n")
        
        # Iterate through the data
        for idx, row in df.iterrows():
            # Skip if we don't have enough data for indicators
            if idx < 20:
                continue
            
            # Check for exit conditions if we have an open position
            if self.current_position is not None:
                position = self.current_position
                
                if position['side'] == 'LONG':
                    should_exit, exit_reason = self.check_long_exit(row, position['entry_price'])
                else:  # SHORT
                    should_exit, exit_reason = self.check_short_exit(row, position['entry_price'])
                
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
        """Open a new position"""
        entry_price = row['close']
        position_value = self.balance * self.position_size_pct
        
        if side == 'LONG':
            quantity = position_value / entry_price
        else:  # SHORT
            quantity = position_value / entry_price
        
        self.current_position = {
            'side': side,
            'entry_time': row['timestamp'],
            'entry_price': entry_price,
            'quantity': quantity,
            'position_value': position_value
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
            'pnl_pct': (pnl / position['position_value']) * 100,
            'exit_reason': exit_reason
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
        print("OVERALL RESULTS - V5B-Fixed Strategy")
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
            print("SHORT TRADES (V4 Conditions)")
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
    
    # Initialize and run backtest with 10% position sizing for better risk management
    backtest = BacktestStrategy(
        data_file=data_file,
        initial_balance=10000,
        position_size_pct=0.10,  # Changed from 0.95 to 0.10
        stop_loss_pct=0.03,
        take_profit_pct=0.05
    )
    
    backtest.run_backtest()


if __name__ == "__main__":
    main()
