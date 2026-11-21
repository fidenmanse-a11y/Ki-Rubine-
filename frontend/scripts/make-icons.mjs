// Renders the Rubine app icons (PNG) from an inline SVG using Playwright's Chromium.
// Usage: node scripts/make-icons.mjs   (dev-only; generated PNGs are committed)
import { createRequire } from "node:module";
import { writeFileSync, mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const gem = (pad) => `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <radialGradient id="bg" cx="30%" cy="20%" r="95%"><stop offset="0" stop-color="#1c1033"/><stop offset=".55" stop-color="#07060d"/><stop offset="1" stop-color="#000"/></radialGradient>
    <radialGradient id="glow" cx="50%" cy="55%" r="45%"><stop offset="0" stop-color="#8b5cf6" stop-opacity=".55"/><stop offset="1" stop-color="#8b5cf6" stop-opacity="0"/></radialGradient>
    <linearGradient id="a" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ddd6fe"/><stop offset=".45" stop-color="#8b5cf6"/><stop offset="1" stop-color="#3b82f6"/></linearGradient>
    <linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".6"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  </defs>
  <rect width="512" height="512" fill="url(#bg)"/>
  <circle cx="256" cy="280" r="220" fill="url(#glow)"/>
  <g transform="translate(${pad} ${pad}) scale(${(512 - 2 * pad) / 64})">
    <path d="M20 8h24l14 16-26 32L6 24 20 8Z" fill="url(#a)"/>
    <path d="M20 8h24l14 16H6L20 8Z" fill="url(#b)"/>
    <path d="M6 24h52M20 8l-4 16 16 32 16-32-4-16M16 24 32 8l16 16" fill="none" stroke="#fff" stroke-opacity=".38" stroke-width="1.2"/>
  </g>
</svg>`;

mkdirSync("public/icons", { recursive: true });
writeFileSync("public/icons/favicon.svg", gem(96));
const browser = await chromium.launch();
const page = await browser.newPage();
const jobs = [["icon-192.png", 192, 96], ["icon-512.png", 512, 96], ["apple-touch-icon.png", 180, 104], ["icon-maskable-512.png", 512, 150]];
for (const [name, size, pad] of jobs) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<html><body style="margin:0;background:#000">${gem(pad).replace("<svg ", `<svg width="${size}" height="${size}" `)}</body></html>`);
  await page.screenshot({ path: `public/icons/${name}`, omitBackground: false });
  console.log("wrote", name);
}
await browser.close();
