# Asymmetric Long/Short Strategy V4 - Results

## Strategy Overview

This strategy uses completely different approaches for LONG and SHORT trades:

- **SHORT = "Panic Catcher"**: Aggressive entries with fast indicators (EMA 10/30, fast MACD), tight SL (0.8×ATR), quick TPs
- **LONG = "Trend Confirmer"**: Conservative entries with slow indicators (EMA 50/200, standard MACD), wider SL (1.5×ATR), bigger TPs

## Overall Performance

- **Initial Capital**: $100,000.00
- **Final Capital**: $85,565.82
- **Total Return**: $-14,434.18 (-14.43%)
- **Max Drawdown**: 28.09% ($28,086.81)
- **Total Trades**: 85

- **Sharpe Ratio**: -0.30

## LONG Trades Analysis

- **Total LONG Trades**: 19
- **Win Rate**: 31.58%
- **Average PnL**: $-166.79
- **Average Duration**: 9.6 candles (2.4 hours)
- **Profit Factor**: 0.82

## SHORT Trades Analysis

- **Total SHORT Trades**: 66
- **Win Rate**: 36.36%
- **Average PnL**: $-170.68
- **Average Duration**: 4.4 candles (1.1 hours)
- **Profit Factor**: 0.89

## Monthly Returns

| Month | PnL (USD) | PnL (%) |
|-------|-----------|----------|
| 2025-01 | $-13,806.95 | -13.81% |
| 2025-02 | $7,653.51 | 7.65% |
| 2025-03 | $-6,156.79 | -6.16% |
| 2025-04 | $-5,881.74 | -5.88% |
| 2025-05 | $-2,575.61 | -2.58% |
| 2025-06 | $8,587.50 | 8.59% |
| 2025-07 | $-8,115.55 | -8.12% |
| 2025-08 | $-6,418.81 | -6.42% |
| 2025-09 | $-1,372.38 | -1.37% |
| 2025-10 | $3,690.89 | 3.69% |
| 2025-11 | $11,715.49 | 11.72% |
| 2025-12 | $-1,753.74 | -1.75% |

## Exit Reasons

### LONG Trades

- STOP_LOSS: 12 (63.2%)
- RSI_OVERBOUGHT: 6 (31.6%)
- FULLY_CLOSED: 1 (5.3%)

### SHORT Trades

- STOP_LOSS: 43 (65.2%)
- TRAILING_STOP: 11 (16.7%)
- RSI_OVERSOLD: 8 (12.1%)
- FULLY_CLOSED: 4 (6.1%)

## Strategy Parameters

### SHORT (Panic Catcher)
- Risk per trade: 1.5%
- Stop Loss: 0.8 × ATR
- Take Profit 1: 1.5 × ATR (50% close)
- Take Profit 2: 3.0 × ATR (30% close)
- Take Profit 3: 5.0 × ATR (20% close)
- Max Duration: 48 candles (12 hours)

### LONG (Trend Confirmer)
- Risk per trade: 1.0%
- Stop Loss: 1.5 × ATR
- Take Profit 1: 2.5 × ATR (40% close)
- Take Profit 2: 4.0 × ATR (30% close)
- Take Profit 3: 6.0 × ATR (30% close)
- Max Duration: 192 candles (48 hours)

