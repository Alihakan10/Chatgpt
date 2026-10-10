# BIST Early BUY — Virtual Only

Independent test project. It does not import or modify the Termux scanner, Telegram configuration, Google Sheets, or Osmanlı Yatırım.

## Current behavior
- Uses TradingView Screener for the BIST ticker list.
- Uses borsapy's TradingViewProvider for 2-hour candles.
- ATR 10, HL2, multiplier 2.0.
- Includes the currently open 2H candle and evaluates the same BUY condition as the supplied local code.
- Records new events by symbol + candle timestamp in `state/early_signals.json`.
- Makes no Telegram calls and sends no broker orders.

## Run
GitHub Actions → **BIST Early BUY Virtual Test** → **Run workflow**.

The scheduled workflow runs every 15 minutes on weekdays, but GitHub may delay scheduled starts. The script checks Istanbul local time and skips outside the active BIST 2H session. A successful workflow does not guarantee that TradingView data was returned for every symbol; inspect `latest_report.json` and the workflow logs.

This is a virtual test only. Do not add broker credentials to this repository.
