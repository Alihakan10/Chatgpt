const TradingView = require("@mathieuc/tradingview");

const ID = "PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45";

(async () => {
  console.log("TRADINGVIEW INDICATOR METADATA TEST");
  console.log("STUDY OLUSTURULMAYACAK.");

  const indicator = await TradingView.getIndicator(ID);

  console.log("OBJECT KEYS:");
  console.log(Object.keys(indicator));

  console.log("INPUTS:");
  console.log(JSON.stringify(indicator.inputs || {}, null, 2));

  console.log("PLOTS:");
  console.log(JSON.stringify(indicator.plots || {}, null, 2));

  console.log("SCRIPT:");
  if (typeof indicator.script === "string") {
    console.log(indicator.script);
    try {
      console.log("SCRIPT_DECODED:");
      console.log(Buffer.from(indicator.script, "base64").toString("utf8"));
    } catch (_) {}
  } else {
    console.log(JSON.stringify(indicator.script || null, null, 2));
  }

  console.log("DESCRIPTION:");
  console.log(indicator.description || "");

  console.log("METADATA TEST TAMAMLANDI.");
})().catch(err => {
  console.error(err);
  process.exit(1);
});
