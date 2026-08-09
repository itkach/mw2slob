/*
 * MediaWiki.js - bootstraps MathJax 4 to render MediaWiki math offline.
 *
 * Loaded as a module script from article HTML (see MATH_JAX_SCRIPTS in
 * mw2slob/convert.py). Configures MathJax, loads the bundled tex-svg
 * component (TeX input, SVG output - no external fonts or network
 * access needed, since tex-svg.js embeds its own font glyph data and
 * SVG output embeds the glyph paths it uses directly in each formula),
 * then renders every MediaWiki math element found in the document.
 */

import { TEXVC_MACROS } from './texvc.js';
import { renderMath } from './wiki2jax.js';

// Absolute URL of this MathJax directory. Must be absolute (not e.g.
// "./~/MathJax/") because the loader's own require() below runs from
// wherever this module happens to be loaded from, and a relative path
// would get re-resolved against that (and, since this module itself
// lives inside the MathJax directory, doubled up).
const MATHJAX_BASE = new URL('.', import.meta.url).href;

// tex-svg.js bundles a right-click context-menu extension whose real
// Menu class unconditionally (regardless of enableMenu, and regardless
// of any of its settings we configure) does two things from inside its
// own constructor: reads/writes MathJax-Menu-Settings in localStorage,
// and schedules an "apply these settings" pass once the document is
// ready. That pass tries to reconcile things we don't ship - it
// compares the (possibly stale, persisted) renderer setting against
// our actual SVG-only output and tries to fetch output/chtml.js, and
// separately tries to fetch a11y/complexity.js - and since neither
// file exists here, those fetches fail. Worse, that failure rejects
// MathJax.startup.promise itself, which was silently killing math
// rendering entirely, not just the menu.
//
// The one thing MathJax's document-level code reads directly off the
// menu object (synchronously, in the document mixin's own constructor,
// not the real Menu's) is `.settings`, to compute enableEnrichment/
// enableSpeech/enableBraille/enableComplexity - so a stub providing
// just that, with everything off, is enough to fully neutralize the
// real Menu's behavior while keeping speech/enrichment disabled too.
class NoMenu {
  constructor() {
    this.settings = { enrich: false, speech: false, braille: false, collapsible: false };
  }
}

globalThis.MathJax = {
  loader: {
    paths: { mathjax: MATHJAX_BASE },
    require: (url) => import(url),
  },
  tex: {
    // tex-svg.js activates base/ams/newcommand/textmacros/noundefined/
    // require/autoload/configmacros by default. color, cancel, unicode,
    // boldsymbol and mhchem are not compiled into the bundle, but are
    // shipped alongside as separate files (see input/tex/extensions/)
    // and picked up on demand by the default "autoload" package when
    // their macros are first used - no network access needed, since
    // the fetch is same-origin/relative.
    macros: TEXVC_MACROS,
  },
  svg: {
    fontCache: 'local',
  },
  startup: {
    typeset: false,
  },
  options: {
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'option'],
    // No context menu (most of its entries need features - speech,
    // the online "Show Source" popup, etc - we don't ship or that
    // don't apply to a static offline dictionary page), and no real
    // Menu instance backing it - see NoMenu above for why.
    enableMenu: false,
    MenuClass: NoMenu,
  },
};

import('mathjax/tex-svg.js')
  .then(() => MathJax.startup.promise)
  .then(() => renderMath(document))
  .catch((err) => console.error('[MathJax] failed to render math:', err));
