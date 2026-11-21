/**
 * Renders the manuals in doc/en and doc/ro to PDF, next to their Markdown source.
 *
 *   node tools/docs-pdf/build.mjs
 *
 * Headless Chrome over the DevTools Protocol (Node's built-in WebSocket); marked and Mermaid are
 * loaded from jsdelivr, so the build needs internet access but nothing installed.
 * Links to other manuals point to their PDFs; links to repository files point to GitHub.
 */
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const REPO = 'https://github.com/cristiv123/integrations-cockpit/blob/main/';
const DOCS = ['doc/en/technical-documentation.md', 'doc/en/installation.md', 'doc/en/user-manual.md',
  'doc/ro/documentatie-tehnica.md', 'doc/ro/instalare.md', 'doc/ro/manual-utilizare.md'];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const CSS = `
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
:root { --ink: #1d2a36; --blue: #1F4E78; --rule: #d6dde4; --soft: #f3f6f9; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 10pt; line-height: 1.5; color: var(--ink); margin: 0; }
h1 { font-size: 22pt; color: var(--blue); margin: 0 0 6pt; line-height: 1.2; }
h2 { font-size: 15pt; color: var(--blue); margin: 22pt 0 6pt; padding-bottom: 3pt; border-bottom: 1.5pt solid var(--blue); break-after: avoid; }
h3 { font-size: 12pt; margin: 16pt 0 4pt; break-after: avoid; }
h4 { font-size: 10.5pt; margin: 12pt 0 4pt; break-after: avoid; }
h1 + p, h1 + p + p { color: #4a5a68; }
p, li { orphans: 3; widows: 3; }
a { color: var(--blue); text-decoration: none; }
code { font-family: Consolas, "Cascadia Mono", monospace; font-size: 8.8pt; background: var(--soft); padding: 0 2pt; border-radius: 2pt; }
pre { background: var(--soft); border: 0.5pt solid var(--rule); border-radius: 3pt; padding: 6pt 8pt; white-space: pre-wrap; word-break: break-word; break-inside: avoid; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 8.8pt; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { background: var(--blue); color: #fff; text-align: left; font-weight: 600; }
th, td { border: 0.5pt solid var(--rule); padding: 3pt 5pt; vertical-align: top; }
tbody tr:nth-child(even) td { background: #f8fafc; }
blockquote { margin: 8pt 0; padding: 4pt 10pt; border-left: 3pt solid var(--blue); background: var(--soft); break-inside: avoid; }
blockquote p { margin: 3pt 0; }
hr { border: none; border-top: 0.5pt solid var(--rule); margin: 14pt 0; }
img { max-width: 100%; border: 0.5pt solid var(--rule); break-inside: avoid; display: block; margin: 6pt auto; }
p:has(> img:only-child) { break-inside: avoid; }
.mermaid { text-align: center; margin: 8pt 0 12pt; break-inside: avoid; }
.mermaid svg { max-width: 100% !important; height: auto; max-height: 150mm; }
h2#contents + ol, h2#cuprins + ol { columns: 2; column-gap: 18pt; }
`;

const SCRIPT = `
import { marked } from 'https://cdn.jsdelivr.net/npm/marked@15.0.12/lib/marked.esm.js';
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs';
const slug = (t) => t.toLowerCase().trim().replace(/<[^>]+>/g, '').replace(/[^\\p{L}\\p{N}\\s_-]/gu, '').replace(/\\s/g, '-');
const used = new Map();
marked.use({ renderer: {
  heading({ tokens, depth, text }) {
    let id = slug(text); const n = used.get(id) ?? 0; used.set(id, n + 1); if (n) id += '-' + n;
    return '<h' + depth + ' id="' + id + '">' + this.parser.parseInline(tokens) + '</h' + depth + '>';
  },
  code({ text, lang }) {
    const esc = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return lang === 'mermaid' ? '<pre class="mermaid">' + esc + '</pre>' : '<pre><code>' + esc + '</code></pre>';
  },
  link({ href, title, tokens }) {
    return '<a href="' + window.__link(href) + '">' + this.parser.parseInline(tokens) + '</a>';
  },
} });
document.body.innerHTML = marked.parse(window.__md);
// key/value tables written as "| | |" have an empty header row: drop it
for (const thead of document.querySelectorAll('thead')) if (!thead.textContent.trim()) thead.remove();
mermaid.initialize({ startOnLoad: false, theme: 'default', fontFamily: 'Segoe UI, Arial, sans-serif',
  flowchart: { useMaxWidth: true, htmlLabels: true }, sequence: { useMaxWidth: true }, er: { useMaxWidth: true }, gantt: { useMaxWidth: true } });
await mermaid.run({ querySelector: '.mermaid' });
await Promise.all([...document.images].map((i) => i.complete ? null : new Promise((r) => { i.onload = i.onerror = r; })));
await document.fonts.ready;
window.__done = true;
`;

class Cdp {
  #ws; #id = 1; #pending = new Map(); #listeners = new Map();
  static async attach(url) {
    const c = new Cdp();
    c.#ws = new WebSocket(url);
    await new Promise((ok, fail) => { c.#ws.addEventListener('open', ok, { once: true }); c.#ws.addEventListener('error', fail, { once: true }); });
    c.#ws.addEventListener('message', (e) => {
      const m = JSON.parse(e.data);
      if (m.id && c.#pending.has(m.id)) { const { ok, fail } = c.#pending.get(m.id); c.#pending.delete(m.id); m.error ? fail(new Error(m.error.message)) : ok(m.result); }
      else if (m.method) for (const fn of c.#listeners.get(m.method) ?? []) fn(m.params);
    });
    return c;
  }
  send(method, params = {}, sessionId) {
    const id = this.#id++;
    return new Promise((ok, fail) => { this.#pending.set(id, { ok, fail }); this.#ws.send(JSON.stringify({ id, method, params, sessionId })); });
  }
  on(method, fn) { if (!this.#listeners.has(method)) this.#listeners.set(method, []); this.#listeners.get(method).push(fn); }
  close() { this.#ws.close(); }
}

/** Markdown link → PDF link: other manuals become their .pdf, repository files become GitHub URLs. */
function linker(mdPath) {
  return (href) => {
    if (/^(https?:|mailto:|#)/.test(href)) return href;
    const [path, hash = ''] = href.split('#');
    if (path.endsWith('.md') && DOCS.some((d) => resolve(ROOT, d) === resolve(dirname(mdPath), path))) {
      return path.replace(/\.md$/, '.pdf') + (hash ? '#' + hash : '');
    }
    const target = relative(ROOT, resolve(dirname(mdPath), path)).replace(/\\/g, '/');
    return REPO + target + (hash ? '#' + hash : '');
  };
}

async function launchChrome() {
  const chrome = [process.env.CHROME, 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe', '/usr/bin/google-chrome'].filter(Boolean).find((p) => existsSync(p));
  if (!chrome) throw new Error('Chrome not found; set CHROME to its path');
  const port = 9300 + Math.floor(Math.random() * 500);
  const profile = await mkdtemp(join(tmpdir(), 'cockpit-pdf-'));
  const child = spawn(chrome, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
    '--allow-file-access-from-files', '--no-first-run', 'about:blank'], { stdio: 'ignore' });
  for (let i = 0; i < 100; i++) {
    try { return { child, profile, ws: (await (await fetch(`http://127.0.0.1:${port}/json/version`)).json()).webSocketDebuggerUrl }; }
    catch { await sleep(200); }
  }
  throw new Error('Chrome did not open a debugging port');
}

const escapeHtml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

async function render(cdp, md, out) {
  const source = (await readFile(md, 'utf8')).replace(/\r\n/g, '\n');
  const title = source.match(/^# (.+)$/m)?.[1] ?? 'Integrations-Cockpit';
  const link = linker(md);
  const links = {};
  for (const m of source.matchAll(/\]\(([^)\s]+)\)/g)) links[m[1]] = link(m[1]);
  const html = `<!doctype html><html><head><meta charset="utf-8"><base href="${pathToFileURL(dirname(md)).href}/">
<title>${escapeHtml(title)}</title><style>${CSS}</style>
<script>window.__md = ${JSON.stringify(source)}; const L = ${JSON.stringify(links)}; window.__link = (h) => L[h] ?? h;</script>
<script type="module">${SCRIPT}</script></head><body></body></html>`;
  const tmp = join(tmpdir(), `cockpit-doc-${Date.now()}.html`);
  await writeFile(tmp, html);

  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  const send = (m, p) => cdp.send(m, p, sessionId);
  await send('Page.enable');
  await send('Runtime.enable');
  const errors = [];
  cdp.on('Runtime.exceptionThrown', (p) => { if (p) errors.push(p.exceptionDetails?.exception?.description ?? p.exceptionDetails?.text); });
  await send('Page.navigate', { url: pathToFileURL(tmp).href });
  for (let i = 0; i < 300; i++) {
    const r = await send('Runtime.evaluate', { expression: 'window.__done === true', returnByValue: true });
    if (r.result.value) break;
    if (i === 299) throw new Error(`${md}: rendering did not finish. ${errors.join(' | ')}`);
    await sleep(200);
  }
  const footer = `<div style="font-size:7.5pt;color:#6b7a88;width:100%;padding:0 16mm;display:flex;justify-content:space-between;font-family:Segoe UI,Arial">
    <span>${escapeHtml(title)}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`;
  const { data } = await send('Page.printToPDF', {
    printBackground: true, preferCSSPageSize: true, displayHeaderFooter: true,
    headerTemplate: '<div></div>', footerTemplate: footer, generateDocumentOutline: true, generateTaggedPDF: true,
  });
  await writeFile(out, Buffer.from(data, 'base64'));
  await cdp.send('Target.closeTarget', { targetId });
  await rm(tmp, { force: true });
}

const { child, profile, ws } = await launchChrome();
const cdp = await Cdp.attach(ws);
try {
  for (const doc of DOCS) {
    const md = resolve(ROOT, doc);
    const out = md.replace(/\.md$/, '.pdf');
    await render(cdp, md, out);
    console.log(`  ${relative(ROOT, out)}`);
  }
} finally {
  cdp.close();
  child.kill();
  await sleep(500);
  await rm(profile, { recursive: true, force: true }).catch(() => {});
}
