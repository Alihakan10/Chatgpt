const TradingView = require("@mathieuc/tradingview");
const zlib = require("zlib");

const ID = "PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45";

function tryDecode(s) {
  const b = Buffer.from(s, "base64");
  console.log("SCRIPT_BASE64_BYTES:", b.length);
  console.log("SCRIPT_BYTES_HEAD_HEX:", b.subarray(0,32).toString("hex"));
  console.log("SCRIPT_BYTES_HEAD_UTF8:", JSON.stringify(b.subarray(0,80).toString("utf8")));

  const attempts = [
    ["gunzip", () => zlib.gunzipSync(b)],
    ["inflate", () => zlib.inflateSync(b)],
    ["inflateRaw", () => zlib.inflateRawSync(b)],
    ["brotli", () => zlib.brotliDecompressSync(b)]
  ];

  for (const [name, fn] of attempts) {
    try {
      const out = fn();
      console.log("\nDECODE_" + name.toUpperCase() + "_OK:");
      console.log(out.toString("utf8"));
    } catch (e) {
      console.log("DECODE_" + name.toUpperCase() + "_FAILED");
    }
  }
}

(async () => {
  console.log("TRADINGVIEW INDICATOR METADATA TEST");
  console.log("STUDY OLUSTURULMAYACAK.");

  const indicator = await TradingView.getIndicator(ID);

  console.log("INPUTS:");
  console.log(JSON.stringify(indicator.inputs || {}, null, 2));

  console.log("PLOTS:");
  console.log(JSON.stringify(indicator.plots || {}, null, 2));

  if (typeof indicator.script === "string") {
    tryDecode(indicator.script);
  }

  console.log("DESCRIPTION:");
  console.log(indicator.description || "");
  console.log("METADATA TEST TAMAMLANDI.");
})().catch(err => {
  console.error(err);
  process.exit(1);
});
