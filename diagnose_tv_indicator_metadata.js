const ID = "PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45";
const url = "https://pine-facade.tradingview.com/pine-facade/translate/" + encodeURIComponent(ID) + "/last";
const r = await fetch(url, {headers: {"User-Agent":"Mozilla/5.0","Accept":"application/json"}});
console.log("HTTP", r.status);
const text = await r.text();
console.log(text);

