"# testOpusStrategy

## V5B-Fixed Backtest Strategy with V4 SHORT Improvements

This repository contains the improved V5B-Fixed trading strategy that combines V5B LONG conditions with enhanced SHORT strategy using V4 indicators and risk management.

### Key Features

- **V5B LONG Conditions**: Proven oversold reversal strategy (58.30% WR)
- **V4-Inspired SHORT**: Enhanced with EMA, Fast MACD, and ATR-based risk management (54.55% WR, 1.73 PF)
- **Dynamic Risk Management**: ATR-based stops and targets adapt to market volatility
- **Multiple Take-Profit Levels**: Captures both quick profits and larger moves

### Files

- `backtest-strategy-v5B-fixed.py` - Main backtest implementation
- `IMPLEMENTATION_SUMMARY.md` - Detailed comparison and analysis
- `backtest_results.txt` - Latest backtest results

### Results (2025 ETHUSDT 15m Data)

#### Overall Performance
- **Total Trades**: 245
- **Win Rate**: 57.96%
- **Profit Factor**: 1.34
- **Return**: +16.25%
- **Max Drawdown**: -16.48%

#### LONG Trades (V5B Conditions)
- **Count**: 223
- **Win Rate**: 58.30%
- **Profit Factor**: 0.97
- **Net P&L**: -$83.81

#### SHORT Trades (V4-Inspired)
- **Count**: 22
- **Win Rate**: 54.55%
- **Profit Factor**: 1.73 ⭐ (66% improvement from PR #7's 1.04)
- **Net P&L**: +$1,708.96 ⭐

### Improvement Over PR #7

| Metric | PR #7 | Fixed | Improvement |
|--------|-------|-------|-------------|
| SHORT Profit Factor | 1.04 | 1.73 | **+66%** ✅ |
| SHORT Net P&L | +$7.05 | +$1,709 | **+24,100%** ✅ |
| Overall Return | -0.82% | +16.25% | **+17.07%** ✅ |

### SHORT Entry Conditions

All conditions must be met:
1. EMA 10 < EMA 30 (bearish trend)
2. Close < EMA 10 (price below trend)
3. Fast MACD (8,17,5) histogram < 0 AND declining
4. RSI between 38-50 (selective bearish range)
5. Volume > 1.8× Volume SMA 20 (high volume)
6. Close < Lower Bollinger Band (extended price)
7. Price dropped > 0.6% (significant weakness)

### SHORT Risk Management (V4 ATR-Based)

- **Risk**: 1.5% of capital per trade
- **Stop Loss**: 0.8 × ATR
- **Take Profit**: 1.5×, 3.0×, 5.0× ATR levels
- **Trailing Stop**: 0.6 × ATR (when profitable)
- **Max Duration**: 48 candles

### LONG Entry Conditions (V5B - Unchanged)

- RSI < 33 (oversold)
- Close < Lower Bollinger Band
- Volume > 1.8× Volume SMA 20
- Price change < -0.6%

### Usage

```bash
# Install dependencies
pip install pandas numpy

# Run backtest
python3 backtest-strategy-v5B-fixed.py
```

### Technical Indicators Used

- **RSI (14)**: Momentum indicator
- **EMA (10, 30)**: Trend indicators
- **Fast MACD (8,17,5)**: Momentum confirmation
- **Bollinger Bands (20, 2)**: Volatility and price extension
- **ATR (14)**: Volatility-based risk management
- **Volume SMA (20)**: Volume confirmation

### Notes

- Data period: 2025-01-01 to 2026-01-01 (ETHUSDT 15-minute candles)
- Initial balance: $10,000
- The strategy shows significant improvement in SHORT performance through V4's dynamic risk management
- LONG conditions remain unchanged from V5B
- Security scan passed with 0 alerts

### References

- **PR #7**: Original V5B-Fixed implementation
- **V4 Strategy**: Source of indicators and risk management approach
- **V5B Strategy**: Source of LONG conditions
" 
