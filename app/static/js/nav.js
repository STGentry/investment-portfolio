(function () {
  'use strict';

  var sidebar = document.getElementById('sidebar');
  var toggle = document.getElementById('sidebar-toggle');
  var nav = document.getElementById('sidebar-nav');
  if (!sidebar || !toggle || !nav) {
    return;
  }

  var STORAGE_KEY = 'portfolio-sidebar';
  var narrowQuery = window.matchMedia('(max-width: 900px)');

  function readPreference() {
    try {
      var saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved === 'expanded') {
        return true;
      }
      if (saved === 'collapsed') {
        return false;
      }
    } catch (error) {
      /* localStorage unavailable; fall back to the breakpoint default. */
    }
    return null;
  }

  function writePreference(expanded) {
    try {
      window.localStorage.setItem(STORAGE_KEY, expanded ? 'expanded' : 'collapsed');
    } catch (error) {
      /* localStorage unavailable; the preference simply will not persist. */
    }
  }

  function applyState(expanded, persist) {
    sidebar.classList.toggle('collapsed', !expanded);
    sidebar.classList.toggle('expanded', expanded);
    toggle.setAttribute('aria-expanded', String(expanded));
    toggle.setAttribute('aria-label', expanded ? 'Collapse navigation' : 'Expand navigation');
    if (persist) {
      writePreference(expanded);
    }
  }

  var preference = readPreference();
  var expanded = preference === null ? !narrowQuery.matches : preference;
  applyState(expanded, false);

  toggle.addEventListener('click', function () {
    expanded = !expanded;
    applyState(expanded, true);
  });

  function syncActiveLink() {
    var path = window.location.pathname;
    var links = nav.querySelectorAll('a.nav-link');
    for (var i = 0; i < links.length; i++) {
      var link = links[i];
      var active = link.getAttribute('href') === path ||
        (path === '/index.html' && link.getAttribute('href') === '/');
      if (active) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page');
      } else {
        link.classList.remove('active');
        link.removeAttribute('aria-current');
      }
    }
  }

  syncActiveLink();
  window.addEventListener('popstate', syncActiveLink);

  if (narrowQuery.addEventListener) {
    narrowQuery.addEventListener('change', function () {
      if (preference === null && narrowQuery.matches !== expanded) {
        expanded = !narrowQuery.matches;
        applyState(expanded, false);
      }
    });
  }
})();