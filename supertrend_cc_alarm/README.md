# Standalone Supertrend CC Telegram Alarm

Bu klasor mevcut BIST Supertrend sisteminden bagimsizdir.

## Ayarlar
- 2H
- ATR 10
- HL2
- Wilder/RMA
- Multiplier 2
- Confirmed Close
- Sadece son tamamlanmis mum
- Tekrar eden ayni BUY gonderilmez

## Akis
620 BIST -> native 2H OHLC -> Supertrend CC -> BUY -> Telegram

TradingView Study veya mevcut scanner.py / verified_scanner.py kullanilmaz.

GitHub Actions 5 dakikada bir calisir; 2H mum kapanisindan sonraki ilk kontrolde BUY Telegram'a gonderilir.
