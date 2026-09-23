from new_buy_system.verify_14 import tv_native, trend_from_rows

SYMBOLS = ["BIST:ACSEL","BIST:AKSUE","BIST:ATSYH","BIST:BESLR","BIST:BMSCH","BIST:DMRGD","BIST:EMNIS","BIST:ENPRA","BIST:MOBTL","BIST:PETUN"]

ok = 0
errors = 0
for s in SYMBOLS:
    try:
        r4 = tv_native(s, "240", 300)
        r1 = tv_native(s, "1D", 300)
        t4 = trend_from_rows(r4)
        t1 = trend_from_rows(r1)
        print(f"{s}: 4H={t4} ({len(r4)} mum) | 1D={t1} ({len(r1)} mum)")
        ok += 1
    except Exception as e:
        errors += 1
        print(f"{s}: ERROR={e}")

print(f"SUMMARY OK={ok} ERRORS={errors} TOTAL={len(SYMBOLS)}")
if errors:
    raise SystemExit(1)
