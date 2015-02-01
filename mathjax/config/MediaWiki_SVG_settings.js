MathJax.Hub.Config({
  showMathMenu: false,
  showMathMenuMSIE: false,
  jax: ["input/TeX","output/SVG"],
  SVG: {
    font: "STIX-Web",
    addMMLclasses: true
  },
  TeX: {extensions: ["noErrors.js",
                     "noUndefined.js",
                     "AMSmath.js",
                     "AMSsymbols.js",
                     "texvc.js",
                     "color.js",
                     "cancel.js"]}
});

var $$mathjaxOnLoadTime;

MathJax.Hub.Register.StartupHook("onLoad",function () {
  $$mathjaxOnLoadTime = new Date().getTime();
});

MathJax.Hub.Queue(function () {
  console.log("[MATHJAX] SVG: done in " + (new Date().getTime() - $$mathjaxOnLoadTime));
});
