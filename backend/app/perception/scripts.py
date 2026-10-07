"""Fixed in-page script used by perception. It is a constant of this
codebase: the model never supplies or influences any script text.

Defines `window.__agentqa` with:
  snapshot(opts)      -> interactive elements (+ stable ids, selector strategies),
                         viewport, DOM metadata
  fingerprint(el)     -> semantic fingerprint of one element (identity check)

Stable ids: NOT derived from CSS classes, DOM position or generated ids. The id
is a hash of a semantic fingerprint (role, tag, input type, normalized accessible
name with digits masked, name attr, test-id / stable id attr, href path, nearest
landmark). Identical fingerprints are disambiguated by DOM-order ordinal
('.2', '.3'). Field values that look sensitive are redacted here, in the page,
so raw secrets never cross into the Python process.
"""

AGENTQA_JS_VERSION = 2

AGENTQA_JS = r"""
(() => {
  if (window.__agentqa && window.__agentqa.version === 2) return true;

  const INTERACTIVE =
    'a[href],button,input:not([type="hidden"]),select,textarea,summary,' +
    '[role="button"],[role="link"],[role="checkbox"],[role="radio"],[role="tab"],[role="menuitem"],' +
    '[role="menuitemcheckbox"],[role="menuitemradio"],[role="switch"],[role="combobox"],[role="textbox"],' +
    '[role="searchbox"],[role="slider"],[role="option"],[role="treeitem"],' +
    '[contenteditable=""],[contenteditable="true"],[onclick],[tabindex]:not([tabindex="-1"])';
  const HEURISTIC_TAGS = 'div,span,li,td,img,svg,i,p,article,section';
  const TESTID_ATTRS = ['data-testid', 'data-test-id', 'data-test', 'data-cy', 'data-qa'];
  const ARIA_ROLES = new Set(['button','link','textbox','checkbox','radio','combobox','listbox','slider',
    'spinbutton','tab','menuitem','menuitemcheckbox','menuitemradio','switch','option','searchbox','treeitem']);
  const UNSTABLE_ID = /\d{3,}|[0-9a-f]{8,}|^:r|^(ember|radix|react|headlessui|mui|rc|css)[-_:]/i;
  const SENSITIVE = /pass(word|wd)?|pwd|secret|token|otp|cvv|cvc|ssn|card.?n(um|o)|api.?key/i;
  const LANDMARK_TAGS = new Set(['form','dialog','nav','main','header','footer','aside']);
  const LANDMARK_ROLES = new Set(['dialog','alertdialog','navigation','main','form','region','banner','contentinfo','complementary']);
  const REDACTED = '[redacted]';

  const clean = (s, n) => (s || '').replace(/\s+/g, ' ').trim().slice(0, n);
  const norm = (s) => clean(s, 60).toLowerCase().replace(/\d+/g, '#');

  function cyrb53(str, seed) {
    let h1 = 0xdeadbeef ^ (seed || 0), h2 = 0x41c6ce57 ^ (seed || 0);
    for (let i = 0; i < str.length; i++) {
      const ch = str.charCodeAt(i);
      h1 = Math.imul(h1 ^ ch, 2654435761);
      h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return 4294967296 * (2097151 & h2) + (h1 >>> 0);
  }
  const hex14 = (n) => n.toString(16).padStart(14, '0');

  function deepQuery(selector) {
    const out = [];
    const walk = (root) => {
      root.querySelectorAll(selector).forEach((e) => out.push(e));
      root.querySelectorAll('*').forEach((e) => { if (e.shadowRoot) walk(e.shadowRoot); });
    };
    walk(document);
    return out;
  }

  function roleOf(el) {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit.trim().split(/\s+/)[0].toLowerCase();
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return el.hasAttribute('href') ? 'link' : 'clickable';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return (el.multiple || el.size > 1) ? 'listbox' : 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      if (['button', 'submit', 'reset', 'image', 'file'].includes(t)) return 'button';
      if (t === 'checkbox') return 'checkbox';
      if (t === 'radio') return 'radio';
      if (t === 'range') return 'slider';
      if (t === 'number') return 'spinbutton';
      if (t === 'search') return 'searchbox';
      return 'textbox';
    }
    if (el.isContentEditable) return 'textbox';
    return 'clickable';
  }

  const byIds = (ids) => (ids || '').split(/\s+/).map((i) => {
    const r = i ? document.getElementById(i) : null;
    return r ? (r.innerText || r.textContent || '') : '';
  }).join(' ');

  function labelOf(el) {
    if (el.labels && el.labels.length) {
      return Array.from(el.labels).map((l) => l.innerText || l.textContent || '').join(' ');
    }
    return '';
  }

  function nameOf(el, tag, type) {
    const aria = el.getAttribute('aria-label');
    if (aria && aria.trim()) return aria;
    const lb = byIds(el.getAttribute('aria-labelledby'));
    if (lb.trim()) return lb;
    const lab = labelOf(el);
    if (lab.trim()) return lab;
    if (tag === 'input' && ['button', 'submit', 'reset'].includes(type)) {
      return el.value || (type === 'submit' ? 'Submit' : type === 'reset' ? 'Reset' : '');
    }
    if (tag === 'img' || (tag === 'input' && type === 'image')) return el.getAttribute('alt') || '';
    const txt = (tag === 'input' || tag === 'textarea' || tag === 'select') ? '' : (el.innerText || el.textContent || '');
    if (txt.trim()) return txt;
    return el.getAttribute('title') || el.getAttribute('placeholder') || '';
  }

  function landmarkOf(el) {
    let p = el.parentElement;
    for (let i = 0; p && i < 25; i++, p = p.parentElement) {
      const r = p.getAttribute('role');
      const t = p.tagName.toLowerCase();
      if (LANDMARK_TAGS.has(t) || (r && LANDMARK_ROLES.has(r))) {
        const lbl = p.getAttribute('aria-label') || p.getAttribute('name') ||
          (p.getAttribute('aria-labelledby') ? 'labelled' : '') || (UNSTABLE_ID.test(p.id) ? '' : p.id);
        return (r || t) + (lbl ? ':' + norm(lbl) : '');
      }
    }
    return '';
  }

  // Row/item context (nearest list item / table row / article heading text, digits masked).
  // Used ONLY to tell apart otherwise identical elements (e.g. one "Delete" per row), so ids
  // survive reordering and insertion.
  function contextOf(el) {
    const row = el.parentElement && el.parentElement.closest('li,tr,article,[role="listitem"],[role="row"]');
    if (!row) return '';
    const h = row.querySelector('h1,h2,h3,h4,h5,h6,strong,b,[role="heading"]');
    return norm((h ? h.innerText : row.innerText) || '');
  }
  const contextHash = (el) => { const c = contextOf(el); return c ? hex14(cyrb53(c)).slice(-6) : ''; };

  function testIdOf(el) {
    for (const a of TESTID_ATTRS) { const v = el.getAttribute(a); if (v) return [a, v]; }
    return null;
  }
  function stableIdOf(el) { return (el.id && !UNSTABLE_ID.test(el.id)) ? el.id : ''; }
  function hrefPathOf(el) {
    if (el.tagName !== 'A') return '';
    try { return new URL(el.getAttribute('href') || '', location.href).pathname.replace(/\d+/g, '#'); }
    catch (e) { return ''; }
  }

  // Semantic identity of an element. Deliberately excludes classes, position, generated ids.
  function fingerprintParts(el) {
    const tag = el.tagName.toLowerCase();
    const type = tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : '';
    const tid = testIdOf(el);
    const role = roleOf(el);
    const name = nameOf(el, tag, type);
    return {
      tag, type, role, name,
      base: [role, tag, type, norm(name), el.getAttribute('name') || '',
             tid ? tid[0] + '=' + tid[1] : stableIdOf(el), hrefPathOf(el), landmarkOf(el)].join('|'),
    };
  }
  const fingerprint = (el) => hex14(cyrb53(fingerprintParts(el).base));

  function cssPath(el) {
    const parts = [];
    let cur = el;
    for (let depth = 0; cur && cur.nodeType === 1 && depth < 6; depth++) {
      const tag = cur.tagName.toLowerCase();
      if (cur.id && !UNSTABLE_ID.test(cur.id)) {
        parts.unshift(tag + '[id="' + cur.id.replace(/["\\]/g, '\\$&') + '"]');
        break;
      }
      const parent = cur.parentElement;
      if (!parent) { parts.unshift(tag); break; }
      const same = Array.from(parent.children).filter((c) => c.tagName === cur.tagName);
      parts.unshift(same.length > 1 ? tag + ':nth-of-type(' + (same.indexOf(cur) + 1) + ')' : tag);
      cur = parent;
    }
    return parts.join(' > ');
  }

  function valueOf(el, tag, type, sensitive) {
    let v = null;
    if (tag === 'select') {
      const o = el.selectedOptions && el.selectedOptions[0];
      v = o ? (o.label || o.text || o.value) : '';
    } else if (tag === 'input') {
      if (['checkbox', 'radio', 'button', 'submit', 'reset', 'image', 'file'].includes(type)) return null;
      v = el.value;
    } else if (tag === 'textarea') {
      v = el.value;
    } else if (el.isContentEditable) {
      v = el.innerText;
    } else {
      return null;
    }
    if (v && sensitive) return REDACTED;
    return clean(v, opts_.maxValue);
  }

  let opts_ = { maxValue: 80, maxName: 80 };

  function snapshot(opts) {
    opts_ = Object.assign({ maxElements: 600, maxValue: 80, maxName: 80, tag: true }, opts || {});
    const vw = window.innerWidth, vh = window.innerHeight;

    const seen = new Set();
    let nodes = deepQuery(INTERACTIVE);
    nodes.forEach((n) => seen.add(n));

    // Clickable-but-not-semantic elements (cursor:pointer), outermost only.
    let scanned = 0;
    for (const el of deepQuery(HEURISTIC_TAGS)) {
      if (++scanned > 4000) break;
      if (seen.has(el) || el.closest(INTERACTIVE)) continue;
      const cs = getComputedStyle(el);
      if (cs.cursor !== 'pointer') continue;
      const parent = el.parentElement;
      if (parent && getComputedStyle(parent).cursor === 'pointer') continue;
      const label = (el.getAttribute('aria-label') || el.innerText || '').trim();
      if (!label) continue;
      seen.add(el); nodes.push(el);
    }

    // Pass 1: describe every candidate and count strategy keys.
    const recs = [];
    const keyCount = {};
    for (const el of nodes) {
      const parts = fingerprintParts(el);
      const { tag, type, role } = parts;
      const rect = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      const visible = rect.width > 0 && rect.height > 0 && cs.visibility !== 'hidden' &&
                      cs.visibility !== 'collapse' && cs.display !== 'none';
      const name = clean(parts.name, opts_.maxName);
      const label = clean(labelOf(el), opts_.maxName);
      const placeholder = el.getAttribute('placeholder');
      const tid = testIdOf(el);
      const sid = stableIdOf(el);
      const isControl = ['input', 'textarea', 'select'].includes(tag);
      const text = isControl ? label : clean(el.innerText || el.textContent || '', opts_.maxName);
      const sensitive = type === 'password' ||
        SENSITIVE.test(el.getAttribute('name') || '') || SENSITIVE.test(el.id || '') ||
        SENSITIVE.test(placeholder || '') || SENSITIVE.test(el.getAttribute('aria-label') || '') ||
        /password|cc-|one-time-code/i.test(el.getAttribute('autocomplete') || '');

      const strategies = [];
      if (tid) strategies.push({ kind: 'testid', value: tid[0] + '=' + tid[1] });
      if (sid) strategies.push({ kind: 'id', value: sid });
      if (ARIA_ROLES.has(role) && name) strategies.push({ kind: 'role', role, value: name });
      if (label && isControl) strategies.push({ kind: 'label', value: label });
      if (placeholder && isControl) strategies.push({ kind: 'placeholder', value: clean(placeholder, opts_.maxName) });
      if (!isControl && text && text.length <= 60) strategies.push({ kind: 'text', value: text });
      strategies.push({ kind: 'css', value: cssPath(el), fragile: true });
      for (const s of strategies) {
        s.key = s.kind + '|' + (s.role || '') + '|' + s.value;
        keyCount[s.key] = (keyCount[s.key] || 0) + 1;
      }
      recs.push({ el, parts, rect, visible, name, text, placeholder, sensitive, strategies, tag, type, role, ctx: contextOf(el) });
    }

    // Assign ids. Base id = hash of semantic fingerprint. Identical fingerprints are told apart by
    // row context when every context is distinct (order-independent), else by DOM-order ordinal.
    const groups = {};
    for (const r of recs) {
      r.fp = hex14(cyrb53(r.parts.base));
      r.baseId = 'e' + r.fp.slice(-6);
      (groups[r.baseId] = groups[r.baseId] || []).push(r);
    }
    for (const g of Object.values(groups)) {
      if (g.length === 1) { g[0].id = g[0].baseId; continue; }
      const sfx = g.map((r) => (r.ctx ? hex14(cyrb53(r.ctx)).slice(-4) : ''));
      const distinct = sfx.every((x) => x) && new Set(sfx).size === sfx.length;
      g.forEach((r, i) => {
        if (distinct) { r.id = r.baseId + '.' + sfx[i]; r.ctxHash = hex14(cyrb53(r.ctx)).slice(-6); }
        else { r.id = i === 0 ? r.baseId : r.baseId + '.' + (i + 1); }
      });
    }

    // Pass 2: nth per strategy, primary/fallback selection.
    const keyIndex = {};
    const out = [];
    let hidden = 0;
    for (const r of recs) {
      const id = r.id, fp = r.fp;
      for (const s of r.strategies) {
        const idx = keyIndex[s.key] || 0;
        keyIndex[s.key] = idx + 1;
        s.nth = keyCount[s.key] > 1 ? idx : null;
        s.unique = keyCount[s.key] === 1;
      }
      if (opts_.tag) r.el.setAttribute('data-agentqa-id', id);
      if (!r.visible) { hidden++; continue; }
      if (out.length >= opts_.maxElements) continue;

      const unique = r.strategies.find((s) => s.unique && s.kind !== 'css');
      const primary = unique || r.strategies.find((s) => s.kind !== 'css') || r.strategies[r.strategies.length - 1];
      const fallbacks = r.strategies.filter((s) => s !== primary).slice(0, 3)
        .map(({ key, unique, ...rest }) => rest);
      const { key: _k, unique: _u, ...primaryClean } = primary;

      const el = r.el, rect = r.rect;
      out.push({
        id, fp, role: r.role, tag: r.tag, type: r.type || null,
        name: r.name, text: r.text,
        ariaLabel: clean(el.getAttribute('aria-label'), opts_.maxName) || null,
        placeholder: r.placeholder ? clean(r.placeholder, opts_.maxName) : null,
        value: valueOf(el, r.tag, r.type, r.sensitive),
        href: r.tag === 'a' ? clean(el.getAttribute('href'), 200) : null,
        inViewport: rect.bottom > 0 && rect.right > 0 && rect.top < vh && rect.left < vw,
        enabled: !el.matches(':disabled') && el.getAttribute('aria-disabled') !== 'true',
        checked: (r.type === 'checkbox' || r.type === 'radio' || ['checkbox', 'radio', 'switch'].includes(r.role))
          ? (el.checked !== undefined ? !!el.checked : el.getAttribute('aria-checked') === 'true') : null,
        required: !!el.required || el.getAttribute('aria-required') === 'true',
        readonly: !!el.readOnly,
        focused: document.activeElement === el,
        box: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
        landmark: landmarkOf(el) || null,
        context: r.ctxHash || null,
        strategy: primaryClean, fallbacks,
      });
    }

    if (opts_.tag) {  // drop stale tags from nodes that are no longer candidates
      deepQuery('[data-agentqa-id]').forEach((e) => { if (!seen.has(e)) e.removeAttribute('data-agentqa-id'); });
    }

    return {
      elements: out,
      total: recs.length,
      hidden,
      viewport: {
        width: vw, height: vh, scroll_x: Math.round(window.scrollX), scroll_y: Math.round(window.scrollY),
        page_width: document.documentElement.scrollWidth, page_height: document.documentElement.scrollHeight,
        device_pixel_ratio: window.devicePixelRatio || 1,
      },
      ready_state: document.readyState,
      dom: domMetadata(),
    };
  }

  function domMetadata() {
    const q = (s) => Array.from(document.querySelectorAll(s));
    const landmarks = {};
    [['nav', 'nav'], ['main', 'main'], ['header', 'header'], ['footer', 'footer'], ['aside', 'aside'],
     ['form', 'form'], ['dialog', 'dialog,[role="dialog"]']].forEach(([k, s]) => {
      const n = q(s).length; if (n) landmarks[k] = n;
    });
    const meta = document.querySelector('meta[name="description"]');
    const dialogs = q('dialog[open],[role="dialog"],[role="alertdialog"],[aria-modal="true"]')
      .filter((d) => d.getBoundingClientRect().width > 0);
    return {
      lang: document.documentElement.lang || null,
      meta_description: meta ? clean(meta.getAttribute('content'), 200) : null,
      headings: q('h1,h2,h3').slice(0, 30).map((h) => ({ level: Number(h.tagName[1]), text: clean(h.innerText, 100) }))
        .filter((h) => h.text),
      landmarks,
      forms: q('form').slice(0, 5).map((f) => ({
        id: f.id || f.getAttribute('name') || null,
        method: (f.getAttribute('method') || 'get').toLowerCase(),
        action: f.getAttribute('action') ? f.getAttribute('action').split('?')[0].slice(0, 120) : null,
        field_count: f.elements.length,
      })),
      form_count: q('form').length,
      link_count: document.links.length,
      image_count: document.images.length,
      images_missing_alt: q('img:not([alt])').length,
      iframe_count: q('iframe,frame').length,
      dom_node_count: document.getElementsByTagName('*').length,
      open_dialog: dialogs.length > 0,
    };
  }

  window.__agentqa = { version: 2, snapshot, fingerprint, context: contextHash };
  return true;
})()
"""

# Visible (rendered) text of the page; innerText already excludes display:none.
VISIBLE_TEXT_JS = "(n) => (document.body ? document.body.innerText : '').slice(0, n)"
