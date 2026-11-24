// Theme (per browser) and shared logo branding (stored on the server).
export const THEMES = {system: 'System', light: 'Light', dark: 'Dark'};
const MAX_BYTES = 512 * 1024;
const TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];

export function storedTheme() {
  try { const v = localStorage.getItem('theme'); return v === 'light' || v === 'dark' ? v : 'system'; }
  catch { return 'system'; }
}

export function applyTheme(choice) {
  const root = document.documentElement;
  if (choice === 'light' || choice === 'dark') root.dataset.theme = choice;
  else delete root.dataset.theme;
  try { choice === 'system' ? localStorage.removeItem('theme') : localStorage.setItem('theme', choice); } catch {}
  window.dispatchEvent(new Event('themechange'));
}

export function logoUrl(branding) {
  return branding?.has_logo ? `/api/branding/logo?v=${encodeURIComponent(branding.version || '')}` : null;
}

export const DEFAULT_NAME = {text:'Intel Ingest', font:'inter', size:15, weight:650, italic:false,
  transform:'none', spacing:0.01, color:'foreground', show_mark:true};
export const FONT_LABELS = {system:'System UI', inter:'Inter / sans-serif', humanist:'Humanist (Gill Sans)',
  geometric:'Geometric (Avenir/Futura)', serif:'Serif (Georgia)', slab:'Slab serif (Rockwell)',
  mono:'Monospace', condensed:'Condensed'};
const COLORS = {foreground:'var(--text)', muted:'var(--text-2)', accent:'var(--primary-ink)'};

export function initials(text) {
  const words = String(text || '').trim().split(/\s+/).filter(Boolean);
  return ((words[0]?.[0] || '') + (words[1]?.[0] || words[0]?.[1] || '')).toUpperCase() || '·';
}

// Applied via the style object (not string interpolation), from curated values only.
export function applyNameStyle(element, name, fonts = {}) {
  const n = {...DEFAULT_NAME, ...(name || {})};
  element.textContent = n.text;
  Object.assign(element.style, {fontFamily: fonts[n.font] || '', fontSize: `${n.size}px`, fontWeight: String(n.weight),
    fontStyle: n.italic ? 'italic' : 'normal', textTransform: n.transform, letterSpacing: `${n.spacing}em`,
    color: COLORS[n.color] || COLORS.foreground});
  return element;
}

// Top-left brand: uploaded logo if present, otherwise an optional monogram mark.
export function renderBrand(branding) {
  const brand = document.querySelector('.brand');
  if (!brand) return;
  const name = {...DEFAULT_NAME, ...(branding?.name || {})}, url = logoUrl(branding);
  brand.replaceChildren();
  if (url) { const img = document.createElement('img'); img.className = 'brand-logo'; img.src = url; img.alt = ''; brand.append(img); }
  else if (name.show_mark) { const mark = document.createElement('span'); mark.className = 'brand-mark';
    mark.setAttribute('aria-hidden', 'true'); mark.textContent = initials(name.text); brand.append(mark); }
  const label = document.createElement('span'); label.className = 'brand-name';
  brand.append(applyNameStyle(label, name, branding?.fonts));
  brand.setAttribute('aria-label', name.text);
  document.title = document.title.replace(/Intel Ingest|^[^\[\]]*$/, name.text);
}

export function summaryBrandHtml(branding, dashboardName, esc) {
  const url = logoUrl(branding);
  return `<div class="summary-brand">${url ? `<img src="${url}" alt="Logo">` : ''}
    <div><div class="eyebrow">Intelligence summary</div><div class="dash-name">${esc(dashboardName || '')}</div></div></div>`;
}

export function validateLogoFile(file) {
  if (!file) return 'Choose an image file.';
  if (!TYPES.includes(file.type)) return 'Use a PNG, JPEG, WebP or GIF image. SVG is not accepted.';
  if (file.size > MAX_BYTES) return `Logo must be at most ${MAX_BYTES / 1024} KB.`;
  return null;
}

const readDataUrl = file => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = () => reject(new Error('Could not read the file'));
  reader.readAsDataURL(file);
});

export async function renderAppearanceSettings({api, state, esc, toast}, body) {
  let branding = await api('/api/branding');
  const draw = (message = '') => {
    const url = logoUrl(branding);
    const name = {...DEFAULT_NAME, ...(branding.name || {})};
    const theme = storedTheme();
    body.innerHTML = `<div class="stack">
      <div class="card pad"><h2>Theme</h2>
        <p class="small muted">Applies to this browser. System follows your operating system's light/dark setting.</p>
        <div class="theme-choice" role="radiogroup" aria-label="Theme">${Object.entries(THEMES).map(([k, l]) =>
          `<label><input type="radio" name="theme" value="${k}" ${theme === k ? 'checked' : ''}> ${l}</label>`).join('')}</div>
      </div>
      <div class="card pad"><h2>App name</h2>
        <p class="small muted">Shown in the top-left corner and browser tab for everyone using this installation.
          Fonts use fonts installed on each viewer's device; no external fonts are downloaded.</p>
        <form data-name-form>
          <div class="grid-3">
            <div><label for="name-text">Name</label><input id="name-text" name="text" maxlength="60" required value="${esc(name.text)}"></div>
            <div><label for="name-font">Font</label><select id="name-font" name="font">${Object.entries(FONT_LABELS).map(([k, l]) =>
              `<option value="${k}" ${name.font === k ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
            <div><label for="name-size">Size: <span data-size-out>${name.size}</span>px</label><input id="name-size" name="size" type="range" min="12" max="26" step="1" value="${name.size}"></div>
            <div><label for="name-weight">Weight</label><select id="name-weight" name="weight">${[[400,'Regular'],[500,'Medium'],[600,'Semibold'],[650,'Semibold+'],[700,'Bold'],[800,'Extra bold']].map(([v, l]) =>
              `<option value="${v}" ${name.weight === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
            <div><label for="name-transform">Letter case</label><select id="name-transform" name="transform">${[['none','As typed'],['uppercase','UPPERCASE'],['lowercase','lowercase'],['capitalize','Capitalize Words']].map(([v, l]) =>
              `<option value="${v}" ${name.transform === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
            <div><label for="name-spacing">Letter spacing: <span data-spacing-out>${name.spacing}</span>em</label><input id="name-spacing" name="spacing" type="range" min="-0.05" max="0.3" step="0.01" value="${name.spacing}"></div>
            <div><label for="name-color">Colour</label><select id="name-color" name="color">${[['foreground','Text'],['muted','Muted grey'],['accent','Purple accent']].map(([v, l]) =>
              `<option value="${v}" ${name.color === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
            <div><label class="inline"><input type="checkbox" name="italic" ${name.italic ? 'checked' : ''}> Italic</label>
              <label class="inline"><input type="checkbox" name="show_mark" ${name.show_mark ? 'checked' : ''}> Show initials badge when no logo</label></div>
          </div>
          <label>Preview</label>
          <div class="name-preview"><span data-name-preview></span></div>
          <div class="row" style="margin-top:12px"><button class="primary">Save name</button><button type="button" data-name-reset>Reset to default</button></div>
          <p role="status" class="small muted" data-name-message></p>
        </form>
      </div>
      <div class="card pad"><h2>Logo</h2>
        <p class="small muted">Shown in the top-left corner and in the header of intelligence summaries and HTML exports.
          Shared by everyone using this installation. PNG, JPEG, WebP or GIF up to ${branding.max_bytes / 1024} KB; a transparent PNG works best on both themes.</p>
        <div class="row" style="align-items:flex-start;margin-top:10px">
          <div class="logo-preview">${url ? `<img src="${url}" alt="Current logo">` : '<span class="small faint">No logo uploaded</span>'}</div>
          <div class="stack" style="min-width:220px">
            <label for="logo-file" style="margin-top:0">Upload image</label>
            <input id="logo-file" type="file" accept="image/png,image/jpeg,image/webp,image/gif">
            <div class="row"><button class="primary" data-upload>Save logo</button>
              <button class="danger" data-remove ${url ? '' : 'disabled'}>Remove logo</button></div>
          </div>
        </div>
        <p role="status" class="small muted" data-logo-message>${esc(message)}</p>
      </div></div>`;
    const form = body.querySelector('[data-name-form]');
    const readName = () => ({text: form.elements.text.value, font: form.elements.font.value, size: Number(form.elements.size.value),
      weight: Number(form.elements.weight.value), italic: form.elements.italic.checked, transform: form.elements.transform.value,
      spacing: Number(form.elements.spacing.value), color: form.elements.color.value, show_mark: form.elements.show_mark.checked});
    const preview = () => {
      const value = readName();
      form.querySelector('[data-size-out]').textContent = value.size;
      form.querySelector('[data-spacing-out]').textContent = value.spacing;
      applyNameStyle(form.querySelector('[data-name-preview]'), {...value, text: value.text || ' '}, branding.fonts);
    };
    form.addEventListener('input', preview); form.addEventListener('change', preview); preview();
    form.onsubmit = async event => {
      event.preventDefault();
      try {
        branding = await api('/api/branding/name', {method: 'PUT', body: readName()});
        state.meta.branding = branding; renderBrand(branding); draw(); toast('App name saved');
      } catch (err) { form.querySelector('[data-name-message]').textContent = err.message; }
    };
    form.querySelector('[data-name-reset]').onclick = async () => {
      try {
        branding = await api('/api/branding/name', {method: 'DELETE'});
        state.meta.branding = branding; renderBrand(branding); draw(); toast('App name reset');
      } catch (err) { form.querySelector('[data-name-message]').textContent = err.message; }
    };
    body.querySelectorAll('input[name=theme]').forEach(input => input.onchange = () => applyTheme(input.value));
    body.querySelector('[data-upload]').onclick = async () => {
      const file = body.querySelector('#logo-file').files[0];
      const problem = validateLogoFile(file);
      if (problem) { body.querySelector('[data-logo-message]').textContent = problem; return; }
      try {
        branding = await api('/api/branding/logo', {method: 'PUT', body: {data_url: await readDataUrl(file)}});
        state.meta.branding = branding; renderBrand(branding); draw('Logo saved.'); toast('Logo saved');
      } catch (err) { body.querySelector('[data-logo-message]').textContent = err.message; }
    };
    body.querySelector('[data-remove]').onclick = async () => {
      if (!confirm('Remove the logo for everyone using this installation?')) return;
      try {
        branding = await api('/api/branding/logo', {method: 'DELETE'});
        state.meta.branding = branding; renderBrand(branding); draw('Logo removed.');
      } catch (err) { body.querySelector('[data-logo-message]').textContent = err.message; }
    };
  };
  draw();
}
