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

# The production scan at 13:02 reported these BUYs on the
# 11:00 native 2H candle. Verify that exact historical candle,
# not whichever candle happens to be the latest when this test runs.
TARGET_DATE = "22.09.2026"
TARGET_HOUR = 11


def local_dt(ts):
    return datetime.fromtimestamp(ts, tz=ZoneInfo("UTC")).astimezone(TZ)


def label(direction):
    return "AL" if direction == 1 else "SAT" if direction == -1 else "BELIRSIZ"


def independent_directions(candles, period=10, multiplier=2.0):
    n = len(candles)
    if n < period + 2:
        raise RuntimeError(f"yetersiz mum: {n}")

    tr = [None] * n
    atr = [None] * n
    final_upper = [None] * n
    final_lower = [None] * n
    direction = [None] * n

    for i in range(n):
        h, l = candles[i]["high"], candles[i]["low"]
        if i == 0:
            tr[i] = h - l
        else:
            pc = candles[i - 1]["close"]
            tr[i] = max(h - l, abs(h - pc), abs(l - pc))

    atr[period - 1] = sum(tr[:period]) / period
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

        final_upper[i] = (
            basic_upper
            if basic_upper < final_upper[i - 1] or prev_close > final_upper[i - 1]
            else final_upper[i - 1]
        )
        final_lower[i] = (
            basic_lower
            if basic_lower > final_lower[i - 1] or prev_close < final_lower[i - 1]
            else final_lower[i - 1]
        )

        if direction[i - 1] == -1:
            direction[i] = 1 if candles[i]["close"] > final_upper[i - 1] else -1
        else:
            direction[i] = -1 if candles[i]["close"] < final_lower[i - 1] else 1

    return direction, atr, final_upper, final_lower


def run_symbol(symbol):
    candles = sorted(
        scanner.get_tv_candles(symbol, "native_2h"),
        key=lambda x: x["time"]
    )
    if len(candles) < 20:
        raise RuntimeError(f"native 2H veri yetersiz: {len(candles)}")

    target = None
    target_i = None

    for i, candle in enumerate(candles):
        dt = local_dt(candle["time"])
        if (
            dt.strftime("%d.%m.%Y") == TARGET_DATE
            and dt.hour == TARGET_HOUR
            and dt.minute == 0
        ):
            target = candle
            target_i = i
            break

    if target_i is None or target_i < 1:
        raise RuntimeError(f"{TARGET_DATE} {TARGET_HOUR:02d}:00 native 2H bari bulunamadi")

    # Calculate only with data up through the exact BUY candle,
    # matching the production calculation at that moment.
    calc = candles[:target_i + 1]

    prod_dirs = scanner.calculate_supertrend_directions(
        calc, scanner.ATR_PERIOD, scanner.ATR_MULTIPLIER
    )
    ind_dirs, atr, fu, fl = independent_directions(
        calc, scanner.ATR_PERIOD, scanner.ATR_MULTIPLIER
    )

    p = target_i - 1

    return {
        "symbol": symbol,
        "previous": calc[p],
        "target": calc[target_i],
        "previous_dir_prod": prod_dirs[p],
        "target_dir_prod": prod_dirs[target_i],
        "previous_dir_ind": ind_dirs[p],
        "target_dir_ind": ind_dirs[target_i],
        "atr": atr[target_i],
        "fu": fu[target_i],
        "fl": fl[target_i],
        "prod_match_independent": (
            prod_dirs[p] == ind_dirs[p]
            and prod_dirs[target_i] == ind_dirs[target_i]
        ),
        "buy": prod_dirs[p] == -1 and prod_dirs[target_i] == 1,
    }


def main():
    print("=" * 88)
    print("7 BUY ADAYI - URETIMDEKI TAM 11:00 MUMUN BIREBIR DOGRULAMASI")
    print("Study YOK | ATR 10 | Multiplier 2.0 | HL2 | Native 2H")
    print(f"Hedef mum: {TARGET_DATE} {TARGET_HOUR:02d}:00")
    print("Not: Daha sonra 13:00 mumu olustuğu icin son mumu degil,")
    print("uretim taramasinin BUY bildirdigi TAM 11:00 MUMUNU kontrol ediyoruz.")
    print("=" * 88)

    results = []
    errors = []

    for n, symbol in enumerate(SYMBOLS, 1):
        print(f"\n[{n}/7] {symbol}")
        try:
            a = run_symbol(symbol)
            pc, tc = a["previous"], a["target"]

            print(
                f"ONCEKI {local_dt(pc['time']).strftime('%d.%m.%Y %H:%M')} | "
                f"O={pc['open']:.4f} H={pc['high']:.4f} "
                f"L={pc['low']:.4f} C={pc['close']:.4f} | "
                f"ST={label(a['previous_dir_prod'])}"
            )
            print(
                f"BUY MUMU {local_dt(tc['time']).strftime('%d.%m.%Y %H:%M')} | "
                f"O={tc['open']:.4f} H={tc['high']:.4f} "
                f"L={tc['low']:.4f} C={tc['close']:.4f} | "
                f"ST={label(a['target_dir_prod'])}"
            )
            print(
                f"ATR10={a['atr']:.6f} | "
                f"FINAL_UPPER={a['fu']:.6f} | "
                f"FINAL_LOWER={a['fl']:.6f}"
            )
            print(
                f"PROD={label(a['previous_dir_prod'])}->{label(a['target_dir_prod'])} | "
                f"INDEPENDENT={label(a['previous_dir_ind'])}->{label(a['target_dir_ind'])} | "
                f"HESAP_ESLESMESI={a['prod_match_independent']} | "
                f"BUY={a['buy']}"
            )
            results.append(a)
        except Exception as exc:
            print(f"HATA: {exc}")
            errors.append((symbol, str(exc)))

    print("\n" + "=" * 88)
    print("SONUC")
    print("=" * 88)
    print(f"Kontrol edilen: {len(results)}/7")
    print(f"Hata: {len(errors)}")
    print(f"11:00 SAT -> AL BUY: {sum(a['buy'] for a in results)}/{len(results)}")
    print(
        "Uretim ve bagimsiz hesap tamamen ayni: "
        f"{sum(a['prod_match_independent'] for a in results)}/{len(results)}"
    )

    if errors:
        print("\nHATALAR:")
        for symbol, error in errors:
            print(f"  !!! {symbol} | {error}")

    print("=" * 88)


if __name__ == "__main__":
    main()
