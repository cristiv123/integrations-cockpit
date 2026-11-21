#!/usr/bin/env node
/**
 * Record the Integrations-Cockpit demo video (method from KI-Wissen/tools/demo-video).
 *
 *   node tools/demo-video/record.mjs --lang en
 *   node tools/demo-video/record.mjs --lang en --only intro,data   # dry run
 *   node tools/demo-video/record.mjs --lang en --show              # with a window
 *
 * Needs the app on http://localhost:8501 (synthetic demo data), pitch/deck/slides.html
 * (build_slides.py) and build/<lang>/durations.json (tts.py). Writes build/<lang>/frames
 * and timeline.json for compose.py. Nothing to install: Node's WebSocket drives the
 * installed Chrome over the DevTools Protocol; frames come from Page.startScreencast.
 */

import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const NARRATION = JSON.parse(await readFile(join(HERE, 'narration.json'), 'utf8'));
const SLIDES = pathToFileURL(resolve(HERE, '..', '..', 'pitch', 'deck', 'slides.html')).href;

const VIEWPORT = { width: 1600, height: 900, deviceScaleFactor: 1.2 };
const FRAME = { width: 1920, height: 1080 };
/** Seconds an app recomputation lasts in the finished video. Mirrored in compose.py. */
const WAIT_OUT = 1.5;
const SCENE_TAIL = 0.9;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Cdp {
  #ws; #nextId = 1; #pending = new Map(); #listeners = new Map();
  static async attach(wsUrl) {
    const cdp = new Cdp();
    cdp.#ws = new WebSocket(wsUrl);
    await new Promise((ok, fail) => {
      cdp.#ws.addEventListener('open', ok, { once: true });
      cdp.#ws.addEventListener('error', () => fail(new Error('cannot reach ' + wsUrl)), { once: true });
    });
    cdp.#ws.addEventListener('message', (event) => {
      const m = JSON.parse(event.data);
      if (m.id && cdp.#pending.has(m.id)) {
        const { ok, fail } = cdp.#pending.get(m.id);
        cdp.#pending.delete(m.id);
        m.error ? fail(new Error(m.error.message)) : ok(m.result);
      } else if (m.method) {
        for (const fn of cdp.#listeners.get(m.method) ?? []) fn(m.params);
      }
    });
    return cdp;
  }
  send(method, params = {}, sessionId) {
    const id = this.#nextId++;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    return new Promise((ok, fail) => { this.#pending.set(id, { ok, fail }); this.#ws.send(JSON.stringify(payload)); });
  }
  on(method, fn) { if (!this.#listeners.has(method)) this.#listeners.set(method, []); this.#listeners.get(method).push(fn); }
  once(method) {
    return new Promise((ok) => {
      const fn = (p) => { const l = this.#listeners.get(method); l.splice(l.indexOf(fn), 1); ok(p); };
      this.on(method, fn);
    });
  }
  close() { this.#ws.close(); }
}

function chromePath() {
  const found = [process.env.CHROME, 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'].filter(Boolean).find((p) => existsSync(p));
  if (!found) throw new Error('Chrome not found; set CHROME to its path');
  return found;
}

async function launchChrome(headless) {
  const port = 9300 + Math.floor(Math.random() * 500);
  const profile = await mkdtemp(join(tmpdir(), 'cockpit-video-'));
  const flags = [`--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--hide-scrollbars', '--force-color-profile=srgb', '--allow-file-access-from-files', 'about:blank'];
  if (headless) flags.unshift('--headless=new', '--disable-gpu');
  else flags.unshift(`--window-size=${VIEWPORT.width},${VIEWPORT.height + 140}`);
  const child = spawn(chromePath(), flags, { stdio: 'ignore' });
  let version = null;
  for (let i = 0; i < 100 && !version; i++) {
    try { version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json(); } catch { await sleep(200); }
  }
  if (!version) throw new Error('Chrome did not open a debugging port');
  return { child, profile, wsUrl: version.webSocketDebuggerUrl };
}

// Headless Chrome draws no pointer: a cursor is injected into the app (not into the slides).
const CURSOR_SCRIPT = `
(() => {
  if (location.protocol === 'file:') return;
  const install = () => {
    if (document.getElementById('__demo_cursor')) return;
    const c = document.createElement('div');
    c.id = '__demo_cursor';
    c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2l15 11-6.5 1.2L16 21l-2.6 1.2-3.4-6.6L5 20z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, { position: 'fixed', left: (window.__cx ?? 800) + 'px', top: (window.__cy ?? 450) + 'px',
      zIndex: 2147483647, pointerEvents: 'none', transition: 'left .7s cubic-bezier(.4,0,.2,1), top .7s cubic-bezier(.4,0,.2,1)',
      marginLeft: '-3px', marginTop: '-2px', filter: 'drop-shadow(0 1px 2px rgba(0,0,0,.35))' });
    document.documentElement.appendChild(c);
    const r = document.createElement('div');
    r.id = '__demo_ripple';
    Object.assign(r.style, { position: 'fixed', width: '34px', height: '34px', marginLeft: '-17px', marginTop: '-17px',
      borderRadius: '50%', background: 'rgba(31,78,120,.35)', zIndex: 2147483646, pointerEvents: 'none',
      transform: 'scale(0)', opacity: '0', transition: 'transform .35s ease-out, opacity .45s ease-out' });
    document.documentElement.appendChild(r);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
  setInterval(install, 500);
})();`;

class Page {
  constructor(cdp, sessionId) { this.cdp = cdp; this.sessionId = sessionId; this.x = 800; this.y = 450; }
  send(method, params) { return this.cdp.send(method, params, this.sessionId); }

  async eval(body) {
    const r = await this.send('Runtime.evaluate', { expression: `(async () => { ${body} })()`, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text ?? 'evaluation failed');
    return r.result.value;
  }

  async goto(url) {
    const loaded = this.cdp.once('Page.loadEventFired');
    await this.send('Page.navigate', { url });
    await Promise.race([loaded, sleep(20000)]);
    await this.eval(`window.__cx = ${this.x}; window.__cy = ${this.y};`);
  }

  async waitFor(test, timeoutMs = 60000) {
    const expr = /\breturn\b/.test(test) ? test : `return !!document.querySelector(${JSON.stringify(test)});`;
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) { if (await this.eval(expr)) return; await sleep(200); }
    throw new Error(`timed out waiting for ${test}`);
  }

  /** Streamlit has finished its rerun: no "Running" widget and no stale elements, three checks in a row. */
  async idle(timeoutMs = 180000) {
    await sleep(300);
    let calm = 0;
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const busy = await this.eval(`return !!document.querySelector('[data-testid="stStatusWidget"]') || !!document.querySelector('[data-stale="true"]') || !document.querySelector('[data-testid="stTab"]');`);
      calm = busy ? 0 : calm + 1;
      if (calm >= 3) return;
      await sleep(200);
    }
    throw new Error('app did not become idle');
  }

  async locate(selector, { text, nth = 0 } = {}) {
    return this.eval(`
      let list = [...document.querySelectorAll(${JSON.stringify(selector)})].filter(e => e.getClientRects().length > 0);
      ${text ? `list = list.filter(e => e.textContent.includes(${JSON.stringify(text)}));` : ''}
      const el = list[${nth}];
      if (!el) throw new Error(${JSON.stringify('nothing matches ' + selector + (text ? ' / ' + text : ''))});
      el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      await new Promise(r => setTimeout(r, 150));
      const b = el.getBoundingClientRect();
      return { x: Math.round(b.left + Math.min(b.width / 2, 120)), y: Math.round(b.top + b.height / 2), top: b.top, left: b.left, w: b.width, h: b.height };
    `);
  }

  async moveTo(x, y, ms = 750) {
    this.x = x; this.y = y;
    await this.eval(`window.__cx = ${x}; window.__cy = ${y}; const c = document.getElementById('__demo_cursor'); if (c) { c.style.left = '${x}px'; c.style.top = '${y}px'; }`);
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
    await sleep(ms);
  }

  async hover(selector, opts) { const p = await this.locate(selector, opts); await this.moveTo(p.x, p.y); return p; }

  async ripple() {
    await this.eval(`const r = document.getElementById('__demo_ripple'); if (r) { r.style.transition = 'none'; r.style.left = window.__cx + 'px';
      r.style.top = window.__cy + 'px'; r.style.transform = 'scale(.2)'; r.style.opacity = '1'; r.offsetWidth;
      r.style.transition = 'transform .35s ease-out, opacity .45s ease-out'; r.style.transform = 'scale(1.4)'; r.style.opacity = '0'; }`);
  }

  async clickAt(x, y) {
    await this.moveTo(x, y);
    await this.ripple();
    await this.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
    await this.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
    await sleep(400);
  }

  async click(selector, opts) { const p = await this.locate(selector, opts); await this.clickAt(p.x, p.y); return p; }

  async scrollMain(to, ms = 1800) {
    await this.eval(`
      const el = document.querySelector('[data-testid="stMain"]');
      const start = el.scrollTop, dy = ${to} - start, t0 = performance.now();
      await new Promise(done => { const step = (t) => { const k = Math.min(1, (t - t0) / ${ms});
        el.scrollTop = start + dy * (k < .5 ? 2*k*k : 1 - Math.pow(-2*k + 2, 2) / 2); k < 1 ? requestAnimationFrame(step) : done(); };
        requestAnimationFrame(step); });
    `);
  }
}

const sidebar = '[data-testid="stSidebar"] label';
const tab = '[data-testid="stTab"]';

class Take {
  constructor(page, durations) { this.page = page; this.durations = durations; this.scenes = []; this.waits = []; }
  outputSince(since) {
    const now = Date.now() / 1000;
    let saved = 0;
    for (const { a, b } of this.waits) if (a >= since && b - a > WAIT_OUT) saved += (b - a) - WAIT_OUT;
    return (now - since) - saved;
  }
  /** An app rerun; long ones are squeezed in compose.py, with a badge. */
  async rerun() {
    const a = Date.now() / 1000;
    await this.page.idle();
    const b = Date.now() / 1000;
    this.waits.push({ a, b });
    if (b - a > 2) console.log(`    rerun ${(b - a).toFixed(1)}s`);
  }
}

const SCENES = {
  async intro(t) {
    const p = t.page;
    await p.goto(`${SLIDES}?s=cover`);
    await sleep(6500);
    await p.goto(`${SLIDES}?s=problem`);
  },

  async data(t) {
    const p = t.page;
    await p.goto(t.app);
    await t.rerun();
    await p.moveTo(800, 450, 300);
    await p.hover(sidebar, { text: 'Synthetische Demodaten' });
    await sleep(600);
    await p.hover('[data-testid="stSidebar"] [data-testid="stCaptionContainer"]', { text: 'Dateien' });
    await sleep(600);
    await p.click(tab, { text: 'Datenqualität' });
    await sleep(800);
    await p.hover('[data-testid="stTabPanel"] [data-testid="stDataFrame"]', { nth: 0 });
    await sleep(1500);
    await p.hover('[data-testid="stTabPanel"] [data-testid="stCaptionContainer"]', { text: 'Erkannte Dateien' });
  },

  async cockpit(t) {
    const p = t.page;
    await p.click(tab, { text: 'Cockpit' });
    await sleep(700);
    await p.scrollMain(330);
    const grid = await p.locate('[data-testid="stTabPanel"] [data-testid="stDataFrame"]');
    await p.moveTo(grid.left + 60, grid.top + 70);
    await p.moveTo(grid.left + 900, grid.top + 140);
    await p.scrollMain(0, 1200);
    await p.click(sidebar, { text: 'Ziel 2 · Arbeit' });
    await t.rerun();
    await p.hover('[data-testid="stMetric"]', { nth: 3 });
    await p.click(sidebar, { text: 'Ziel 3 · Ohne Sozialhilfe' });
    await t.rerun();
    await p.hover('[data-testid="stMetric"]', { nth: 0 });
  },

  async calls(t) {
    const p = t.page;
    await p.click(sidebar, { text: 'Ziel 1 · Sprache' });
    await t.rerun();
    await p.click(sidebar, { text: 'Sozialarbeiter:in' });
    await t.rerun();
    await p.click(tab, { text: 'Wen rufe ich an?' });
    await sleep(900);
    await p.hover('[data-testid="stTabPanel"] [data-testid="stMarkdownContainer"] p', { text: '· Alter', nth: 0 });
    await sleep(900);
    await p.hover('[data-testid="stTabPanel"] [data-testid="stMarkdownContainer"] p', { text: 'Ziel 3:', nth: 0 });
    await sleep(700);
    await p.hover('[data-testid="stTabPanel"] [data-testid="stMarkdownContainer"] p', { text: '· Alter', nth: 1 });
    await p.scrollMain(420, 2500);
  },

  async money(t) {
    const p = t.page;
    await p.scrollMain(0, 800);
    await p.click(sidebar, { text: 'Leitung' });
    await t.rerun();
    await p.click(tab, { text: 'Datenqualität' });
    await sleep(800);
    const grid = await p.locate('[data-testid="stTabPanel"] [data-testid="stDataFrame"]', { nth: 0 });
    // Rows are about 35 CSS px; the fifth row is goal 1's "proven but not recorded".
    await p.moveTo(grid.left + 620, grid.top + 35 * 5 + 17);
    await p.ripple();
    await sleep(1200);
    await p.moveTo(grid.left + 1050, grid.top + 35 * 5 + 17);
  },

  async patterns(t) {
    const p = t.page;
    await p.click(tab, { text: 'Muster' });
    await sleep(900);
    await p.hover('[data-testid="stTabPanel"] [data-testid="stMarkdownContainer"] li', { nth: 0 });
    await sleep(800);
    await p.click('[data-testid="stSelectbox"] button[aria-haspopup="listbox"]');
    await sleep(500);
    await p.click('[role="option"]', { text: 'Lateinisch alphabetisiert' });
    await t.rerun();
    await p.scrollMain(560, 2200);
    await p.hover('[data-testid="stVegaLiteChart"], [data-testid="stArrowVegaLiteChart"], .vega-embed', { nth: 0 });
    await sleep(1200);
    await p.scrollMain(980, 2000);
  },

  async excel(t) {
    const p = t.page;
    await p.scrollMain(0, 900);
    await p.hover('[data-testid="stDownloadButton"] button');
    await p.ripple();
    await sleep(900);
    await p.click(tab, { text: 'Liste' });
    await sleep(800);
    const grid = await p.locate('[data-testid="stTabPanel"] [data-testid="stDataFrame"]');
    await p.moveTo(grid.left + 300, grid.top + 120);
  },

  async outro(t) {
    const p = t.page;
    await p.goto(`${SLIDES}?s=privacy`);
    await sleep(5200);
    await p.goto(`${SLIDES}?s=cover`);
  },
};

/** Visit every view once so the recording never waits on a first computation. */
async function warmUp(p, app) {
  await p.goto(app);
  await p.idle();
  for (const label of ['Ziel 2 · Arbeit', 'Ziel 3 · Ohne Sozialhilfe', 'Ziel 1 · Sprache', 'Sozialarbeiter:in', 'Leitung']) {
    await p.click(sidebar, { text: label });
    await p.idle();
  }
  await p.click(tab, { text: 'Muster' });
  await p.click('[data-testid="stSelectbox"] button[aria-haspopup="listbox"]');
  await p.click('[role="option"]', { text: 'Lateinisch alphabetisiert' });
  await p.idle();
  for (const url of ['cover', 'problem', 'privacy']) { await p.goto(`${SLIDES}?s=${url}`); await sleep(800); }
}

function parseArgs() {
  const o = { lang: 'en', only: null, app: 'http://localhost:8501', show: false };
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i], value = argv[i + 1];
    if (flag === '--lang') { o.lang = value; i++; }
    else if (flag === '--only') { o.only = value.split(','); i++; }
    else if (flag === '--app') { o.app = value.replace(/\/$/, ''); i++; }
    else if (flag === '--show') o.show = true;
    else throw new Error('unknown flag: ' + flag);
  }
  return o;
}

async function main() {
  const o = parseArgs();
  const out = join(HERE, 'build', o.lang);
  const durations = JSON.parse(await readFile(join(out, 'durations.json'), 'utf8'));
  const names = Object.keys(NARRATION.scenes).filter((n) => !o.only || o.only.includes(n));
  const framesDir = join(out, 'frames');
  await rm(framesDir, { recursive: true, force: true });
  await mkdir(framesDir, { recursive: true });

  const { child, profile, wsUrl } = await launchChrome(!o.show);
  const cdp = await Cdp.attach(wsUrl);
  const frames = [];
  try {
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    const page = new Page(cdp, sessionId);
    await page.send('Page.enable', {});
    await page.send('Runtime.enable', {});
    await page.send('Emulation.setDeviceMetricsOverride', { ...VIEWPORT, mobile: false });
    await page.send('Page.addScriptToEvaluateOnNewDocument', { source: CURSOR_SCRIPT });
    console.log('  warm-up');
    await warmUp(page, o.app);

    let pending = Promise.resolve();
    cdp.on('Page.screencastFrame', (params) => {
      const file = `f${String(frames.length).padStart(6, '0')}.jpg`;
      frames.push({ file, t: params.metadata.timestamp });
      pending = pending.then(() => writeFile(join(framesDir, file), Buffer.from(params.data, 'base64')));
      page.send('Page.screencastFrameAck', { sessionId: params.sessionId }).catch(() => {});
    });
    await page.send('Page.startScreencast', { format: 'jpeg', quality: 88, maxWidth: FRAME.width, maxHeight: FRAME.height, everyNthFrame: 1 });
    await sleep(500);

    const take = new Take(page, durations);
    take.app = o.app;
    for (const name of names) {
      const start = Date.now() / 1000;
      take.scenes.push({ name, start });
      console.log(`  ${name}`);
      await SCENES[name](take);
      const left = (durations[name] ?? 0) + SCENE_TAIL - take.outputSince(start);
      if (left > 0) await sleep(left * 1000);
    }
    const end = Date.now() / 1000;
    await page.send('Page.stopScreencast', {});
    await pending;
    await writeFile(join(out, 'timeline.json'), JSON.stringify({
      lang: o.lang, frame: FRAME, waitOut: WAIT_OUT, end, scenes: take.scenes, waits: take.waits, frames,
    }, null, 1));
    console.log(`  ${frames.length} frames, ${(end - take.scenes[0].start).toFixed(1)}s recorded`);
  } finally {
    cdp.close();
    child.kill();
    await rm(profile, { recursive: true, force: true }).catch(() => {});
  }
}

await main();
