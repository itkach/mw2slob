/**
 * texvc.js - MediaWiki texvc-compatible macros for MathJax 4
 *
 * MediaWiki's texvc/mathoid TeX dialect defines a number of macros and
 * symbols that are not part of plain TeX/LaTeX. MathJax 4 has no
 * "package" concept for a handful of macros like this - the supported
 * way to add them is the tex.macros config option, so this module just
 * exports a plain object suitable for that option instead of trying to
 * register a MathJax input jax extension.
 *
 * See https://www.mediawiki.org/wiki/Extension:Math/Texvc for the
 * symbols this mirrors.
 */

export const TEXVC_MACROS = {
  // Blackboard bold letters
  C: '\\mathbb{C}',
  Complex: '\\mathbb{C}',
  cnums: '\\mathbb{C}',
  H: '\\mathbb{H}',
  N: '\\mathbb{N}',
  natnums: '\\mathbb{N}',
  Q: '\\mathbb{Q}',
  R: '\\mathbb{R}',
  reals: '\\mathbb{R}',
  Reals: '\\mathbb{R}',
  Z: '\\mathbb{Z}',

  // Greek variants
  thetasym: '\\vartheta',
  koppa: '\\unicode{x3DF}',
  stigma: '\\unicode{x3DB}',
  coppa: '\\unicode{x3D9}',

  // Uppercase Greek letters that look like Latin letters, and so have
  // no standard LaTeX control sequence of their own
  Alpha: '\\unicode{x391}',
  Beta: '\\unicode{x392}',
  Epsilon: '\\unicode{x395}',
  Zeta: '\\unicode{x396}',
  Eta: '\\unicode{x397}',
  Iota: '\\unicode{x399}',
  Kappa: '\\unicode{x39A}',
  Mu: '\\unicode{x39C}',
  Nu: '\\unicode{x39D}',
  Omicron: '\\unicode{x39F}',
  Rho: '\\unicode{x3A1}',
  Tau: '\\unicode{x3A4}',
  Chi: '\\unicode{x3A7}',
  Koppa: '\\unicode{x3DE}',
  Stigma: '\\unicode{x3DA}',
  Coppa: '\\unicode{x3D8}',

  // Other ord symbols
  sect: '\\S',
  P: '\\P',
  AA: '\\unicode{xC5}',
  alef: '\\aleph',
  alefsym: '\\aleph',
  weierp: '\\wp',
  real: '\\Re',
  part: '\\partial',
  infin: '\\infty',
  empty: '\\emptyset',
  O: '\\emptyset',
  ang: '\\angle',
  exist: '\\exists',
  clubs: '\\clubsuit',
  diamonds: '\\diamondsuit',
  hearts: '\\heartsuit',
  spades: '\\spadesuit',
  textvisiblespace: '\\unicode{x2423}',

  // Binary operators/relations
  and: '\\land',
  or: '\\lor',
  bull: '\\bullet',
  plusmn: '\\pm',
  sdot: '\\cdot',
  supe: '\\supseteq',
  sube: '\\subseteq',
  isin: '\\in',

  // Arrows
  hAar: '\\Leftrightarrow',
  hArr: '\\Leftrightarrow',
  Harr: '\\Leftrightarrow',
  Lrarr: '\\Leftrightarrow',
  lrArr: '\\Leftrightarrow',
  lArr: '\\Leftarrow',
  Larr: '\\Leftarrow',
  rArr: '\\Rightarrow',
  Rarr: '\\Rightarrow',
  harr: '\\leftrightarrow',
  lrarr: '\\leftrightarrow',
  larr: '\\leftarrow',
  gets: '\\leftarrow',
  rarr: '\\rightarrow',
  uarr: '\\uparrow',
  darr: '\\downarrow',
  Uarr: '\\Uparrow',
  uArr: '\\Uparrow',
  Darr: '\\Downarrow',
  dArr: '\\Downarrow',
  rang: '\\rangle',
  lang: '\\langle',

  // Big operators (surface/volume integrals)
  oiint: '\\unicode{x222F}',
  oiiint: '\\unicode{x2230}',

  // Macros
  sgn: '\\operatorname{sgn}',
  arccot: '\\operatorname{arccot}',
  arcsec: '\\operatorname{arcsec}',
  arccsc: '\\operatorname{arccsc}',
  bold: ['\\mathbf{#1}', 1],
  // \href and \style are disabled (rendered inert) rather than
  // interpreted, same as upstream texvc does
  href: '\\operatorname{href}',
  style: '\\operatorname{style}',
  pagecolor: ['', 1],
  vline: '\\smash{\\large\\lvert}',
  image: '\\Im',
};
