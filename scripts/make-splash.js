// Generates iOS PWA startup images (apple-touch-startup-image) into frontend/public/splash/.
// Usage: node scripts/make-splash.js
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const SIZES = [ // CSS width, height, device pixel ratio
  [375, 667, 2], [414, 896, 2], [390, 844, 3], [393, 852, 3], [402, 874, 3], [428, 926, 3], [430, 932, 3], [440, 956, 3],
];
const svg = `<svg viewBox="0 0 64 64"><defs><linearGradient id="a" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#c4b5fd"/><stop offset=".5" stop-color="#8b5cf6"/><stop offset="1" stop-color="#3b82f6"/></linearGradient>
<linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>
<path d="M20 8h24l14 16-26 32L6 24 20 8Z" fill="url(#a)"/><path d="M20 8h24l14 16H6L20 8Z" fill="url(#b)"/>
<path d="M6 24h52M20 8l-4 16 16 32 16-32-4-16M16 24 32 8l16 16" fill="none" stroke="#fff" stroke-opacity=".35" stroke-width="1.4"/></svg>`;
(async () => {
  const out = path.join(__dirname, "../frontend/public/splash");
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch();
  for (const [w, h, dpr] of SIZES) {
    const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: dpr });
    await p.setContent(`<html><body style="margin:0;background:#000;height:100vh;display:grid;place-items:center;font-family:-apple-system,system-ui">
      <div style="text-align:center"><div style="width:84px;height:84px;margin:0 auto">${svg.replace("<svg", '<svg width="84" height="84"')}</div>
      <div style="color:#f5f5f7;font-weight:700;font-size:22px;margin-top:18px;letter-spacing:-0.3px">Rubine</div></div></body></html>`);
    await p.screenshot({ path: path.join(out, `splash-${w * dpr}x${h * dpr}.png`) });
    await p.close();
    console.log(`splash-${w * dpr}x${h * dpr}.png`);
  }
  await b.close();
})();
