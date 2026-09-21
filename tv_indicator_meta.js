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

  for (const key of ["metainfo","script","source","description","name","shortName","id","version","options"]) {
    try {
      if (indicator[key] !== undefined) {
        console.log("\n" + key.toUpperCase() + ":");
        console.log(typeof indicator[key] === "string"
          ? indicator[key]
          : JSON.stringify(indicator[key], null, 2));
      }
    } catch (e) {
      console.log(key + ": <okunamadi>");
    }
  }

  console.log("METADATA TEST TAMAMLANDI.");
})().catch(err => {
  console.error(err);
  process.exit(1);
});
