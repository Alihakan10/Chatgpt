import time
from datetime import datetime
from zoneinfo import ZoneInfo

import scanner

TZ = ZoneInfo(scanner.TIMEZONE)

# Onceki kontrolde current native 2H bari eksik kalan 3 hisse
# + referans olarak iki kez SAT->AL dogrulanan SMRTG.
SYMBOLS = [
    "BIST:QNBTR",
    "BIST:SNPAM",
    "BIST:YYAPI",
    "BIST:SMRTG",
]

MAX_DATA_ATTEMPTS = 4
RETRY_DELAY = 4.0


def local_dt(ts):
    return datetime.fromtimestamp(ts, tz=ZoneInfo("UTC")).astimezone(TZ)


def fetch_native_2h_with_retry(symbol):
    last_error = None
    for attempt in range(1, MAX_DATA_ATTEMPTS + 1):
        try:
            candles = scanner.get_tv_candles(symbol, "native_2h")
            ordered = sorted(candles, key=lambda x: x["time"])
            now = scanner.now_istanbul()
            today = now.date()

            today_session = [
                b for b in ordered
                if local_dt(b["time"]).date() == today
                and 10 <= local_dt(b["time"]).hour <= 17
                and local_dt(b["time"]).minute == 0
                and b["time"] <= now.timestamp()
            ]

            if today_session:
                return ordered, attempt

            last_error = RuntimeError("bugunun current native 2H bari bulunamadi")
        except Exception as exc:
            last_error = exc

        if attempt < MAX_DATA_ATTEMPTS:
            print(
                f"  RETRY {attempt}/{MAX_DATA_ATTEMPTS}: {last_error} | "
                f"{RETRY_DELAY:.0f}s sonra tekrar"
            )
            time.sleep(RETRY_DELAY)

    raise RuntimeError(
        f"{MAX_DATA_ATTEMPTS} denemede current native 2H alinamadi: {last_error}"
    )


def analyze(symbol):
    ordered, attempts = fetch_native_2h_with_retry(symbol)
    now = scanner.now_istanbul()
    today = now.date()

    session = [
        (b, local_dt(b["time"]))
        for b in ordered
        if 10 <= local_dt(b["time"]).hour <= 17
        and local_dt(b["time"]).minute == 0
    ]

    prev_dates = sorted({dt.date() for _, dt in session if dt.date() < today})
    if not prev_dates:
        raise RuntimeError("onceki islem gunu bulunamadi")

    prev_date = prev_dates[-1]
    prev_bar = max(
        (b for b, dt in session if dt.date() == prev_date),
        key=lambda b: b["time"],
    )

    today_bars = [
        b for b, dt in session
        if dt.date() == today and b["time"] <= now.timestamp()
    ]
    if not today_bars:
        raise RuntimeError("bugunun current 2H bari bulunamadi")

    current_bar = max(today_bars, key=lambda b: b["time"])

    directions = scanner.calculate_supertrend_directions(
        ordered,
        scanner.ATR_PERIOD,
        scanner.ATR_MULTIPLIER,
    )

    by_time = {b["time"]: i for i, b in enumerate(ordered)}
    i_prev = by_time[prev_bar["time"]]
    i_cur = by_time[current_bar["time"]]

    prev_dir = directions[i_prev]
    cur_dir = directions[i_cur]
    prior_cur_dir = directions[i_cur - 1] if i_cur > 0 else None

    return {
        "symbol": symbol,
        "attempts": attempts,
        "bar18": prev_bar,
        "bar_cur": current_bar,
        "dir18": prev_dir,
        "dir_cur": cur_dir,
        "prior_cur": prior_cur_dir,
        "candidate": prev_dir == -1 and cur_dir == 1,
        "intrabar_reversal": prior_cur_dir == -1 and cur_dir == 1,
    }


def label(direction):
    if direction == 1:
        return "AL"
    if direction == -1:
        return "SAT"
    return "BELIRSIZ"


def main():
    print("=" * 78)
    print("EKSIK 3 HISSE + SMRTG - TRADINGVIEW NATIVE 2H RETRY KONTROL")
    print("Study YOK | ATR 10 | Multiplier 2.0 | HL2 | Native 2H")
    print(f"Her hisse icin en fazla {MAX_DATA_ATTEMPTS} veri denemesi")
    print("=" * 78)

    results = []
    errors = []

    for n, symbol in enumerate(SYMBOLS, 1):
        print(f"\n[{n}/{len(SYMBOLS)}] {symbol}")
        try:
            a = analyze(symbol)
            print(f"veri denemesi={a['attempts']}")
            print(
                f"18:00={label(a['dir18'])} | "
                f"CURRENT={label(a['dir_cur'])} | "
                f"onceki-current={label(a['prior_cur'])} -> {label(a['dir_cur'])}"
            )
            print(
                f"18:00 C={a['bar18']['close']:.4f} | "
                f"CURRENT {local_dt(a['bar_cur']['time']).strftime('%d.%m.%Y %H:%M')} | "
                f"O={a['bar_cur']['open']:.4f} "
                f"H={a['bar_cur']['high']:.4f} "
                f"L={a['bar_cur']['low']:.4f} "
                f"C={a['bar_cur']['close']:.4f}"
            )
            print(
                f"aday={a['candidate']} | "
                f"GERCEK_INTRABAR_SAT_AL={a['intrabar_reversal']}"
            )
            results.append(a)
        except Exception as exc:
            print(f"HATA: {exc}")
            errors.append((symbol, str(exc)))

        time.sleep(1.0)

    print("\n" + "=" * 78)
    print("SON KONTROL")
    print("=" * 78)

    candidates = [a for a in results if a["candidate"]]
    true_reversals = [a for a in results if a["intrabar_reversal"]]

    print(f"Kontrol edilen: {len(results)}/{len(SYMBOLS)}")
    print(f"Hata: {len(errors)}")
    print(f"18:00 SAT -> CURRENT AL: {len(candidates)}")
    print(f"CURRENT mum icinde SAT -> AL: {len(true_reversals)}")

    if true_reversals:
        print("\nGERCEK ANLIK SAT -> AL:")
        for a in true_reversals:
            print(
                f"  >>> {a['symbol']} | "
                f"{local_dt(a['bar_cur']['time']).strftime('%d.%m.%Y %H:%M')} | "
                f"C={a['bar_cur']['close']:.4f}"
            )

    if errors:
        print("\nHALA VERI ALINAMAYAN:")
        for symbol, error in errors:
            print(f"  !!! {symbol} | {error}")

    print("=" * 78)


if __name__ == "__main__":
    main()
