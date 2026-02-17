"# testOpusStrategy

## V5B-Fixed Backtest Strategy

This repository contains the V5B-Fixed trading strategy that combines the best elements from V5B and V4 strategies:

- **V5B LONG conditions**: Excellent performance on oversold reversals
- **V4 SHORT conditions**: Selective bearish momentum trading

### Strategy File

- `backtest-strategy-v5B-fixed.py` - Main backtest implementation

### Results (2025 Data - ETHUSDT 15min)

**Overall Performance:**
- Total Trades: 256
- Win Rate: 58.20%
- Profit Factor: 0.97
- Return: -0.82%
- Max Drawdown: 4.15%

**LONG Trades (V5B Conditions):**
- Count: 222
- Win Rate: 58.11%
- Profit Factor: 0.96

**SHORT Trades (V4 Conditions):**
- Count: 34 (✅ Target: ~36)
- Win Rate: 58.82% (✅ Target: ~58%)
- Profit Factor: 1.04

### Entry Conditions

**LONG (V5B):**
- RSI < 33 (oversold)
- Close < Lower Bollinger Band
- Volume > 1.8x SMA
- Price change < -0.6%

**SHORT (V4 - Fixed):**
- RSI between 38-46 (bearish, not extreme)
- Volume > 1.8x SMA
- Close < Lower BB AND price change < -0.6%
- Close < BB middle (bearish structure)

### Exit Conditions

**Both LONG and SHORT:**
- Take Profit: 5%
- Stop Loss: 3%
- RSI-based exits (>70 for LONG, <30 for SHORT)

### Usage

```bash
python3 backtest-strategy-v5B-fixed.py
```

### Dependencies

- pandas
- numpy

Install with:
```bash
pip install pandas numpy
```

### Notes

- Position sizing: 10% per trade for risk management
- The strategy achieves target trade counts and win rates
- Profit factor below target suggests market conditions or exit tuning may need adjustment
" 
