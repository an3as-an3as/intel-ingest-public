import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateLogoFile, logoUrl, summaryBrandHtml, THEMES} from '../appearance.js';

const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

test('logo validation rejects SVG and oversize files', () => {
  assert.equal(validateLogoFile({type:'image/png', size:1000}), null);
  assert.match(validateLogoFile({type:'image/svg+xml', size:10}), /SVG/);
  assert.match(validateLogoFile({type:'image/png', size:600*1024}), /512 KB/);
  assert.ok(validateLogoFile(null));
});

test('logo URL is cache-busted and absent when no logo', () => {
  assert.equal(logoUrl({has_logo:false}), null);
  assert.equal(logoUrl({has_logo:true, version:'abc'}), '/api/branding/logo?v=abc');
});

test('summary header escapes dashboard names and includes logo only when present', () => {
  const html = summaryBrandHtml({has_logo:true, version:'v1'}, '<b>x</b>', esc);
  assert.match(html, /\/api\/branding\/logo\?v=v1/);
  assert.ok(!html.includes('<b>x</b>'));
  assert.ok(!summaryBrandHtml({has_logo:false}, 'Name', esc).includes('<img'));
});

test('three theme modes and Obsidian purple tokens for both themes', () => {
  assert.deepEqual(Object.keys(THEMES), ['system','light','dark']);
  const css = readFileSync(new URL('../styles.css', import.meta.url), 'utf8');
  assert.match(css, /--primary: #8a5cf5/);
  assert.match(css, /--background: #1e1e1e/);
  assert.match(css, /--background: #f6f6f6/);
  assert.match(css, /:root\[data-theme="dark"\]/);
});

import {initials, DEFAULT_NAME, FONT_LABELS} from '../appearance.js';

test('app name helpers: initials and curated fonts matching the server list', () => {
  assert.equal(initials('Intel Ingest'), 'II');
  assert.equal(initials('Nordic'), 'NO');
  assert.equal(initials('  '), '·');
  assert.equal(DEFAULT_NAME.text, 'Intel Ingest');
  assert.deepEqual(Object.keys(FONT_LABELS).sort(), ['condensed','geometric','humanist','inter','mono','serif','slab','system']);
});
