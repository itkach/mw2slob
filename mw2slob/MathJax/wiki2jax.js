/**
 * wiki2jax.js - render MediaWiki math elements offline with MathJax 4
 *
 * MediaWiki's HTML marks up formulas as
 *   <span class="mwe-math-element" data-tex="...">
 *     <span class="mwe-math-mathml-inline">...</span>
 *     <img class="mwe-math-fallback-image-inline" src="https://wikimedia.org/...">
 *   </span>
 * where data-tex holds the raw TeX source (set by mw2slob/convert.py from
 * the extension's data-mw.body.extsrc, since the original data-mw
 * attribute itself is stripped elsewhere in the conversion pipeline).
 * The fallback <img> points at the Wikimedia REST API and is useless
 * offline, so convert.py already strips its src/srcset.
 *
 * This module finds those elements and replaces each one with an SVG
 * rendered locally by MathJax, so no network access is needed.
 */

const MATH_SELECTOR = 'span.mwe-math-element[data-tex]';
const LEGACY_MATH_SELECTOR = 'img.tex[alt], img.mwe-math-fallback-image-inline[alt]';

// MediaWiki-specific TeX source massaging, ported from the old texvc
// wiki2jax prefilter. These are plain string transforms so they don't
// depend on any MathJax input jax hook.
function prefilter(tex) {
  return tex
    // MediaWiki source uses unescaped % as a literal percent sign
    .replace(/([^\\])%/g, '$1\\%')
    // MediaWiki's old surface/volume integral spacing hacks
    .replace(/\\iiint([^!]*)!\\!\\!\\!\\!.*\\subset\\!\\supset/g, '\\iiint$1\\!\\subset\\!\\supset')
    .replace(/\\iint([^!]*)!\\!\\!\\!\\!\\!\\!\\!\\!\\!\\!(.*)\\subset\\!\\supset/g, '\\iint$1$2\\subset\\!\\!\\supset')
    .replace(/\\int\\!\\!\\!(\\!)+\\int\\!\\!\\!(\\!)+\\int([^!]*)!\\!\\!\\!\\!.*\\bigcirc(\\,)*/g, '\\iiint$3\\subset\\!\\supset')
    .replace(/\\int\\!\\!\\!(\\!)+\\int([^!]*)!\\!\\!\\!\\!\\!\\!\\!\\!(.*)\\bigcirc(\\,)*/g, '\\iint$2$3\\subset\\!\\!\\supset');
}

// A math element is treated as display math when it is the only
// meaningful content of its parent (e.g. <dd><span class="mwe-math-element">
// ...</span></dd>), and as inline math otherwise (e.g. embedded in a
// sentence inside a <p>).
function isDisplay(node) {
  const parent = node.parentNode;
  if (!parent) {
    return false;
  }
  for (const sibling of parent.childNodes) {
    if (sibling === node) {
      continue;
    }
    if (sibling.nodeType === Node.TEXT_NODE && sibling.textContent.trim() === '') {
      continue;
    }
    return false;
  }
  return true;
}

async function renderOne(node, tex, display) {
  let typeset;
  try {
    typeset = await MathJax.tex2svgPromise(prefilter(tex), { display });
  } catch (err) {
    console.error('[wiki2jax] failed to render "%s": %s', tex, err.message);
    return;
  }
  node.replaceWith(typeset);
}

export async function renderMath(root) {
  const jobs = [];

  for (const node of root.querySelectorAll(MATH_SELECTOR)) {
    jobs.push(renderOne(node, node.getAttribute('data-tex'), isDisplay(node)));
  }

  for (const node of root.querySelectorAll(LEGACY_MATH_SELECTOR)) {
    jobs.push(renderOne(node, node.getAttribute('alt'), isDisplay(node)));
  }

  await Promise.all(jobs);
}
