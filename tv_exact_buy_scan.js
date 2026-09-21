const TradingView = require("@mathieuc/tradingview");

const INDICATOR_ID = "PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45";
const TIMEFRAME = "120";
const RANGE = 500;
const LIMIT = Number(process.env.SCAN_LIMIT || "620");

const TEST_MODE = process.env.TEST_MODE === "true";
const TEST_SYMBOL = process.env.TEST_SYMBOL || "";
const FORCE_SCAN = process.env.FORCE_SCAN === "true";
const SEND_SCAN_REPORT = process.env.SEND_SCAN_REPORT !== "false";

const fs = require("fs");
const STATE_FILE = "state/supertrend_state.json";
const TZ = "Europe/Istanbul";

const fmt = ts =>
  new Intl.DateTimeFormat("tr-TR", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(Number(ts) * 1000));

const sleep = ms => new Promise(r => setTimeout(r, ms));

function isCompleted2H(period) {
  if (!period || period.$time == null) return false;
  const t = Number(period.$time);
  return Number.isFinite(t) &&
    t + 2 * 60 * 60 <= Math.floor(Date.now() / 1000);
}

async function getSymbols() {
  const response = await fetch("https://scanner.tradingview.com/turkey/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filter: [
        { left: "is_primary", operation: "equal", right: true },
        { left: "typespecs", operation: "has", right: "common" },
        { left: "type", operation: "equal", right: "stock" },
        { left: "name", operation: "nempty" }
      ],
      options: {
        active_symbols_only: true,
        lang: "tr"
      },
      symbols: {
        query: { types: [] },
        tickers: []
      },
      columns: ["name"],
      sort: {
        sortBy: "name",
        sortOrder: "asc"
      },
      range: [0, 1000]
    })
  });

  if (!response.ok) {
    throw new Error("Scanner HTTP " + response.status);
  }

  const data = await response.json();

  return [
    ...new Set(
      (data.data || [])
        .map(x => x.s)
        .filter(
          x =>
            typeof x === "string" &&
            x.startsWith("BIST:")
        )
    )
  ].slice(0, LIMIT);
}

async function main() {
  const symbols =
    TEST_MODE && TEST_SYMBOL
      ? [TEST_SYMBOL]
      : await getSymbols();

  const state = (() => {
    try {
      return JSON.parse(
        fs.readFileSync(
          STATE_FILE,
          "utf8"
        )
      );
    } catch (_) {
      return {};
    }
  })();

  /*
   * KRITIK:
   * BUY sinyali artik kendi Supertrend hesabimizdan uretilmiyor.
   * TradingView'daki ayni public SuperTrend study'nin ciktilari
   * dogrudan okunuyor.
   *
   * Kabul edilen BUY:
   *   1) SON TAMAMLANMIS 2H MUM
   *   2) SuperTrend_Buy == 1
   *   3) SuperTrend_Direction_Change == 1
   *
   * Daha eski mumlarda olusmus BUY'lar kesinlikle rapora alinmaz.
   */

  const client = new TradingView.Client();
  const chart = new client.Session.Chart();

  const indicator =
    await TradingView.getIndicator(
      INDICATOR_ID
    );

  // Kullanicinin Supertrend ayarlari.
  if (indicator.inputs?.ATR_Multiplier) {
    indicator.setOption(
      "ATR_Multiplier",
      2.0
    );
  }

  if (indicator.inputs?.Multiplier) {
    indicator.setOption(
      "Multiplier",
      2.0
    );
  }

  if (indicator.inputs?.ATR_Period) {
    indicator.setOption(
      "ATR_Period",
      10
    );
  }

  if (indicator.inputs?.Periods) {
    indicator.setOption(
      "Periods",
      10
    );
  }

  if (indicator.inputs?.Period) {
    indicator.setOption(
      "Period",
      10
    );
  }

  /*
   * Study icin kullanilan chart timeframe 120 dakikadir.
   * Public indicator'in source ayari HL2 olarak tanimliysa
   * TradingView study ayni ayarla hesaplanir.
   */

  let study = null;
  let studyReady = false;
  let pendingUpdate = null;
  let pendingError = null;

  async function scanOne(symbol) {
    return await new Promise(
      (resolve, reject) => {
        let done = false;

        const finish = (fn, value) => {
          if (done) return;
          done = true;
          fn(value);
        };

        const timer = setTimeout(
          () =>
            finish(
              reject,
              new Error(
                "Study timeout: " +
                symbol
              )
            ),
          30000
        );

        const waitUpdate = () =>
          new Promise(
            (res, rej) => {
              pendingUpdate = res;
              pendingError = rej;

              setTimeout(() => {
                if (
                  pendingUpdate === res
                ) {
                  pendingUpdate = null;
                  pendingError = null;

                  rej(
                    new Error(
                      "Study update timeout: " +
                      symbol
                    )
                  );
                }
              }, 25000);
            }
          );

        /*
         * SADECE SON TAMAMLANMIS 2H MUM KONTROL EDILIYOR.
         * Eski mumlarda BUY olsa bile bu taramada BUY kabul edilmez.
         */
        const handlePeriods = () => {
          try {
            const periods = (
              Array.isArray(
                study?.periods
              )
                ? study.periods
                : []
            ).filter(isCompleted2H);

            if (!periods.length) {
              return finish(
                reject,
                new Error(
                  "No completed 2H study period: " +
                  symbol
                )
              );
            }

            const last =
              periods[
                periods.length - 1
              ];

            const buyValue =
              Number(
                last.SuperTrend_Buy
              );

            const directionChange =
              Number(
                last.SuperTrend_Direction_Change
              );

            const result =
              buyValue === 1 &&
              directionChange === 1
                ? [
                    {
                      symbol,
                      candle_time:
                        Number(
                          last.$time
                        ),
                      price:
                        Number(
                          last.close
                        )
                    }
                  ]
                : [];

            clearTimeout(timer);

            console.log(
              "    SON TAMAMLANMIS 2H | " +
                symbol +
                " | " +
                fmt(last.$time) +
                " | SuperTrend_Buy=" +
                buyValue +
                " | Direction_Change=" +
                directionChange +
                " | " +
                (result.length
                  ? "GERCEK BUY"
                  : "BUY YOK")
            );

            finish(
              resolve,
              result
            );
          } catch (e) {
            finish(reject, e);
          }
        };

        if (!studyReady) {
          chart.onSymbolLoaded(
            async () => {
              if (studyReady) return;

              try {
                study =
                  new chart.Study(
                    indicator
                  );

                study.onError(
                  (...e) => {
                    const err =
                      new Error(
                        "Study: " +
                          JSON.stringify(e)
                      );

                    if (pendingError) {
                      pendingError(err);
                    }

                    finish(
                      reject,
                      err
                    );
                  }
                );

                study.onUpdate(
                  () => {
                    if (pendingUpdate) {
                      const r =
                        pendingUpdate;

                      pendingUpdate =
                        null;
                      pendingError =
                        null;

                      r();
                    }

                    if (studyReady) {
                      handlePeriods();
                    }
                  }
                );

                study.onReady(() => {
                  studyReady = true;
                  handlePeriods();
                });
              } catch (e) {
                finish(
                  reject,
                  e
                );
              }
            }
          );

          chart.setMarket(
            symbol,
            {
              timeframe:
                TIMEFRAME,
              range: RANGE,
              session: "regular",
              adjustment: "splits"
            }
          );
        } else {
          waitUpdate()
            .then(
              handlePeriods
            )
            .catch(e =>
              finish(
                reject,
                e
              )
            );

          chart.setMarket(
            symbol,
            {
              timeframe:
                TIMEFRAME,
              range: RANGE,
              session: "regular",
              adjustment: "splits"
            }
          );
        }
      }
    );
  }

  console.log(
    "=".repeat(70)
  );
  console.log(
    "TRADINGVIEW GERCEK BUY ETIKET TARAMASI"
  );
  console.log(
    "Hisse: " +
      symbols.length +
      " | ATR 10 | Carp 2.0 | HL2 | 2H"
  );
  console.log(
    "BUY SADECE SON TAMAMLANMIS 2H MUMDA KABUL EDILIYOR."
  );
  console.log(
    "TradingView Public SuperTrend study ciktilari kullaniliyor."
  );
  console.log(
    "SuperTrend_Buy == 1 VE Direction_Change == 1 olmadan BUY YOK."
  );
  console.log(
    "=".repeat(70)
  );

  const current = [];
  const fresh = [];

  let errors = 0;

  for (
    let i = 0;
    i < symbols.length;
    i++
  ) {
    const symbol =
      symbols[i];

    console.log(
      "[" +
        (i + 1) +
        "/" +
        symbols.length +
        "] " +
        symbol
    );

    try {
      const results =
        await scanOne(
          symbol
        );

      const old =
        state[symbol] &&
        typeof state[symbol] ===
          "object"
          ? state[symbol]
          : {};

      const oldBuy = Number(
        old.last_buy_candle_time ||
          0
      );

      for (const r of results) {
        const already =
          r.candle_time <=
          oldBuy;

        current.push({
          ...r,
          already
        });

        if (already) {
          console.log(
            "    MEVCUT BUY | " +
              fmt(
                r.candle_time
              ) +
              " | DAHA ONCE GONDERILDI"
          );
        } else {
          fresh.push(r);

          console.log(
            "    >>> GERCEK YENI BUY | " +
              fmt(
                r.candle_time
              )
          );
        }

        state[symbol] = {
          ...old,
          direction: 1,
          candle_time:
            r.candle_time,
          last_buy_candle_time:
            Math.max(
              oldBuy,
              r.candle_time
            )
        };
      }
    } catch (e) {
      errors++;

      console.log(
        "    HATA: " +
          String(
            e.message || e
          )
      );
    }
  }

  console.log(
    "=".repeat(70)
  );
  console.log(
    "TARAMA TAMAMLANDI"
  );
  console.log(
    "Toplam hisse: " +
      symbols.length
  );
  console.log(
    "Basarili cevap: " +
      (symbols.length -
        errors)
  );
  console.log(
    "Hata: " +
      errors
  );
  console.log(
    "SON MUMDAKI GERCEK BUY: " +
      current.length
  );
  console.log(
    "YENI BUY: " +
      fresh.length
  );

  if (
    FORCE_SCAN ||
    TEST_MODE
  ) {
    console.log(
      "MANUEL TARAMA BUY RAPORU"
    );

    if (!current.length) {
      console.log(
        "    SON TAMAMLANMIS 2H MUMDA GERCEK BUY YOK."
      );
    }

    for (const x of current) {
      console.log(
        "    " +
          x.symbol +
          " | " +
          fmt(
            x.candle_time
          ) +
          " | " +
          (x.already
            ? "DAHA ONCE GONDERILDI"
            : "YENI")
      );
    }

    console.log(
      "DAHA ONCE TELEGRAM'A GONDERILEN BUY: " +
        current.filter(
          x => x.already
        ).length
    );

    console.log(
      "YENI BUY: " +
        fresh.length
    );
  }

  if (
    fresh.length &&
    SEND_SCAN_REPORT
  ) {
    const token =
      process.env
        .TELEGRAM_BOT_TOKEN;

    const chat =
      process.env
        .TELEGRAM_CHAT_ID;

    if (!token || !chat) {
      throw new Error(
        "Telegram secret eksik."
      );
    }

    const lines = [
      "TRADINGVIEW GERCEK BUY ETIKETI",
      "",
      "BIST 2 SAATLIK SUPERTREND",
      "ATR 10 | HL2 | 2.0 | 2H",
      "",
      "SON TAMAMLANMIS MUM BUY: " +
        fresh.length +
        " adet",
      ""
    ];

    for (const x of fresh) {
      lines.push(
        "🟢 " +
          x.symbol.replace(
            "BIST:",
            ""
          ) +
          "   " +
          Number(
            x.price
          ).toFixed(2) +
          " TL"
      );

      lines.push(
        "   Mum: " +
          fmt(
            x.candle_time
          )
      );
    }

    const resp =
      await fetch(
        "https://api.telegram.org/bot" +
          token +
          "/sendMessage",
        {
          method: "POST",
          headers: {
            "Content-Type":
              "application/json"
          },
          body: JSON.stringify({
            chat_id: chat,
            text: lines.join(
              "\n"
            ),
            disable_web_page_preview:
              true
          })
        }
      );

    const tg =
      await resp.json();

    if (
      !resp.ok ||
      !tg.ok
    ) {
      throw new Error(
        "Telegram HTTP " +
          resp.status +
          ": " +
          JSON.stringify(tg)
      );
    }

    console.log(
      "GERCEK BUY LISTESI TELEGRAM'A GONDERILDI."
    );
  } else {
    console.log(
      "Son tamamlanmis 2H mumda yeni gercek BUY yok; Telegram gonderilmeyecek."
    );
  }

  fs.mkdirSync(
    "state",
    {
      recursive: true
    }
  );

  fs.writeFileSync(
    STATE_FILE,
    JSON.stringify(
      state,
      null,
      2
    ) + "\n"
  );

  try {
    client.end();
  } catch (_) {}
}

main().catch(e => {
  console.error(e);
  process.exit(1);
});
