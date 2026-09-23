import scanner
from datetime import datetime
from zoneinfo import ZoneInfo

SYMBOLS = [
    "BIST:ALCAR","BIST:BURCE","BIST:BURVA","BIST:CASA","BIST:CMBTN",
    "BIST:ENERY","BIST:FMIZP","BIST:KNFRT","BIST:KONTR","BIST:ODAS",
    "BIST:POLHO","BIST:QNBFK","BIST:SNPAM","BIST:VKFYO"
]

def dt(ts):
    return datetime.fromtimestamp(ts, tz=ZoneInfo("UTC")).astimezone(
        ZoneInfo(scanner.TIMEZONE)
    ).strftime("%d.%m.%Y %H:%M")

def run():
    print("=== 14 URETIM BUY -> TRADINGVIEW NATIVE 2H CANLI KARŞILAŞTIRMA ===")
    print("Study YOK | 1H->2H YOK | Native 2H")
    print("AYAR: ATR=10 MULT=2 HL2")
    matches_completed = 0
    matches_live = 0
    for symbol in SYMBOLS:
        try:
            candles = sorted(scanner.get_tv_candles_with_retry(symbol, "native_2h"), key=lambda x:x["time"])
            ci = scanner.get_last_completed_index(candles)
            if ci is None or ci < 1:
                print(symbol, "VERI YETERSIZ")
                continue
            dirs_all = scanner.calculate_supertrend_directions(
                candles, scanner.ATR_PERIOD, scanner.ATR_MULTIPLIER
            )
            p = dirs_all[ci-1]; c = dirs_all[ci]
            completed_buy = p == -1 and c == 1
            live_idx = len(candles)-1
            live_buy = False
            live_text = "YOK"
            if live_idx > ci:
                lp = dirs_all[live_idx-1]; lc = dirs_all[live_idx]
                live_buy = lp == -1 and lc == 1
                live_text = f"{dt(candles[live_idx]['time'])} {lp}->{lc} BUY={live_buy}"
            if completed_buy: matches_completed += 1
            if live_buy: matches_live += 1
            print(
                f"{symbol} | TAMAMLANMIS {dt(candles[ci]['time'])} "
                f"{p}->{c} BUY={completed_buy} | CANLI {live_text}"
            )
        except Exception as e:
            print(symbol, "HATA", repr(e))
    print(f"SUMMARY COMPLETED_BUY={matches_completed} LIVE_BUY={matches_live}")

if __name__ == "__main__":
    run()
