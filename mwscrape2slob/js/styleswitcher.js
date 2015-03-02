(function(){

  function maybeCall(funcName, args) {
    if (typeof window.$SLOB === 'object' && window.$SLOB !== null) {
      var maybeFunc = window.$SLOB[funcName];
      if (maybeFunc && typeof(maybeFunc) === 'function') {
        console.debug('Calling ' + funcName + ' with args ', args);
        return maybeFunc.apply(window.$SLOB, args);
      }
      else {
        console.debug('Not a function in window.$SLOB: ' + funcName);
      }
    }
    return undefined;
  };

  function parseQs(a) {
    if (!a) return {};
    var b = {}, i;
    for (i = a.length - 1; i > -1; --i) {
      var p=a[i].split('=', 2);
      if (p.length === 1) {
        b[p[0]] = "";
      }
      else {
        b[p[0]] = decodeURIComponent(p[1].replace(/\+/g, " "));
      }
    }
    return b;
  }

  function qsFromLocation() {
    return parseQs(window.location.search.substr(1).split('&'));
  }

  var styleSwitcher = function() {

    var getAvailable = function(root) {
      if (!root) {
        root = document;
      }
      var result = [];
      var links = root.getElementsByTagName('link');
      if (!links) {
        return result;
      }
      var i, link, rel, title;
      for (i = 0; i < links.length; i++) {
        link = links[i];
        title = link.getAttribute('title');
        if (!title) {
          continue;
        }
        rel = link.getAttribute('rel');
        if (rel) {
          var rels = rel.split(' ');
          if (rels.indexOf('stylesheet') < 0) {
            continue;
          }
          result.push(link);
        }
      }
      return result;
    };

    return {

      getTitles: function(root) {
        var styles = getAvailable(root),
            i, result = [];
        for (i = 0; i < styles.length; i++) {
          result.push(styles[i].title);
        }
        return result;
      },

      setStyle: function(title, root) {
        var styles = getAvailable(root), i, style, rel, styleWasSet = false;
        for (i = 0; i < styles.length; i++) {
          style = styles[i];
          style.disabled = true;
          if (style.getAttribute('title') === title) {
            style.disabled = false;
            styleWasSet = true;
          }
        }
        if (styleWasSet) {
          console.debug('Notifying style for ' + window.location + ' set to ' + title);
          maybeCall('onStyleSet', [title]);
        }
      }
    };

  }();

  document.addEventListener('DOMContentLoaded', function(event) {
    var styles = styleSwitcher.getTitles();
    console.debug('Found ' + (styles ? styles.length : 0) + ' style(s)', styles);
    maybeCall('setStyleTitles', [styles]);
    if (styles && styles.length) {
      var preferredStyle = maybeCall('getPreferredStyle');
      if (preferredStyle) {
        console.debug('Setting style from window.$SLOB: ' + preferredStyle);
        styleSwitcher.setStyle(preferredStyle);
        return;
      }
      var qs = qsFromLocation();
      if (qs.style) {
        console.debug('Setting style from query string: ' + qs.style);
        styleSwitcher.setStyle(qs.style);
      }
    }

  });

  //export style switcher as global if window.$SLOB expressed interest
  var exportName = maybeCall('exportStyleSwitcherAs');
  if (exportName) {
    console.debug("Exporting style switcher as window." + exportName);
    window[exportName] = styleSwitcher;
  }
  //export style switcher via callback if window.$SLOB expressed interest
  maybeCall('setStyleSwitcher', [styleSwitcher]);

})();
