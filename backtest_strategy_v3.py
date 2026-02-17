#!/usr/bin/env python3
"""
Adaptive Regime-Switching Strategy V3 for ETHUSDT
Automatically switches between trend-following and mean-reversion based on market regime detection.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import csv


class AdaptiveStrategyV3:
    """Adaptive regime-switching strategy that uses trend-following in trending markets
    and mean-reversion in ranging markets."""
    
    def __init__(self, initial_capital: float = 100000.0):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.positions = []
        self.trades = []
        self.equity_curve = []
        self.commission_rate = 0.0005  # 0.05%
        
        # Risk parameters  
        self.trend_risk_pct = 0.015  # 1.5% for trend trades
        self.mean_reversion_risk_pct = 0.015  # 1.5% for mean reversion
        self.transitioning_multiplier = 0.0  # Don't trade in transitioning regime
        self.max_positions = 2
        self.max_daily_loss_pct = 0.03  # 3%
        self.max_weekly_loss_pct = 0.05  # 5%
        self.stale_trade_candles = 80  # 20 hours = 80 * 15min (shorter timeout)
        
        # State tracking
        self.daily_pnl = 0.0
        self.weekly_pnl = 0.0
        self.last_date = None
        self.week_start_equity = initial_capital
        self.day_start_equity = initial_capital
        
    def calculate_ema(self, data: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average."""
        return data.ewm(span=period, adjust=False).mean()
    
    def calculate_sma(self, data: pd.Series, period: int) -> pd.Series:
        """Calculate Simple Moving Average."""
        return data.rolling(window=period).mean()
    
    def calculate_rsi(self, data: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index."""
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Average True Range."""
        high_low = high - low
        high_close = np.abs(high - close.shift())
        low_close = np.abs(low - close.shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(window=period).mean()
        return atr
    
    def calculate_macd(self, data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate MACD, Signal line, and Histogram."""
        ema_fast = self.calculate_ema(data, fast)
        ema_slow = self.calculate_ema(data, slow)
        macd_line = ema_fast - ema_slow
        signal_line = self.calculate_ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    def calculate_bollinger_bands(self, data: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Bollinger Bands."""
        middle = self.calculate_sma(data, period)
        std = data.rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        return upper, middle, lower
    
    def calculate_adx(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Average Directional Index."""
        # Calculate +DM and -DM
        high_diff = high.diff()
        low_diff = -low.diff()
        
        plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0)
        minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0)
        
        # Calculate ATR
        atr = self.calculate_atr(high, low, close, period)
        
        # Calculate +DI and -DI
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
        
        # Calculate DX and ADX
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()
        
        return adx
    
    def detect_regime(self, row: pd.Series, bb_width_median: float) -> str:
        """Detect market regime: TRENDING, RANGING, or TRANSITIONING."""
        adx = row['ADX']
        bb_width = row['BB_Width']
        
        # TRENDING: Strong trend
        if adx > 27 and bb_width > bb_width_median:
            return 'TRENDING'
        
        # RANGING: Clear ranging market
        elif adx < 20 and bb_width < bb_width_median:
            return 'RANGING'
        
        # TRANSITIONING: Everything else - avoid trading
        else:
            return 'TRANSITIONING'
    
    def get_session_multiplier(self, hour: int) -> float:
        """Get position size multiplier based on hour of day (UTC)."""
        if 8 <= hour < 11 or 13 <= hour < 17:  # EU session open or US session
            return 1.0
        elif 6 <= hour < 8 or 17 <= hour < 21:
            return 0.8
        elif 21 <= hour < 24 or 0 <= hour < 6:
            return 0.6
        else:
            return 0.6
    
    def check_day_filter(self, dt: datetime) -> Tuple[bool, bool]:
        """Check if trading is allowed and if positions should be closed.
        Returns: (can_open_new, must_close_all)"""
        weekday = dt.weekday()  # Monday=0, Sunday=6
        hour = dt.hour
        
        # No trading on Saturday (5) and Sunday (6)
        if weekday >= 5:
            return False, True
        
        # Friday (4) restrictions
        if weekday == 4:
            if hour >= 20:  # Close all by 20:00 UTC
                return False, True
            elif hour >= 18:  # No new positions after 18:00 UTC
                return False, False
        
        return True, False
    
    def check_trend_long_entry(self, row: pd.Series, prev_row: pd.Series) -> bool:
        """Check if trend-following long entry conditions are met."""
        # All EMAs aligned bullishly - strong confirmation
        if not (row['EMA_20'] > row['EMA_50'] > row['EMA_100'] > row['EMA_200']):
            return False
        
        # Price above EMA 20
        if row['Close'] <= row['EMA_20']:
            return False
        
        # MACD histogram > 0 AND rising significantly
        if row['MACD_Hist'] <= 0 or row['MACD_Hist'] <= prev_row['MACD_Hist'] * 1.02:
            return False
        
        # RSI in uptrend zone
        if not (50 <= row['RSI'] <= 75):
            return False
        
        # Volume confirmation - strong buying
        if row['Volume'] <= row['Volume_SMA'] * 1.2:
            return False
        
        # ADX confirms strong trend
        if row['ADX'] <= 27:
            return False
        
        # Price action: recent higher highs
        if not (row['High'] > prev_row['High']):
            return False
        
        return True
    
    def check_trend_short_entry(self, row: pd.Series, prev_row: pd.Series) -> bool:
        """Check if trend-following short entry conditions are met."""
        # All EMAs aligned bearishly - strong confirmation
        if not (row['EMA_20'] < row['EMA_50'] < row['EMA_100'] < row['EMA_200']):
            return False
        
        # Price below EMA 20
        if row['Close'] >= row['EMA_20']:
            return False
        
        # MACD histogram < 0 AND falling significantly
        if row['MACD_Hist'] >= 0 or row['MACD_Hist'] >= prev_row['MACD_Hist'] * 0.98:
            return False
        
        # RSI in downtrend zone
        if not (25 <= row['RSI'] <= 50):
            return False
        
        # Volume confirmation - strong selling
        if row['Volume'] <= row['Volume_SMA'] * 1.2:
            return False
        
        # ADX confirms strong trend
        if row['ADX'] <= 27:
            return False
        
        # Price action: recent lower lows
        # Check if we're making lower lows (bearish momentum)
        if not (row['Low'] < prev_row['Low']):
            return False
        
        return True
    
    def check_mean_reversion_long_entry(self, row: pd.Series, prev_row: pd.Series) -> bool:
        """Check if mean-reversion long entry conditions are met."""
        # Price below or at Lower BB
        if row['Close'] > row['BB_Lower'] * 1.005:
            return False
        
        # RSI oversold
        if row['RSI'] >= 30:
            return False
        
        # RSI turning up
        if prev_row['RSI'] >= row['RSI']:
            return False
        
        # Not in strong trend
        if row['ADX'] >= 27:
            return False
        
        return True
    
    def check_mean_reversion_short_entry(self, row: pd.Series, prev_row: pd.Series) -> bool:
        """Check if mean-reversion short entry conditions are met."""
        # Price above or at Upper BB
        if row['Close'] < row['BB_Upper'] * 0.995:
            return False
        
        # RSI overbought
        if row['RSI'] <= 70:
            return False
        
        # RSI turning down
        if prev_row['RSI'] <= row['RSI']:
            return False
        
        # Not in strong trend
        if row['ADX'] >= 27:
            return False
        
        return True
    
    def calculate_position_size(self, price: float, stop_loss: float, risk_pct: float, 
                               regime: str, session_multiplier: float) -> float:
        """Calculate position size based on risk percentage and current regime."""
        risk_amount = self.capital * risk_pct
        price_risk = abs(price - stop_loss)
        
        if price_risk == 0:
            return 0
        
        position_size = risk_amount / price_risk
        
        # Apply regime multiplier
        if regime == 'TRANSITIONING':
            position_size *= self.transitioning_multiplier
        
        # Apply session multiplier
        position_size *= session_multiplier
        
        return position_size
    
    def open_position(self, idx: int, row: pd.Series, signal_type: str, direction: str, 
                     regime: str, session_multiplier: float):
        """Open a new position."""
        entry_price = row['Close']
        atr = row['ATR']
        
        # Determine risk parameters based on signal type and regime
        if signal_type == 'TrendFollow':
            risk_pct = self.trend_risk_pct
            if regime == 'TRANSITIONING':
                sl_multiplier = 1.8
            else:
                sl_multiplier = 2.8  # Wide SL (2.8 x ATR) to avoid premature stops in volatile trends
            tp1_mult = 2.2
            tp2_mult = 4.0
            tp3_mult = 6.5
        else:  # MeanReversion
            risk_pct = self.mean_reversion_risk_pct
            if regime == 'TRANSITIONING':
                sl_multiplier = 2.2
            else:
                sl_multiplier = 3.5  # Wider SL (3.5 x ATR) - mean reversion needs room for price to return to mean
            tp1_mult = 0.7  # Quick first target
            tp2_mult = 1.4  # Second target
            tp3_mult = None
        
        # Calculate stop loss and take profits
        if direction == 'LONG':
            stop_loss = entry_price - (atr * sl_multiplier)
            tp1 = entry_price + (atr * tp1_mult)
            tp2 = entry_price + (atr * tp2_mult)
            tp3 = entry_price + (atr * tp3_mult) if tp3_mult else None
        else:  # SHORT
            stop_loss = entry_price + (atr * sl_multiplier)
            tp1 = entry_price - (atr * tp1_mult)
            tp2 = entry_price - (atr * tp2_mult)
            tp3 = entry_price - (atr * tp3_mult) if tp3_mult else None
        
        # Calculate position size
        position_size = self.calculate_position_size(entry_price, stop_loss, risk_pct, 
                                                     regime, session_multiplier)
        
        if position_size <= 0:
            return
        
        # Calculate commission
        position_value = position_size * entry_price
        commission = position_value * self.commission_rate
        
        position = {
            'entry_idx': idx,
            'entry_date': row['DateTime'],
            'entry_price': entry_price,
            'direction': direction,
            'signal_type': signal_type,
            'regime': regime,
            'size': position_size,
            'stop_loss': stop_loss,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'tp1_hit': False,
            'tp2_hit': False,
            'remaining_size': position_size,
            'entry_commission': commission,
            'session_multiplier': session_multiplier,
            'trailing_stop': None,
            'breakeven_moved': False
        }
        
        self.positions.append(position)
        self.capital -= commission
    
    def close_position(self, position: Dict, idx: int, row: pd.Series, 
                      exit_reason: str, partial: float = 1.0):
        """Close a position (fully or partially)."""
        exit_price = row['Close']
        close_size = position['remaining_size'] * partial
        
        if close_size <= 0:
            return 0
        
        # Calculate P&L
        if position['direction'] == 'LONG':
            pnl_per_unit = exit_price - position['entry_price']
        else:  # SHORT
            pnl_per_unit = position['entry_price'] - exit_price
        
        gross_pnl = pnl_per_unit * close_size
        
        # Calculate exit commission
        position_value = close_size * exit_price
        exit_commission = position_value * self.commission_rate
        
        net_pnl = gross_pnl - exit_commission
        
        # Update capital
        self.capital += net_pnl
        
        # Update daily and weekly P&L
        self.daily_pnl += net_pnl
        self.weekly_pnl += net_pnl
        
        # Record trade if fully closed
        if partial >= 0.99:  # Fully closed
            duration_candles = idx - position['entry_idx']
            duration_hours = duration_candles * 0.25  # 15min = 0.25 hours
            
            total_commission = position['entry_commission'] + exit_commission
            total_pnl = gross_pnl - position['entry_commission'] - exit_commission
            pnl_pct = (total_pnl / (position['size'] * position['entry_price'])) * 100
            
            trade = {
                'regime': position['regime'],
                'signal_type': position['signal_type'],
                'direction': position['direction'],
                'entry_date': position['entry_date'],
                'entry_price': position['entry_price'],
                'exit_date': row['DateTime'],
                'exit_price': exit_price,
                'size': position['size'],
                'pnl_usdt': gross_pnl,
                'pnl_pct': pnl_pct,
                'commission': total_commission,
                'net_pnl': total_pnl,
                'duration_hours': duration_hours,
                'exit_reason': exit_reason,
                'session_multiplier': position['session_multiplier']
            }
            
            self.trades.append(trade)
            return net_pnl
        else:
            # Partial close - update remaining size
            position['remaining_size'] -= close_size
            return net_pnl
    
    def check_exits(self, position: Dict, idx: int, row: pd.Series, 
                   prev_row: pd.Series, regime: str) -> Optional[str]:
        """Check exit conditions for a position. Returns exit reason if should exit."""
        price = row['Close']
        direction = position['direction']
        
        # 1. Stop Loss hit
        if direction == 'LONG' and price <= position['stop_loss']:
            return 'StopLoss'
        elif direction == 'SHORT' and price >= position['stop_loss']:
            return 'StopLoss'
        
        # 2. TP1 hit
        if not position['tp1_hit']:
            if direction == 'LONG' and price >= position['tp1']:
                position['tp1_hit'] = True
                # Close 50% for trend, 60% for mean reversion
                partial = 0.5 if position['signal_type'] == 'TrendFollow' else 0.6
                self.close_position(position, idx, row, 'TP1', partial)
                # Move SL to breakeven
                position['stop_loss'] = position['entry_price']
                position['breakeven_moved'] = True
                return None
            elif direction == 'SHORT' and price <= position['tp1']:
                position['tp1_hit'] = True
                partial = 0.4 if position['signal_type'] == 'TrendFollow' else 0.5
                self.close_position(position, idx, row, 'TP1', partial)
                position['stop_loss'] = position['entry_price']
                position['breakeven_moved'] = True
                return None
        
        # 3. TP2 hit
        if position['tp1_hit'] and not position['tp2_hit']:
            if direction == 'LONG' and price >= position['tp2']:
                position['tp2_hit'] = True
                # Close 35% for trend, 40% for mean reversion  
                partial = 0.35 if position['signal_type'] == 'TrendFollow' else 0.4
                self.close_position(position, idx, row, 'TP2', partial)
                # Activate trailing stop at 1.0 * ATR
                position['trailing_stop'] = price - row['ATR']
                return None
            elif direction == 'SHORT' and price <= position['tp2']:
                position['tp2_hit'] = True
                partial = 0.3 if position['signal_type'] == 'TrendFollow' else 0.5
                self.close_position(position, idx, row, 'TP2', partial)
                position['trailing_stop'] = price + row['ATR']
                return None
        
        # 4. TP3 hit (trend trades only)
        if position['tp3'] and position['tp2_hit']:
            if direction == 'LONG' and price >= position['tp3']:
                return 'TP3'
            elif direction == 'SHORT' and price <= position['tp3']:
                return 'TP3'
        
        # 5. Trailing stop hit
        if position['trailing_stop']:
            if direction == 'LONG':
                # Update trailing stop
                new_trail = price - row['ATR']
                if new_trail > position['trailing_stop']:
                    position['trailing_stop'] = new_trail
                # Check if hit
                if price <= position['trailing_stop']:
                    return 'TrailingStop'
            else:  # SHORT
                new_trail = price + row['ATR']
                if new_trail < position['trailing_stop']:
                    position['trailing_stop'] = new_trail
                if price >= position['trailing_stop']:
                    return 'TrailingStop'
        
        # 6. Counter-signal (optional - not implementing to avoid over-trading)
        
        # 7. RSI extreme
        if direction == 'LONG' and row['RSI'] > 85:
            return 'RSI_Extreme'
        elif direction == 'SHORT' and row['RSI'] < 15:
            return 'RSI_Extreme'
        
        # 8. Regime change exit (tighten SL only, don't force close)
        if position['regime'] == 'TRENDING' and regime == 'RANGING':
            tighter_sl = position['entry_price'] + (row['ATR'] * 0.5 * (-1 if direction == 'LONG' else 1))
            if direction == 'LONG' and tighter_sl > position['stop_loss']:
                position['stop_loss'] = tighter_sl
            elif direction == 'SHORT' and tighter_sl < position['stop_loss']:
                position['stop_loss'] = tighter_sl
        
        # 9. Stale trade
        duration_candles = idx - position['entry_idx']
        if duration_candles >= self.stale_trade_candles:
            return 'StaleTimeout'
        
        return None
    
    def run_backtest(self, data: pd.DataFrame):
        """Run the complete backtest."""
        print("Starting Adaptive Regime-Switching Strategy V3 Backtest...")
        print(f"Initial Capital: ${self.initial_capital:,.2f}")
        print(f"Data Range: {data['DateTime'].iloc[0]} to {data['DateTime'].iloc[-1]}")
        print(f"Total Candles: {len(data)}")
        print()
        
        # Calculate BB Width median for regime detection
        bb_width_median = data['BB_Width'].rolling(window=100).median()
        
        for idx in range(200, len(data)):  # Start after warmup period
            row = data.iloc[idx]
            prev_row = data.iloc[idx - 1]
            
            # Update equity curve
            equity = self.capital
            for pos in self.positions:
                if pos['direction'] == 'LONG':
                    unrealized = (row['Close'] - pos['entry_price']) * pos['remaining_size']
                else:
                    unrealized = (pos['entry_price'] - row['Close']) * pos['remaining_size']
                equity += unrealized
            
            # Calculate drawdown
            max_equity = max([e['equity'] for e in self.equity_curve] + [self.initial_capital])
            drawdown_pct = ((max_equity - equity) / max_equity) * 100 if max_equity > 0 else 0
            
            self.equity_curve.append({
                'datetime': row['DateTime'],
                'equity': equity,
                'drawdown_pct': drawdown_pct,
                'regime': row['Regime']
            })
            
            # Check daily/weekly reset
            current_date = row['DateTime'].date()
            if self.last_date and current_date != self.last_date:
                self.daily_pnl = 0.0
                self.day_start_equity = equity
                
                # Check if new week using ISO week number
                if row['DateTime'].isocalendar()[1] != pd.Timestamp(self.last_date).isocalendar()[1]:
                    self.weekly_pnl = 0.0
                    self.week_start_equity = equity
            
            self.last_date = current_date
            
            # Check max loss limits
            if self.daily_pnl / self.day_start_equity < -self.max_daily_loss_pct:
                continue  # Pause trading for rest of day
            
            if self.weekly_pnl / self.week_start_equity < -self.max_weekly_loss_pct:
                continue  # Pause trading for rest of week
            
            # Check day filter
            can_open, must_close = self.check_day_filter(row['DateTime'])
            
            # Force close all positions if required
            if must_close:
                for pos in self.positions[:]:
                    self.close_position(pos, idx, row, 'FridayClose')
                    self.positions.remove(pos)
                continue
            
            # Check exits for existing positions
            regime = row['Regime']
            for pos in self.positions[:]:
                exit_reason = self.check_exits(pos, idx, row, prev_row, regime)
                if exit_reason:
                    self.close_position(pos, idx, row, exit_reason)
                    self.positions.remove(pos)
            
            # Check for new entries
            if not can_open:
                continue
            
            if len(self.positions) >= self.max_positions:
                continue
            
            session_multiplier = self.get_session_multiplier(row['DateTime'].hour)
            
            # TRENDING regime - use trend following
            # In a bearish year, prioritize shorts
            if regime == 'TRENDING':
                if self.check_trend_short_entry(row, prev_row):
                    self.open_position(idx, row, 'TrendFollow', 'SHORT', regime, session_multiplier)
                elif self.check_trend_long_entry(row, prev_row):
                    # Be more cautious with longs in bearish market
                    if row['Close'] > row['EMA_200']:  # Only if structurally bullish
                        self.open_position(idx, row, 'TrendFollow', 'LONG', regime, session_multiplier)
            
            # RANGING regime - use mean reversion
            elif regime == 'RANGING':
                if self.check_mean_reversion_long_entry(row, prev_row):
                    self.open_position(idx, row, 'MeanReversion', 'LONG', regime, session_multiplier)
                elif self.check_mean_reversion_short_entry(row, prev_row):
                    self.open_position(idx, row, 'MeanReversion', 'SHORT', regime, session_multiplier)
            
            # TRANSITIONING regime - don't trade
            elif regime == 'TRANSITIONING':
                pass  # Skip
        
        # Close any remaining positions at end
        if self.positions:
            final_row = data.iloc[-1]
            for pos in self.positions[:]:
                self.close_position(pos, len(data) - 1, final_row, 'EndOfData')
                self.positions.remove(pos)
        
        print(f"Backtest completed. Final equity: ${self.capital:,.2f}")
        print(f"Total trades: {len(self.trades)}")
    
    def calculate_metrics(self) -> Dict:
        """Calculate performance metrics."""
        if not self.trades:
            return {}
        
        df_trades = pd.DataFrame(self.trades)
        
        # Basic metrics
        total_trades = len(df_trades)
        winning_trades = len(df_trades[df_trades['net_pnl'] > 0])
        losing_trades = len(df_trades[df_trades['net_pnl'] < 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # P&L metrics
        total_pnl = df_trades['net_pnl'].sum()
        total_return_pct = (total_pnl / self.initial_capital) * 100
        
        # Drawdown
        equity_df = pd.DataFrame(self.equity_curve)
        max_drawdown_pct = equity_df['drawdown_pct'].max()
        max_drawdown_usdt = equity_df['equity'].max() - equity_df['equity'].min()
        
        # Risk metrics
        gross_profit = df_trades[df_trades['net_pnl'] > 0]['net_pnl'].sum()
        gross_loss = abs(df_trades[df_trades['net_pnl'] < 0]['net_pnl'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Sharpe ratio (annualized)
        equity_df['returns'] = equity_df['equity'].pct_change()
        daily_returns = equity_df.groupby(equity_df['datetime'].dt.date)['returns'].sum()
        sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(365) if daily_returns.std() > 0 else 0
        
        # Best and worst trades
        best_trade = df_trades['net_pnl'].max()
        worst_trade = df_trades['net_pnl'].min()
        
        # By regime
        regime_stats = {}
        for regime in ['TRENDING', 'RANGING', 'TRANSITIONING']:
            regime_trades = df_trades[df_trades['regime'] == regime]
            if len(regime_trades) > 0:
                regime_stats[regime] = {
                    'count': len(regime_trades),
                    'win_rate': (len(regime_trades[regime_trades['net_pnl'] > 0]) / len(regime_trades) * 100),
                    'total_pnl': regime_trades['net_pnl'].sum(),
                    'avg_duration': regime_trades['duration_hours'].mean(),
                    'profit_factor': (regime_trades[regime_trades['net_pnl'] > 0]['net_pnl'].sum() / 
                                     abs(regime_trades[regime_trades['net_pnl'] < 0]['net_pnl'].sum())
                                     if abs(regime_trades[regime_trades['net_pnl'] < 0]['net_pnl'].sum()) > 0 else 0)
                }
        
        # By signal type
        signal_stats = {}
        for signal in ['TrendFollow', 'MeanReversion']:
            signal_trades = df_trades[df_trades['signal_type'] == signal]
            if len(signal_trades) > 0:
                signal_stats[signal] = {
                    'count': len(signal_trades),
                    'win_rate': (len(signal_trades[signal_trades['net_pnl'] > 0]) / len(signal_trades) * 100),
                    'total_pnl': signal_trades['net_pnl'].sum()
                }
        
        # By direction
        long_trades = df_trades[df_trades['direction'] == 'LONG']
        short_trades = df_trades[df_trades['direction'] == 'SHORT']
        
        # Monthly returns
        df_trades['month'] = pd.to_datetime(df_trades['exit_date']).dt.to_period('M')
        monthly_pnl = df_trades.groupby('month')['net_pnl'].sum()
        
        # Day of week
        df_trades['day_of_week'] = pd.to_datetime(df_trades['exit_date']).dt.day_name()
        day_pnl = df_trades.groupby('day_of_week')['net_pnl'].sum()
        
        # Hour of day
        df_trades['hour'] = pd.to_datetime(df_trades['exit_date']).dt.hour
        hour_pnl = df_trades.groupby('hour')['net_pnl'].sum()
        
        # Regime distribution
        regime_dist = equity_df.groupby('regime').size() / len(equity_df) * 100
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_return_pct': total_return_pct,
            'max_drawdown_pct': max_drawdown_pct,
            'max_drawdown_usdt': max_drawdown_usdt,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe,
            'best_trade': best_trade,
            'worst_trade': worst_trade,
            'regime_stats': regime_stats,
            'signal_stats': signal_stats,
            'long_trades': len(long_trades),
            'short_trades': len(short_trades),
            'long_pnl': long_trades['net_pnl'].sum() if len(long_trades) > 0 else 0,
            'short_pnl': short_trades['net_pnl'].sum() if len(short_trades) > 0 else 0,
            'monthly_pnl': monthly_pnl,
            'day_pnl': day_pnl,
            'hour_pnl': hour_pnl,
            'regime_dist': regime_dist,
            'final_equity': self.capital
        }
    
    def print_results(self, metrics: Dict):
        """Print detailed results."""
        print("\n" + "="*80)
        print("ADAPTIVE REGIME-SWITCHING STRATEGY V3 - FINAL RESULTS")
        print("="*80)
        
        print("\n--- OVERALL PERFORMANCE ---")
        print(f"Total Return: {metrics['total_return_pct']:.2f}% (${metrics['total_pnl']:,.2f})")
        print(f"Final Equity: ${metrics['final_equity']:,.2f}")
        print(f"Max Drawdown: {metrics['max_drawdown_pct']:.2f}% (${metrics['max_drawdown_usdt']:,.2f})")
        print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        print(f"Profit Factor: {metrics['profit_factor']:.2f}")
        
        print("\n--- TRADE STATISTICS ---")
        print(f"Total Trades: {metrics['total_trades']}")
        print(f"Winning Trades: {metrics['winning_trades']}")
        print(f"Losing Trades: {metrics['losing_trades']}")
        print(f"Win Rate: {metrics['win_rate']:.2f}%")
        print(f"Best Trade: ${metrics['best_trade']:,.2f}")
        print(f"Worst Trade: ${metrics['worst_trade']:,.2f}")
        
        print("\n--- TRADES BY DIRECTION ---")
        print(f"Long Trades: {metrics['long_trades']} (P&L: ${metrics['long_pnl']:,.2f})")
        print(f"Short Trades: {metrics['short_trades']} (P&L: ${metrics['short_pnl']:,.2f})")
        
        print("\n--- TRADES BY REGIME ---")
        for regime, stats in metrics['regime_stats'].items():
            print(f"{regime}:")
            print(f"  Trades: {stats['count']}")
            print(f"  Win Rate: {stats['win_rate']:.2f}%")
            print(f"  Total P&L: ${stats['total_pnl']:,.2f}")
            print(f"  Avg Duration: {stats['avg_duration']:.2f} hours")
            print(f"  Profit Factor: {stats['profit_factor']:.2f}")
        
        print("\n--- TRADES BY SIGNAL TYPE ---")
        for signal, stats in metrics['signal_stats'].items():
            print(f"{signal}:")
            print(f"  Trades: {stats['count']}")
            print(f"  Win Rate: {stats['win_rate']:.2f}%")
            print(f"  Total P&L: ${stats['total_pnl']:,.2f}")
        
        print("\n--- REGIME DISTRIBUTION ---")
        for regime, pct in metrics['regime_dist'].items():
            print(f"{regime}: {pct:.2f}% of time")
        
        print("\n--- MONTHLY RETURNS ---")
        for month, pnl in metrics['monthly_pnl'].items():
            print(f"{month}: ${pnl:,.2f}")
        
        print("\n--- DAY OF WEEK PROFITABILITY ---")
        for day, pnl in metrics['day_pnl'].items():
            print(f"{day}: ${pnl:,.2f}")
        
        print("\n--- HOUR OF DAY PROFITABILITY (Top 10) ---")
        top_hours = metrics['hour_pnl'].nlargest(10)
        for hour, pnl in top_hours.items():
            print(f"{hour:02d}:00 UTC: ${pnl:,.2f}")
        
        print("\n" + "="*80)
    
    def save_trade_log(self, filename: str = 'trade_log_v3.csv'):
        """Save trade log to CSV."""
        if not self.trades:
            print("No trades to save.")
            return
        
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Trade#', 'Regime', 'SignalType', 'Type', 'EntryDate', 'EntryPrice',
                           'ExitDate', 'ExitPrice', 'PositionSize', 'PnL_USDT', 'PnL_Percent',
                           'Commission', 'NetPnL', 'Duration_Hours', 'ExitReason', 'SessionMultiplier'])
            
            for i, trade in enumerate(self.trades, 1):
                writer.writerow([
                    i,
                    trade['regime'],
                    trade['signal_type'],
                    trade['direction'],
                    trade['entry_date'],
                    f"{trade['entry_price']:.2f}",
                    trade['exit_date'],
                    f"{trade['exit_price']:.2f}",
                    f"{trade['size']:.4f}",
                    f"{trade['pnl_usdt']:.2f}",
                    f"{trade['pnl_pct']:.2f}",
                    f"{trade['commission']:.2f}",
                    f"{trade['net_pnl']:.2f}",
                    f"{trade['duration_hours']:.2f}",
                    trade['exit_reason'],
                    f"{trade['session_multiplier']:.2f}"
                ])
        
        print(f"Trade log saved to {filename}")
    
    def save_equity_curve(self, filename: str = 'equity_curve_v3.csv'):
        """Save equity curve to CSV."""
        if not self.equity_curve:
            print("No equity curve to save.")
            return
        
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['DateTime', 'Equity', 'DrawdownPercent', 'Regime'])
            
            for point in self.equity_curve:
                writer.writerow([
                    point['datetime'],
                    f"{point['equity']:.2f}",
                    f"{point['drawdown_pct']:.2f}",
                    point['regime']
                ])
        
        print(f"Equity curve saved to {filename}")


def load_data(filename: str) -> pd.DataFrame:
    """Load and prepare ETHUSDT data."""
    print(f"Loading data from {filename}...")
    
    # Read CSV
    df = pd.read_csv(filename, skipinitialspace=True)
    
    # Rename columns
    df.columns = ['Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume']
    
    # Create datetime
    df['DateTime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'], format='%m/%d/%Y %H:%M:%S')
    
    # Sort by datetime
    df = df.sort_values('DateTime').reset_index(drop=True)
    
    print(f"Loaded {len(df)} candles")
    print(f"Date range: {df['DateTime'].iloc[0]} to {df['DateTime'].iloc[-1]}")
    
    return df


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate all technical indicators."""
    print("Calculating indicators...")
    
    strategy = AdaptiveStrategyV3()
    
    # EMAs
    df['EMA_20'] = strategy.calculate_ema(df['Close'], 20)
    df['EMA_50'] = strategy.calculate_ema(df['Close'], 50)
    df['EMA_100'] = strategy.calculate_ema(df['Close'], 100)
    df['EMA_200'] = strategy.calculate_ema(df['Close'], 200)
    
    # RSI
    df['RSI'] = strategy.calculate_rsi(df['Close'], 14)
    
    # ATR
    df['ATR'] = strategy.calculate_atr(df['High'], df['Low'], df['Close'], 14)
    
    # MACD
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = strategy.calculate_macd(df['Close'])
    
    # Bollinger Bands
    df['BB_Upper'], df['BB_Middle'], df['BB_Lower'] = strategy.calculate_bollinger_bands(df['Close'], 20, 2.0)
    df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Middle']
    
    # ADX
    df['ADX'] = strategy.calculate_adx(df['High'], df['Low'], df['Close'], 14)
    
    # Volume SMA
    df['Volume_SMA'] = strategy.calculate_sma(df['Volume'], 20)
    
    # Calculate BB Width median for regime detection
    df['BB_Width_Median'] = df['BB_Width'].rolling(window=100).median()
    
    # Detect regime for each candle
    df['Regime'] = df.apply(lambda row: strategy.detect_regime(row, row['BB_Width_Median']), axis=1)
    
    print("Indicators calculated successfully")
    
    return df


def save_results_markdown(metrics: Dict, filename: str = 'STRATEGY_V3_RESULTS.md'):
    """Save results to markdown file."""
    with open(filename, 'w') as f:
        f.write("# Adaptive Regime-Switching Strategy V3 - Results\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## Overall Performance\n\n")
        f.write(f"- **Total Return:** {metrics['total_return_pct']:.2f}% (${metrics['total_pnl']:,.2f})\n")
        f.write(f"- **Final Equity:** ${metrics['final_equity']:,.2f}\n")
        f.write(f"- **Max Drawdown:** {metrics['max_drawdown_pct']:.2f}% (${metrics['max_drawdown_usdt']:,.2f})\n")
        f.write(f"- **Sharpe Ratio:** {metrics['sharpe_ratio']:.2f}\n")
        f.write(f"- **Profit Factor:** {metrics['profit_factor']:.2f}\n\n")
        
        f.write("## Trade Statistics\n\n")
        f.write(f"- **Total Trades:** {metrics['total_trades']}\n")
        f.write(f"- **Winning Trades:** {metrics['winning_trades']}\n")
        f.write(f"- **Losing Trades:** {metrics['losing_trades']}\n")
        f.write(f"- **Win Rate:** {metrics['win_rate']:.2f}%\n")
        f.write(f"- **Best Trade:** ${metrics['best_trade']:,.2f}\n")
        f.write(f"- **Worst Trade:** ${metrics['worst_trade']:,.2f}\n\n")
        
        f.write("## Trades by Direction\n\n")
        f.write(f"- **Long Trades:** {metrics['long_trades']} (P&L: ${metrics['long_pnl']:,.2f})\n")
        f.write(f"- **Short Trades:** {metrics['short_trades']} (P&L: ${metrics['short_pnl']:,.2f})\n\n")
        
        f.write("## Trades by Regime\n\n")
        for regime, stats in metrics['regime_stats'].items():
            f.write(f"### {regime}\n")
            f.write(f"- Trades: {stats['count']}\n")
            f.write(f"- Win Rate: {stats['win_rate']:.2f}%\n")
            f.write(f"- Total P&L: ${stats['total_pnl']:,.2f}\n")
            f.write(f"- Avg Duration: {stats['avg_duration']:.2f} hours\n")
            f.write(f"- Profit Factor: {stats['profit_factor']:.2f}\n\n")
        
        f.write("## Trades by Signal Type\n\n")
        for signal, stats in metrics['signal_stats'].items():
            f.write(f"### {signal}\n")
            f.write(f"- Trades: {stats['count']}\n")
            f.write(f"- Win Rate: {stats['win_rate']:.2f}%\n")
            f.write(f"- Total P&L: ${stats['total_pnl']:,.2f}\n\n")
        
        f.write("## Regime Distribution\n\n")
        for regime, pct in metrics['regime_dist'].items():
            f.write(f"- {regime}: {pct:.2f}% of time\n")
        f.write("\n")
        
        f.write("## Monthly Returns\n\n")
        f.write("| Month | P&L |\n")
        f.write("|-------|-----|\n")
        for month, pnl in metrics['monthly_pnl'].items():
            f.write(f"| {month} | ${pnl:,.2f} |\n")
        f.write("\n")
        
        f.write("## Day of Week Profitability\n\n")
        f.write("| Day | P&L |\n")
        f.write("|-----|-----|\n")
        for day, pnl in metrics['day_pnl'].items():
            f.write(f"| {day} | ${pnl:,.2f} |\n")
        f.write("\n")
        
        f.write("## Top 10 Hours of Day by Profitability\n\n")
        f.write("| Hour (UTC) | P&L |\n")
        f.write("|------------|-----|\n")
        top_hours = metrics['hour_pnl'].nlargest(10)
        for hour, pnl in top_hours.items():
            f.write(f"| {hour:02d}:00 | ${pnl:,.2f} |\n")
    
    print(f"Results saved to {filename}")


def main():
    """Main execution function."""
    # Load data
    df = load_data('ETHUSDT_15_Minutes_year_2025.txt')
    
    # Calculate indicators
    df = calculate_indicators(df)
    
    # Run backtest
    strategy = AdaptiveStrategyV3(initial_capital=100000.0)
    strategy.run_backtest(df)
    
    # Calculate metrics
    metrics = strategy.calculate_metrics()
    
    # Print results
    strategy.print_results(metrics)
    
    # Save outputs
    strategy.save_trade_log('trade_log_v3.csv')
    strategy.save_equity_curve('equity_curve_v3.csv')
    save_results_markdown(metrics, 'STRATEGY_V3_RESULTS.md')
    
    print("\n✓ All files generated successfully!")
    print("  - trade_log_v3.csv")
    print("  - equity_curve_v3.csv")
    print("  - STRATEGY_V3_RESULTS.md")


if __name__ == '__main__':
    main()
