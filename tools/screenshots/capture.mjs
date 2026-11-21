/**
 * Screenshots for the user manual (doc/img/*.png), taken from the running app with the synthetic demo data.
 *
 *   streamlit run app.py            # in another window, on http://localhost:8501
 *   node tools/screenshots/capture.mjs [--app http://localhost:8501]
 *
 * Drives the installed Chrome headless over the DevTools Protocol, with Node's built-in WebSocket; nothing to install.
 */
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, '..', '..', 'doc', 'img');
const DATA = resolve(HERE, '..', '..', 'data');
const REPORTS = ['Situationsanalyse_D12.10000.docx', 'Situationsanalyse_D12.10002.docx', 'Situationsanalyse_D12.10003.docx'];
const VIEWPORT = { width: 1440, height: 900, deviceScaleFactor: 1 };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Cdp {
  #ws; #id = 1; #pending = new Map(); #listeners = new Map();
  static async attach(url) {
    const c = new Cdp();
    c.#ws = new WebSocket(url);
    await new Promise((ok, fail) => { c.#ws.addEventListener('open', ok, { once: true }); c.#ws.addEventListener('error', fail, { once: true }); });
    c.#ws.addEventListener('message', (e) => {
      const m = JSON.parse(e.data);
      if (m.id && c.#pending.has(m.id)) {
        const { ok, fail } = c.#pending.get(m.id);
        c.#pending.delete(m.id);
        m.error ? fail(new Error(m.error.message)) : ok(m.result);
      } else if (m.method) for (const fn of c.#listeners.get(m.method) ?? []) fn(m.params);
    });
    return c;
  }
  send(method, params = {}, sessionId) {
    const id = this.#id++;
    return new Promise((ok, fail) => { this.#pending.set(id, { ok, fail }); this.#ws.send(JSON.stringify({ id, method, params, sessionId })); });
  }
  once(method) {
    return new Promise((ok) => {
      const fn = (p) => { const l = this.#listeners.get(method); l.splice(l.indexOf(fn), 1); ok(p); };
      if (!this.#listeners.has(method)) this.#listeners.set(method, []);
      this.#listeners.get(method).push(fn);
    });
  }
  close() { this.#ws.close(); }
}

class Page {
  constructor(cdp, sessionId) { this.cdp = cdp; this.sid = sessionId; }
  send(method, params) { return this.cdp.send(method, params, this.sid); }
  async eval(body) {
    const r = await this.send('Runtime.evaluate', { expression: `(async () => { ${body} })()`, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
    return r.result.value;
  }
  async goto(url) {
    const loaded = this.cdp.once('Page.loadEventFired');
    await this.send('Page.navigate', { url });
    await Promise.race([loaded, sleep(20000)]);
  }
  /** Streamlit finished its rerun: no status widget, no stale elements, tabs present – three checks in a row. */
  async idle(timeoutMs = 180000) {
    await sleep(400);
    let calm = 0;
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const busy = await this.eval(`return !!document.querySelector('[data-testid="stStatusWidget"]') || !!document.querySelector('[data-stale="true"]') || !document.querySelector('[data-testid="stTab"], [data-testid="stFileUploader"]');`);
      calm = busy ? 0 : calm + 1;
      if (calm >= 3) return;
      await sleep(250);
    }
    throw new Error('app did not become idle');
  }
  async locate(selector, { text, nth = 0 } = {}) {
    return this.eval(`
      let list = [...document.querySelectorAll(${JSON.stringify(selector)})].filter(e => e.getClientRects().length > 0);
      ${text ? `list = list.filter(e => e.textContent.includes(${JSON.stringify(text)}));` : ''}
      const el = list[${nth}];
      if (!el) throw new Error(${JSON.stringify(`nothing matches ${selector} ${text ?? ''}`)});
      el.scrollIntoView({ block: 'nearest' });
      await new Promise(r => setTimeout(r, 150));
      const b = el.getBoundingClientRect();
      return { x: Math.round(b.left + Math.min(b.width / 2, 60)), y: Math.round(b.top + b.height / 2), top: b.top, left: b.left, w: b.width, h: b.height };
    `);
  }
  async click(selector, opts) {
    const p = await this.locate(selector, opts);
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: p.x, y: p.y });
    await this.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: p.x, y: p.y, button: 'left', clickCount: 1 });
    await this.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: p.x, y: p.y, button: 'left', clickCount: 1 });
    await sleep(400);
    return p;
  }
  async waitFor(expr, timeoutMs = 120000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) { if (await this.eval(expr)) return; await sleep(300); }
    const seen = await this.eval(`return [...document.querySelectorAll('[data-testid="stTabPanel"] button, [data-testid="stAlert"], [data-testid="stException"]')]
      .filter(e => e.getClientRects().length).map(e => e.textContent.trim().slice(0, 80)).join(' | ');`);
    throw new Error(`timed out: ${expr}\non screen: ${seen}`);
  }
  async upload(selector, files) {
    const { root } = await this.send('DOM.getDocument', { depth: -1, pierce: true });
    const { nodeId } = await this.send('DOM.querySelector', { nodeId: root.nodeId, selector });
    if (!nodeId) throw new Error('no file input: ' + selector);
    await this.send('DOM.setFileInputFiles', { nodeId, files });
    await sleep(1500);
  }
  async scrollMain(to) {
    await this.eval(`document.querySelector('[data-testid="stMain"]').scrollTop = ${to};`);
    await sleep(600);
  }
  async shot(name, clip) {
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: VIEWPORT.width - 5, y: VIEWPORT.height - 5 });
    await sleep(500);
    const params = { format: 'png', captureBeyondViewport: false };
    if (clip) params.clip = { ...clip, scale: 1 };
    const { data } = await this.send('Page.captureScreenshot', params);
    await writeFile(join(OUT, `${name}.png`), Buffer.from(data, 'base64'));
    console.log(`  ${name}.png`);
  }
}

const sidebar = '[data-testid="stSidebar"] label';
const tab = '[data-testid="stTab"]';

async function launchChrome() {
  const chrome = [process.env.CHROME, 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe', '/usr/bin/google-chrome'].filter(Boolean).find((p) => existsSync(p));
  if (!chrome) throw new Error('Chrome not found; set CHROME to its path');
  const port = 9300 + Math.floor(Math.random() * 500);
  const profile = await mkdtemp(join(tmpdir(), 'cockpit-shots-'));
  const child = spawn(chrome, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--hide-scrollbars', '--force-color-profile=srgb',
    '--lang=de-CH', 'about:blank'], { stdio: 'ignore' });
  for (let i = 0; i < 100; i++) {
    try { return { child, profile, ws: (await (await fetch(`http://127.0.0.1:${port}/json/version`)).json()).webSocketDebuggerUrl }; }
    catch { await sleep(200); }
  }
  throw new Error('Chrome did not open a debugging port');
}

async function main() {
  const i = process.argv.indexOf('--app');
  const app = i > 0 ? process.argv[i + 1].replace(/\/$/, '') : 'http://localhost:8501';
  await mkdir(OUT, { recursive: true });
  const { child, profile, ws } = await launchChrome();
  const cdp = await Cdp.attach(ws);
  try {
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    const p = new Page(cdp, sessionId);
    await p.send('Page.enable');
    await p.send('Runtime.enable');
    await p.send('DOM.enable');
    await p.send('Emulation.setDeviceMetricsOverride', { ...VIEWPORT, mobile: false });
    await p.goto(app);
    await p.idle();

    // Management view, goal 1
    await p.shot('01-cockpit-management');
    const side = await p.locate('[data-testid="stSidebar"]');
    await p.shot('02-sidebar', { x: 0, y: 0, width: Math.round(side.w), height: VIEWPORT.height });
    await p.shot('03-metrics', { x: Math.round(side.w), y: 0, width: VIEWPORT.width - Math.round(side.w), height: 300 });

    await p.click(tab, { text: 'Übersicht' }); await p.idle();
    await p.shot('04-overview');

    await p.click(tab, { text: 'Muster' }); await p.idle();
    await p.shot('05-patterns-insights');
    await p.click('[data-testid="stTabPanel"] [data-testid="stSelectbox"] button[aria-haspopup="listbox"], [data-testid="stTabPanel"] [data-testid="stSelectbox"] [role="combobox"]');
    await p.click('[role="option"]', { text: 'Lateinisch alphabetisiert' }); await p.idle();
    const chart = await p.locate('[data-testid="stTabPanel"] [data-testid="stSelectbox"]');
    await p.scrollMain(Math.max(0, chart.top - 120));
    await p.shot('06-patterns-chart');
    await p.scrollMain(0);

    await p.click(tab, { text: 'Situationsanalysen' }); await p.idle();
    await p.shot('07-situationsanalysen');
    await p.upload('[data-testid="stTabPanel"] input[type="file"]', REPORTS.map((f) => join(DATA, 'situationsanalysen', f)));
    await p.waitFor(`return [...document.querySelectorAll('button')].some(b => b.textContent.includes('Merkmale extrahieren'));`);
    await p.click('button', { text: 'Merkmale extrahieren' }); await p.idle();
    await p.waitFor(`return !!document.querySelector('[data-testid="stDataFrame"], [data-testid="stDataEditor"]') && [...document.querySelectorAll('button')].some(b => b.textContent.includes('Geprüfte Merkmale'));`);
    const editor = await p.locate('button', { text: 'Merkmale extrahieren' });
    await p.scrollMain(Math.max(0, editor.top - 60));
    await p.shot('07b-situationsanalysen-result');
    await p.scrollMain(0);

    await p.click(tab, { text: 'Liste' }); await p.idle();
    await p.shot('08-list');

    await p.click(tab, { text: 'Datenqualität' }); await p.idle();
    await p.shot('09-data-quality');

    await p.click(tab, { text: 'Annahmen' }); await p.idle();
    await p.shot('10-assumptions');

    // Goals 2 and 3
    await p.click(tab, { text: 'Cockpit' });
    await p.click(sidebar, { text: 'Ziel 2 · Arbeit' }); await p.idle();
    await p.shot('11-goal2');
    await p.click(sidebar, { text: 'Ziel 3 · Ohne Sozialhilfe' }); await p.idle();
    await p.shot('12-goal3');
    await p.click(sidebar, { text: 'Ziel 1 · Sprache' }); await p.idle();

    // Social-worker view
    await p.click(sidebar, { text: 'Sozialarbeiter:in' }); await p.idle();
    await p.click(tab, { text: 'Wen rufe ich an?' }); await p.idle();
    const cards = await p.locate('[data-testid="stTabPanel"] [data-testid="stCaptionContainer"]', { text: 'rot (gefährdet)' });
    await p.scrollMain(Math.max(0, cards.top - 140));
    await p.shot('13-call-list');
    await p.scrollMain(0);
    await p.click(sidebar, { text: 'Leitung' }); await p.idle();

    // Upload mode
    await p.click(sidebar, { text: 'Eigene Exporte hochladen' }); await p.idle();
    await p.shot('14-upload');
  } finally {
    cdp.close();
    child.kill();
    await sleep(500);
    await rm(profile, { recursive: true, force: true }).catch(() => {});
  }
}

await main();
