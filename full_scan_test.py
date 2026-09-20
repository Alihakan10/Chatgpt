import os
import scanner

def main():
    limit = int(os.getenv("SCAN_LIMIT", "620"))

    symbols = scanner.get_bist_symbols()
    if limit > 0:
        symbols = symbols[:limit]

    print("=" * 70)
    print("FULL BUY TEST BASLADI")
    print(f"Toplam taranacak hisse: {len(symbols)}")
    print("ATR=10 | HL2 | MULTIPLIER=2.0 | 2H")
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
            print(f"    >>> BUY: {symbol}", flush=True)

    results.sort(key=lambda x: x["symbol"])

    print("")
    print("=" * 70)
    print("FULL BUY TEST TAMAMLANDI")
    print(f"Toplam hisse: {len(symbols)}")
    print(f"BUY sinyali: {len(results)}")
    print(f"Hata: {errors}")
    print("=" * 70)

    if not results:
        print("Yeni/aktif BUY sinyali bulunamadi; Telegram gonderilmeyecek.")
        return

    scanner.send_telegram(
        scanner.build_telegram_message(results)
    )

    print("BUY listesi Telegram'a gonderildi.")

if __name__ == "__main__":
    main()
