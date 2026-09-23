# Yeni BUY Sistemi

Bu klasör mevcut BIST Telegram tarayıcısından tamamen bağımsızdır.

## Hedef

TradingView'deki Supertrend BUY mantığını Study kullanmadan matematiksel olarak yeniden üretmek.

- Timeframe: native 2H
- ATR Period: 10
- ATR Multiplier: 2.0
- Source: HL2
- ATR: Wilder/RMA
- BUY: yalnızca -1 -> +1 yön değişimi
- Son tamamlanmış 2H mum esas alınır

## Güvenlik

Bu aşamada Telegram, GitHub Actions schedule veya mevcut scanner dosyaları kullanılmaz ve değiştirilmez.

## Sıradaki aşama

BUY motorunu sabit 14 hisselik doğrulama setinde çalıştırıp sonuçları ayrı bir test çıktısına almak. Eşleşme doğrulanmadan 620 hisse taramasına geçilmeyecek.
