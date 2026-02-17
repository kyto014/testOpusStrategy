# Strategy V5A - Short-Only Results

## Overview
**Strategy**: Short-Only 'Panic Catcher' based on V4 shorts

**Data Period**: Year 2025 ETHUSDT 15-minute data

**Strategy Type**: Mean-reversion short entries during panic selling

## Key Performance Metrics

| Metric | Value |
|--------|-------|
| Initial Capital | $100,000.00 |
| Final Capital | $99,948.84 |
| **Total Return** | **-0.05%** |
| **Max Drawdown** | **-0.05%** |
| Sharpe Ratio | -5.49 |
| **Win Rate** | **33.73%** |
| **Profit Factor** | **0.45** |
| Total Trades | 169 |
| Winning Trades | 57 |
| Losing Trades | 112 |

## Trade Analysis

| Metric | Value |
|--------|-------|
| Gross Profit | $34.11 |
| Gross Loss | $75.43 |
| Best Trade | $1.32 |
| Worst Trade | $-1.50 |
| Avg Winning Trade | $0.60 |
| Avg Losing Trade | $-0.67 |
| Avg Trade Duration | 2.1 candles (0.5 hours) |

## Exit Reason Breakdown

| Exit Reason | Count | Percentage |
|-------------|-------|------------|
| Stop Loss | 112 | 66.3% |
| TP1 | 53 | 31.4% |
| RSI Extreme (<15) | 4 | 2.4% |

## Monthly Performance

| Month | Trades | PnL | Wins |
|-------|--------|-----|------|
| 2025-01 | 8 | $-3.81 | 1 |
| 2025-02 | 14 | $-2.88 | 6 |
| 2025-03 | 14 | $1.50 | 9 |
| 2025-04 | 21 | $-5.79 | 7 |
| 2025-05 | 15 | $-8.47 | 2 |
| 2025-06 | 11 | $-0.37 | 6 |
| 2025-07 | 18 | $-7.51 | 3 |
| 2025-08 | 15 | $-4.64 | 3 |
| 2025-09 | 12 | $-4.76 | 2 |
| 2025-10 | 8 | $0.50 | 5 |
| 2025-11 | 25 | $-2.74 | 10 |
| 2025-12 | 8 | $-2.36 | 3 |

## Hourly Performance

| Hour (UTC) | Trades | Win Rate | Avg PnL |
|------------|--------|----------|----------|
| 00:00 | 9 | 33.3% | $-0.08 |
| 01:00 | 7 | 42.9% | $-0.15 |
| 02:00 | 3 | 33.3% | $-0.16 |
| 03:00 | 8 | 12.5% | $-0.35 |
| 04:00 | 4 | 25.0% | $-0.29 |
| 05:00 | 2 | 0.0% | $-0.45 |
| 06:00 | 3 | 33.3% | $-0.12 |
| 07:00 | 3 | 33.3% | $-0.24 |
| 08:00 | 4 | 0.0% | $-0.83 |
| 10:00 | 2 | 50.0% | $0.24 |
| 11:00 | 3 | 33.3% | $-0.09 |
| 12:00 | 4 | 0.0% | $-0.40 |
| 13:00 | 14 | 42.9% | $-0.33 |
| 14:00 | 32 | 28.1% | $-0.39 |
| 15:00 | 30 | 43.3% | $-0.13 |
| 16:00 | 9 | 33.3% | $-0.34 |
| 17:00 | 8 | 50.0% | $0.00 |
| 18:00 | 6 | 16.7% | $-0.42 |
| 19:00 | 7 | 57.1% | $0.03 |
| 20:00 | 1 | 100.0% | $0.56 |
| 21:00 | 4 | 25.0% | $-0.40 |
| 22:00 | 4 | 50.0% | $0.00 |
| 23:00 | 2 | 0.0% | $-0.46 |

## Daily Performance

| Day | Trades | Win Rate | Avg PnL |
|-----|--------|----------|----------|
| Monday | 23 | 43.5% | $-0.10 |
| Tuesday | 44 | 31.8% | $-0.27 |
| Wednesday | 33 | 27.3% | $-0.38 |
| Thursday | 42 | 35.7% | $-0.20 |
| Friday | 27 | 33.3% | $-0.24 |

## Strategy Configuration

### Entry Conditions (ALL must be true)
1. EMA 10 < EMA 30 (bearish trend)
2. Close < EMA 10 (price below fast EMA)
3. Fast MACD (8,17,5) histogram < 0 AND declining
4. RSI between 28 and 47 (bearish but not oversold)
5. Volume > 1.9 × Volume SMA 20 (panic spike)
6. Close < Lower Bollinger Band OR price drop > 0.6%

### Risk Parameters
- Risk per trade: 2.0%
- Stop Loss: 0.7 × ATR
- Take Profit 1: 1.5 × ATR (close 50%)
- Take Profit 2: 3.0 × ATR (close 30%)
- Take Profit 3: 5.0 × ATR (close 20%)
- Trailing Stop: 0.6 × ATR (after TP2)
- Max simultaneous positions: 2
- Max trade duration: 48 candles (12 hours)

### Time Filters
- No trading Saturday/Sunday
- No new positions Friday after 18:00 UTC
- Close all positions by Friday 20:00 UTC
- Position sizing varies by hour (40%-100%)

## Comparison with V4 Shorts

V4 shorts had:
- 58.33% win rate
- 2.43 profit factor
- 36 short trades

V5A achieved:
- 33.73% win rate
- 0.45 profit factor
- 169 trades
- -0.05% return

## Conclusion

⚠️ **Strategy performance notes**

The strategy did not achieve the target return of 20-28%.
Max drawdown was within the target of <15%.
Win rate was below the target range of 55-60%.

