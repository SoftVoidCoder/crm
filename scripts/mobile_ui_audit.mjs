import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const [
  baseUrl,
  email,
  password,
  outputDir = "/tmp/korda-mobile-audit",
  viewportWidth = "390",
  viewportHeight = "844",
] = process.argv.slice(2);
if (!baseUrl || !email || !password) {
  throw new Error("Usage: mobile_ui_audit.mjs <base-url> <email> <password> [output-dir]");
}

const browser = await chromium.launch({
  headless: true,
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const context = await browser.newContext({
  viewport: { width: Number(viewportWidth), height: Number(viewportHeight) },
  deviceScaleFactor: 1,
});
const page = await context.newPage();
const fs = await import("node:fs/promises");
await fs.mkdir(outputDir, { recursive: true });

await page.goto(`${baseUrl}/static/login.html`, { waitUntil: "domcontentloaded" });
await page.fill("#loginEmail", email);
await page.fill("#loginPassword", password);
await page.click('button:has-text("Войти")');
await page.waitForURL("**/app", { timeout: 15_000 });
await page.waitForTimeout(1_500);

const targets = [
  ["dashboard", "dashboard"],
  ["prospecting", "prospecting"],
  ["leads", "leads"],
  ["documents", "documents"],
  ["meetings", "meetings"],
  ["operations", "operations"],
];
const results = [];

for (const [name, viewKey] of targets) {
  await page.evaluate((key) => {
    if (typeof navigateTo === "function") navigateTo(key);
  }, viewKey);
  await page.waitForTimeout(650);
  const metrics = await page.evaluate(() => {
    const active = [...document.querySelectorAll(".view-page")]
      .find((element) => element.offsetParent !== null);
    const viewportWidth = document.documentElement.clientWidth;
    return {
      activeView: active?.id || "",
      viewportWidth,
      pageScrollWidth: document.documentElement.scrollWidth,
      rootOverflow: Math.max(0, document.documentElement.scrollWidth - viewportWidth),
      overflowingElements: active
        ? [...active.querySelectorAll("*")]
          .filter((element) => (
            element.offsetParent !== null
            && element.clientWidth > 40
            && element.scrollWidth > element.clientWidth + 8
          ))
          .slice(0, 12)
          .map((element) => ({
            className: String(element.className || "").slice(0, 80),
            text: String(element.innerText || "").trim().replace(/\s+/g, " ").slice(0, 100),
            delta: element.scrollWidth - element.clientWidth,
          }))
        : [],
    };
  });
  await page.screenshot({ path: `${outputDir}/${name}.png`, fullPage: false });
  results.push({ name, ...metrics });
}

await fs.writeFile(`${outputDir}/results.json`, JSON.stringify(results, null, 2));
await browser.close();
console.log(JSON.stringify({ outputDir, results }, null, 2));
