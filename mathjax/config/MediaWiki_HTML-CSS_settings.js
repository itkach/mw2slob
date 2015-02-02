MathJax.Hub.Config({
  showMathMenu: false,
  showMathMenuMSIE: false,
  jax: ["input/TeX","output/HTML-CSS"],
  "HTML-CSS": {
    availableFonts: [],
    webFont: "STIX-Web"
  },
  TeX: {extensions: ["noErrors.js",
                     "noUndefined.js",
                     "AMSmath.js",
                     "AMSsymbols.js",
                     "texvc.js",
                     "color.js",
                     "cancel.js"]}
});

MathJax.Hub.processSectionDelay = 0;

var $$mathjaxOnLoadTime;

MathJax.Hub.Register.StartupHook("onLoad",function () {
  $$mathjaxOnLoadTime = new Date().getTime();
});

MathJax.Hub.Queue(function () {
  console.log("[MATHJAX] HTML-CSS: done in " + (new Date().getTime() - $$mathjaxOnLoadTime));
});
