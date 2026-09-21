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
        if (typeof indicator[key] === "string") {\n        console.log(indicator[key]);\n        if (key === "script") {\n          try { console.log("SCRIPT_DECODED:\\n" + Buffer.from(indicator[key], "base64").toString("utf8")); } catch (_) {}\n        }\n      } else {\n        console.log(JSON.stringify(indicator[key], null, 2));\n      }
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
