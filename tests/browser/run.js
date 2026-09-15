#!/usr/bin/env node
// Real-browser checks for bulk editing. Starts tests/browser/server.py on a
// free port, resets the synthetic fixtures before every scenario, and runs
// each file in scenarios/ against a fresh page. Needs Playwright with a
// Chromium build; without it the run exits 2 and says so (not a pass).
//
//   node tests/browser/run.js            # every scenario
//   node tests/browser/run.js keyboard   # scenarios whose name contains the word
//
// Env: GAMETAPE_PYTHON (default: python3), GAMETAPE_ROOT (source tree),
// GAMETAPE_CHROMIUM (executable path when Playwright's own lookup fails).
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

const HERE = __dirname;
const OUT = path.join(HERE, "output");
const SCENARIOS = path.join(HERE, "scenarios");

function loadPlaywright() {
  const candidates = ["playwright", path.join(path.dirname(process.execPath), "..", "lib", "node_modules", "playwright")];
  for (const candidate of candidates) {
    try { return require(candidate); } catch (err) { if (err.code !== "MODULE_NOT_FOUND") throw err; }
  }
  return null;
}

function startServer() {
  return new Promise((resolve, reject) => {
    const proc = spawn(process.env.GAMETAPE_PYTHON || "python3", [path.join(HERE, "server.py")],
      { env: { ...process.env }, stdio: ["ignore", "pipe", "pipe"] });
    let buf = "", stderr = "";
    proc.stdout.on("data", chunk => {
      buf += chunk.toString();
      const line = buf.split("\n").find(item => item.startsWith("{"));
      if (line) resolve({ proc, info: JSON.parse(line) });
    });
    proc.stderr.on("data", chunk => { stderr += chunk.toString(); });
    proc.on("exit", code => reject(new Error(`server exited ${code}\n${stderr}`)));
  });
}

async function main() {
  const playwright = loadPlaywright();
  if (!playwright) {
    console.error("SKIPPED: playwright is not installed (npm i -g playwright && npx playwright install chromium).");
    process.exit(2);
  }
  const filter = process.argv.slice(2);
  const files = fs.readdirSync(SCENARIOS).filter(name => name.endsWith(".js")).sort()
    .filter(name => !filter.length || filter.some(word => name.includes(word)));
  fs.mkdirSync(OUT, { recursive: true });
  const { proc, info } = await startServer();
  const launch = {};
  if (process.env.GAMETAPE_CHROMIUM) launch.executablePath = process.env.GAMETAPE_CHROMIUM;
  const browser = await playwright.chromium.launch(launch);
  const results = { media: info.media, scenarios: {}, console: [], pageErrors: [] };
  try {
    for (const file of files) {
      const name = file.replace(/\.js$/, "");
      const context = await browser.newContext();
      const page = await context.newPage();
      page.on("console", msg => { if (["error", "warning"].includes(msg.type())) results.console.push({ scenario: name, type: msg.type(), text: msg.text() }); });
      page.on("pageerror", err => results.pageErrors.push({ scenario: name, error: String(err) }));
      const base = info.url;
      const api = {
        get: async route => (await page.request.get(base + route)).json(),
        put: (route, data) => page.request.put(base + route, { data }),
        post: (route, data) => page.request.post(base + route, { data }),
        reset: async () => (await page.request.post(base + "/__test/reset")).json(),
      };
      const started = Date.now();
      try {
        await api.reset();
        await page.goto(base);
        const scenario = require(path.join(SCENARIOS, file));
        const result = await scenario({ page, base, api, screenshot: label => page.screenshot({ path: path.join(OUT, `${name}-${label}.png`) }) });
        results.scenarios[name] = { ok: true, seconds: (Date.now() - started) / 1000, result };
      } catch (err) {
        results.scenarios[name] = { ok: false, seconds: (Date.now() - started) / 1000,
          error: String(err && err.message || err).split("\n").slice(0, 10).join("\n") };
        try { await page.screenshot({ path: path.join(OUT, `${name}-failure.png`) }); } catch {}
      }
      console.error(`${name}: ${results.scenarios[name].ok ? "ok" : "FAIL"} (${results.scenarios[name].seconds}s)`);
      await context.close();
    }
  } finally {
    await browser.close();
    proc.kill("SIGTERM");
  }
  // Media 416s come from the placeholder video, not the application.
  results.console = results.console.filter(item => !(info.media === "placeholder" && /416/.test(item.text)));
  fs.writeFileSync(path.join(OUT, "results.json"), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
  const failed = Object.values(results.scenarios).some(item => !item.ok) || results.pageErrors.length;
  if (info.media === "placeholder") console.error("NOTE: placeholder video; media playback and ffmpeg behaviour were not exercised.");
  process.exit(failed ? 1 : 0);
}

main().catch(err => { console.error(err); process.exit(1); });
