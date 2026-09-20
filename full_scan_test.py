import os
import scanner

def main():
    raw_limit = os.getenv("SCAN_LIMIT", "620").strip().lstrip("\\")
    limit = int(raw_limit or "620")

    symbols = scanner.get_bist_symbols()
    if limit > 0:
        symbols = symbols[:limit]

    print("=" * 70)
    print("TRADINGVIEW GERCEK BUY ETIKET TESTI BASLADI")
    print(f"Toplam taranacak hisse: {len(symbols)}")
    print("Kivanc SuperTrend: ATR=10 | HL2 | MULTIPLIER=2.0 | 2H | RMA")
    print("=" * 70)

    results = []
    errors = 0

    # State kullanmiyoruz:
    # Bu test, son tamamlanmis 2H mumunda BUY etiketi
    # bulunan tum hisseleri Telegram'a gondermek icindir.
    test_state = {}

    for number, symbol in enumerate(symbols, 1):
        print(f"[{number}/{len(symbols)}] {symbol}", flush=True)

        result = scanner.scan_symbol(symbol, test_state)

        if result.get("status") == "error":
            errors += 1
            continue

        if result.get("buy_signal") is True:
            results.append(result)
            print(f"    >>> GERCEK BUY ETIKETI: {symbol}", flush=True)

    results.sort(key=lambda x: x["symbol"])

    print("")
    print("=" * 70)
    print("TRADINGVIEW GERCEK BUY ETIKET TESTI TAMAMLANDI")
    print(f"Toplam hisse: {len(symbols)}")
    print(f"GERCEK BUY ETIKETI: {len(results)}")
    print(f"Hata: {errors}")
    print("=" * 70)

    if not results:
        print("GERCEK BUY ETIKETI bulunamadi; Telegram gonderilmeyecek.")
        return

    scanner.send_telegram(
        scanner.build_telegram_message(results)
    )

    print("BUY listesi Telegram'a gonderildi.")

if __name__ == "__main__":
    main()
