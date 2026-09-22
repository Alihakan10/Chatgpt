from datetime import datetime
from zoneinfo import ZoneInfo

import scanner

TZ = ZoneInfo(scanner.TIMEZONE)

SYMBOLS = [
    "BIST:MEPET",
    "BIST:NTHOL",
    "BIST:PSDTC",
    "BIST:SEGYO",
    "BIST:SISE",
    "BIST:SMRTG",
    "BIST:VANGD",
]


def local_dt(ts):
    return datetime.fromtimestamp(ts, tz=ZoneInfo("UTC")).astimezone(TZ)


def label(direction):
    return "AL" if direction == 1 else "SAT" if direction == -1 else "BELIRSIZ"


def independent_directions(candles, period=10, multiplier=2.0):
    # Independent Wilder/RMA ATR + HL2 Supertrend implementation.
    n = len(candles)
    if n < period + 2:
        raise RuntimeError(f"yetersiz mum: {n}")

    tr = [None] * n
    atr = [None] * n
    final_upper = [None] * n
    final_lower = [None] * n
    direction = [None] * n

    for i in range(n):
        h = candles[i]["high"]
        l = candles[i]["low"]
        if i == 0:
            tr[i] = h - l
        else:
            pc = candles[i - 1]["close"]
            tr[i] = max(h - l, abs(h - pc), abs(l - pc))

    # Wilder RMA: first ATR is SMA, then recursive RMA.
    first = sum(tr[:period]) / period
    atr[period - 1] = first

    for i in range(period, n):
        atr[i] = ((atr[i - 1] * (period - 1)) + tr[i]) / period

    for i in range(period - 1, n):
        hl2 = (candles[i]["high"] + candles[i]["low"]) / 2.0
        basic_upper = hl2 + multiplier * atr[i]
        basic_lower = hl2 - multiplier * atr[i]

        if i == period - 1:
            final_upper[i] = basic_upper
            final_lower[i] = basic_lower
            direction[i] = -1
            continue

        prev_close = candles[i - 1]["close"]

        if basic_upper < final_upper[i - 1] or prev_close > final_upper[i - 1]:
            final_upper[i] = basic_upper
        else:
            final_upper[i] = final_upper[i - 1]

        if basic_lower > final_lower[i - 1] or prev_close < final_lower[i - 1]:
            final_lower[i] = basic_lower
        else:
            final_lower[i] = final_lower[i - 1]

        if direction[i - 1] == -1:
            direction[i] = 1 if candles[i]["close"] > final_upper[i - 1] else -1
        else:
            direction[i] = -1 if candles[i]["close"] < final_lower[i - 1] else 1

    return direction, atr, final_upper, final_lower


def run_symbol(symbol):
    candles = sorted(scanner.get_tv_candles(symbol, "native_2h"), key=lambda x: x["time"])
    if len(candles) < 20:
        raise RuntimeError(f"native 2H veri yetersiz: {len(candles)}")

    completed = scanner.get_last_completed_index(candles)
    if completed is None or completed < 1:
        raise RuntimeError("tamamlanmis 2H mum bulunamadi")

    calc = candles[:completed + 1]
    prod_dirs = scanner.calculate_supertrend_directions(
        calc, scanner.ATR_PERIOD, scanner.ATR_MULTIPLIER
    )
    ind_dirs, atr, fu, fl = independent_directions(
        calc, scanner.ATR_PERIOD, scanner.ATR_MULTIPLIER
    )

    i = len(calc) - 1
    p = i - 1

    return {
        "symbol": symbol,
        "previous": calc[p],
        "current": calc[i],
        "previous_dir_prod": prod_dirs[p],
        "current_dir_prod": prod_dirs[i],
        "previous_dir_ind": ind_dirs[p],
        "current_dir_ind": ind_dirs[i],
        "atr": atr[i],
        "fu": fu[i],
        "fl": fl[i],
        "prod_match_independent": prod_dirs[p] == ind_dirs[p] and prod_dirs[i] == ind_dirs[i],
        "buy": prod_dirs[p] == -1 and prod_dirs[i] == 1,
    }


def main():
    print("=" * 86)
    print("7 BUY ADAYI - TRADINGVIEW NATIVE 2H BIREBIR OHLC/SUPERTREND DOGRULAMA")
    print("Study YOK | ATR 10 | Multiplier 2.0 | HL2 | Native 2H")
    print("Uretim scanner.py + bagimsiz ayni formulle ikinci hesap karsilastiriliyor.")
    print("=" * 86)

    results = []
    errors = []

    for n, symbol in enumerate(SYMBOLS, 1):
        print(f"\n[{n}/7] {symbol}")
        try:
            a = run_symbol(symbol)
            pc, cc = a["previous"], a["current"]

            print(
                f"ONCEKI {local_dt(pc['time']).strftime('%d.%m.%Y %H:%M')} | "
                f"O={pc['open']:.4f} H={pc['high']:.4f} "
                f"L={pc['low']:.4f} C={pc['close']:.4f} | "
                f"ST={label(a['previous_dir_prod'])}"
            )
            print(
                f"CURRENT {local_dt(cc['time']).strftime('%d.%m.%Y %H:%M')} | "
                f"O={cc['open']:.4f} H={cc['high']:.4f} "
                f"L={cc['low']:.4f} C={cc['close']:.4f} | "
                f"ST={label(a['current_dir_prod'])}"
            )
            print(
                f"ATR10={a['atr']:.6f} | "
                f"FINAL_UPPER={a['fu']:.6f} | "
                f"FINAL_LOWER={a['fl']:.6f}"
            )
            print(
                f"PROD={label(a['previous_dir_prod'])}->{label(a['current_dir_prod'])} | "
                f"INDEPENDENT={label(a['previous_dir_ind'])}->{label(a['current_dir_ind'])} | "
                f"HESAP_ESLESMESI={a['prod_match_independent']} | "
                f"BUY={a['buy']}"
            )
            results.append(a)
        except Exception as exc:
            print(f"HATA: {exc}")
            errors.append((symbol, str(exc)))

    print("\n" + "=" * 86)
    print("SONUC")
    print("=" * 86)
    print(f"Kontrol edilen: {len(results)}/7")
    print(f"Hata: {len(errors)}")
    print(f"SAT -> AL BUY: {sum(a['buy'] for a in results)}/{len(results)}")
    print(f"Uretim ve bagimsiz hesap tamamen ayni: {sum(a['prod_match_independent'] for a in results)}/{len(results)}")

    if errors:
        print("\nHATALAR:")
        for symbol, error in errors:
            print(f"  !!! {symbol} | {error}")

    print("=" * 86)


if __name__ == "__main__":
    main()
