# ============================================================
# BIST 18:00 -> 10:00 SUPERTREND TESTI
# ============================================================
# scanner.py'ye DOKUNMAZ.
# Study kullanmaz.
# TradingView WebSocket OHLC + scanner.py Supertrend formulu kullanilir.
#
# TEST MANTIĞI
# 18:00 kapanisli BIST 2H bar = TradingView native 2H serisindeki 17:00 bar
# 10:00 bar = TradingView native 2H serisindeki 10:00 bar
#
# 10:10 testinde 10:00 bar henuz kapanmamis olabilir.
# Bu nedenle 10:00 barinin O/H/L/C'si o anda TradingView'in verdigi
# GUNCEL OHLC olarak kullanilir. Bu bir "intrabar" testidir.
#
# Sonuc:
#   18:00 ST = SAT (-1)
#   10:00 ST = AL  (+1)
#       -> 10:10 ADAY YENI AL
#
# State degistirmez, Telegram gondermez.
# ============================================================

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import scanner


TZ = ZoneInfo(scanner.TIMEZONE)


def local_dt(timestamp):
    return datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).astimezone(TZ)


def direction_text(direction):
    if direction == 1:
        return "AL"
    if direction == -1:
        return "SAT"
    return "?"


def find_reference_bars(candles):
    """
    TradingView native 2H serisindeki GERCEK bar zamanlarini kullanir.

    Sabit olarak "10:00" veya "17:00" timestamp varsaymaz.
    TradingView'in seans icinde dondurdugu:
      - onceki islem gununun SON barini = 18:00 kapanis referansi
      - bugunun SON barini = 10:10 anindaki mevcut 2H bar

    Boylece TradingView timestamp hizalamasindaki farklar testi bozmaz.
    """
    now = scanner.now_istanbul()
    today = now.date()

    session_bars = []

    for bar in candles:
        dt = local_dt(bar["time"])

        # BIST normal seansinin 10:00-18:00 araligindaki barlar.
        if 10 <= dt.hour <= 17 and dt.minute == 0:
            session_bars.append((bar, dt))

    if not session_bars:
        return None, None

    previous_dates = sorted({
        dt.date()
        for _, dt in session_bars
        if dt.date() < today
    })

    previous_close = None
    if previous_dates:
        prev_date = previous_dates[-1]
        prev_bars = [
            (bar, dt)
            for bar, dt in session_bars
            if dt.date() == prev_date
        ]
        if prev_bars:
            previous_close = max(
                prev_bars,
                key=lambda x: x[0]["time"]
            )[0]

    today_bars = [
        (bar, dt)
        for bar, dt in session_bars
        if dt.date() == today
        and bar["time"] <= now.timestamp()
    ]

    current_10 = None
    if today_bars:
        current_10 = max(
            today_bars,
            key=lambda x: x[0]["time"]
        )[0]

    return previous_close, current_10


def calculate_at_18_and_10(candles, previous_close, current_10):
    """
    Supertrend dizisini ortak tarihceden bir kez hesaplar.
    Böylece 18:00 ve 10:00 degerleri ayni stateful Supertrend
    zincirinden gelir.
    """
    ordered = sorted(candles, key=lambda x: x["time"])

    target_times = {
        previous_close["time"],
        current_10["time"],
    }

    selected = []
    for i, bar in enumerate(ordered):
        if bar["time"] in target_times:
            selected.append(i)

    if len(selected) != 2:
        raise RuntimeError("18:00 ve 10:00 bar indeksleri bulunamadi.")

    directions = scanner.calculate_supertrend_directions(
        ordered,
        scanner.ATR_PERIOD,
        scanner.ATR_MULTIPLIER
    )

    if directions is None:
        raise RuntimeError("Supertrend hesaplanamadi.")

    idx_18 = selected[0]
    idx_10 = selected[1]

    if ordered[idx_18]["time"] > ordered[idx_10]["time"]:
        idx_18, idx_10 = idx_10, idx_18

    return (
        ordered[idx_18],
        directions[idx_18],
        ordered[idx_10],
        directions[idx_10],
        ordered,
        directions,
    )


def run_symbol(symbol):
    print("")
    print("=" * 72)
    print(f"{symbol} | 18:00 -> 10:00 TEST")

    try:
        candles = scanner.get_tv_candles(symbol, "native_2h")

        previous_close, current_10 = find_reference_bars(candles)

        if previous_close is None:
            print("SON ONCEKI ISLEM GUNUNUN 18:00 BAR'I BULUNAMADI.")
            return {"status": "skip", "symbol": symbol}

        if current_10 is None:
            print("BUGUNUN 10:00 BAR'I BULUNAMADI.")
            print("Bu durum 10:10'dan once veya TradingView'in current bar'i vermemesi halinde gorulebilir.")
            return {"status": "skip", "symbol": symbol}

        (
            bar18,
            dir18,
            bar10,
            dir10,
            ordered,
            directions,
        ) = calculate_at_18_and_10(
            candles,
            previous_close,
            current_10,
        )

        dt18 = local_dt(bar18["time"])
        dt10 = local_dt(bar10["time"])

        is_candidate = dir18 == -1 and dir10 == 1

        print("")
        print(
            f"18:00 BAR | {dt18.strftime('%d.%m.%Y %H:%M')} kapanis"
        )
        print(
            f"  O={bar18['open']:.4f} "
            f"H={bar18['high']:.4f} "
            f"L={bar18['low']:.4f} "
            f"C={bar18['close']:.4f}"
        )
        print(f"  SUPERTREND = {dir18} ({direction_text(dir18)})")

        print("")
        print(
            f"10:00 BAR | {dt10.strftime('%d.%m.%Y %H:%M')} baslangic"
        )
        print(
            f"  O={bar10['open']:.4f} "
            f"H={bar10['high']:.4f} "
            f"L={bar10['low']:.4f} "
            f"C={bar10['close']:.4f}"
        )
        print(f"  SUPERTREND = {dir10} ({direction_text(dir10)})")

        print("")
        if is_candidate:
            print(">>> 10:10 ADAY YENI AL <<<")
            print(">>> 18:00 SAT -> 10:00 AL <<<")
        else:
            print("10:10 ADAY YENI AL YOK.")
            print(
                f"Durum: {direction_text(dir18)} -> {direction_text(dir10)}"
            )

        # 10:00 barinin onceki bar ile gercek bir SAT->AL donusu
        # olup olmadigini da ayrica goster.
        idx10 = next(
            i for i, b in enumerate(ordered)
            if b["time"] == bar10["time"]
        )

        prev10_dir = (
            directions[idx10 - 1]
            if idx10 > 0
            else None
        )

        print(
            "10:00 mum icindeki anlik donus: "
            f"{direction_text(prev10_dir)} -> {direction_text(dir10)}"
        )

        return {
            "status": "ok",
            "symbol": symbol,
            "direction_18": dir18,
            "direction_10": dir10,
            "candidate": is_candidate,
            "bar18_time": bar18["time"],
            "bar10_time": bar10["time"],
        }

    except Exception as exc:
        print(f"HATA: {exc}")
        return {
            "status": "error",
            "symbol": symbol,
            "error": str(exc),
        }


def main():
    all_bist = os.getenv("TEST_1010_ALL_BIST", "false").lower() in ("1", "true", "yes", "on")

    if all_bist:
        symbols = scanner.get_bist_symbols()
        print(f"TradingView Scanner'dan toplam {len(symbols)} BIST hissesi alindi.")
    else:
        text = os.getenv(
            "TEST_1010_SYMBOLS",
            "BIST:ZOREN"
        )
        symbols = [
            x.strip()
            for x in text.split(",")
            if x.strip()
        ]

    print("=" * 72)
    print("BIST 18:00 -> 10:00 SUPERTREND 10:10 TESTI")
    print("=" * 72)
    print(
        f"Ayarlar: ATR={scanner.ATR_PERIOD} | "
        f"Multiplier={scanner.ATR_MULTIPLIER} | "
        "Source=HL2 | Timeframe=Native 2H"
    )
    print(
        "TEST: State YOK | Telegram YOK | Study YOK"
    )
    print(
        "Semboller: " + ", ".join(symbols)
    )

    results = []

    # Tum BIST taramasinda TradingView baglantilarini paralel calistir.
    workers = int(os.getenv("TEST_1010_WORKERS", "8"))
    workers = max(1, min(workers, 12))

    if all_bist:
        print(f"Paralel worker sayisi: {workers}")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(run_symbol, symbol): symbol
                for symbol in symbols
            }
            for future in as_completed(future_map):
                results.append(future.result())
    else:
        for symbol in symbols:
            results.append(run_symbol(symbol))

    print("")
    print("=" * 72)
    print("OZET")
    print("=" * 72)

    ok = [r for r in results if r["status"] == "ok"]
    candidates = [r for r in ok if r.get("candidate")]

    print(f"Basarili: {len(ok)}")
    print(f"10:10 ADAY YENI AL: {len(candidates)}")

    for r in candidates:
        print(
            f"  >>> {r['symbol']} | "
            "18:00 SAT -> 10:00 AL"
        )

    print("=" * 72)


if __name__ == "__main__":
    main()
