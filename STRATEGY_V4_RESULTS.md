# Asymmetric Long/Short Strategy V4 - Results

## Strategy Overview

This strategy uses completely different approaches for LONG and SHORT trades:

- **SHORT = "Panic Catcher"**: Aggressive entries with fast indicators (EMA 10/30, fast MACD), tight SL (0.8×ATR), quick TPs
- **LONG = "Trend Confirmer"**: Conservative entries with slow indicators (EMA 50/200, standard MACD), wider SL (1.5×ATR), bigger TPs

## Overall Performance

- **Initial Capital**: $100,000.00
- **Final Capital**: $134,280.89
- **Total Return**: $34,280.89 (34.28%)
- **Max Drawdown**: 18.62% ($21,639.63)
- **Total Trades**: 65

- **Sharpe Ratio**: 1.22

## LONG Trades Analysis

- **Total LONG Trades**: 29
- **Win Rate**: 31.03%
- **Average PnL**: $-828.58
- **Average Duration**: 11.7 candles (2.9 hours)
- **Profit Factor**: 0.50

## SHORT Trades Analysis

- **Total SHORT Trades**: 36
- **Win Rate**: 58.33%
- **Average PnL**: $1619.71
- **Average Duration**: 5.4 candles (1.3 hours)
- **Profit Factor**: 2.43

## Monthly Returns

| Month | PnL (USD) | PnL (%) |
|-------|-----------|----------|
| 2025-01 | $-4,614.49 | -4.61% |
| 2025-02 | $4,963.40 | 4.96% |
| 2025-03 | $2,016.04 | 2.02% |
| 2025-04 | $8,313.85 | 8.31% |
| 2025-05 | $-768.42 | -0.77% |
| 2025-06 | $-2,517.70 | -2.52% |
| 2025-07 | $-6,892.50 | -6.89% |
| 2025-08 | $-4,669.91 | -4.67% |
| 2025-10 | $8,017.20 | 8.02% |
| 2025-11 | $31,908.68 | 31.91% |
| 2025-12 | $-1,475.27 | -1.48% |

## Exit Reasons

### LONG Trades

- STOP_LOSS: 20 (69.0%)
- RSI_OVERBOUGHT: 6 (20.7%)
- TRAILING_STOP: 2 (6.9%)
- FULLY_CLOSED: 1 (3.4%)

### SHORT Trades

- STOP_LOSS: 17 (47.2%)
- TRAILING_STOP: 9 (25.0%)
- RSI_OVERSOLD: 9 (25.0%)
- FULLY_CLOSED: 1 (2.8%)

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

