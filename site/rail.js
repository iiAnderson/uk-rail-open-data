/*
 * The site rail — shared navigation for every visualisation.
 *
 * Injects itself into the left edge of whatever page loads it, so the pages
 * themselves carry no navigation markup and there is one place to add the next
 * visualisation. Collapsed it is 48px of icons; hovering expands it to 210px
 * *over* the page rather than pushing it, because a map that reflows every time
 * the pointer crosses the left edge is unusable. Clicking the pin makes the
 * width real and the page reflows once, deliberately.
 *
 * The page tells the rail which entry is current with data-page on <body>.
 * The theme lives here too — it is site furniture, not a per-page setting.
 *
 * No build step and no dependencies: the icons are inline SVG for the same
 * reason the fonts are the only remote asset on the site.
 */
(function () {
  'use strict';

  var RAIL_W = 48, OPEN_W = 210;

  /* Stroke icons on a 24-unit grid, drawn to read at 18px. currentColor
     throughout so the active and hover states need no separate artwork. */
  var ICON = {
    hours:
      '<circle cx="12" cy="12.5" r="7.5"/><path d="M12 8v4.5l3 2"/><path d="M9 2.5h6"/>',
    tracks:
      '<path d="M5 20.5c0-5 3-7 7-8s7-3 7-8"/><path d="M3 15h5M16 9h5"/>' +
      '<circle cx="5" cy="20.5" r="1.8"/><circle cx="19" cy="4.5" r="1.8"/>',
    home:
      '<path d="M3.5 11.2 12 3.5l8.5 7.7"/><path d="M5.5 12.8V20a.8.8 0 0 0 .8.8h3.4v-5.4h4.6v5.4h3.4a.8.8 0 0 0 .8-.8v-7.2"/>',
    blog:
      '<path d="M5 3.5h9l5 5V20a.5.5 0 0 1-.5.5h-13A.5.5 0 0 1 5 20z"/>' +
      '<path d="M13.8 3.6v5.1h5.1"/><path d="M8.3 13h7.4M8.3 16.4h5.2"/>',
    data:
      '<ellipse cx="12" cy="6" rx="7" ry="2.8"/>' +
      '<path d="M5 6v12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8V6"/><path d="M5 12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8"/>'
  };

  /* Adding a visualisation is one line here and nothing else. */
  var ITEMS = [
    { group: 'Visualisations' },
    { id: 'passenger-hours', name: 'Passenger hours', href: '/passenger-hours', icon: 'hours' },
    { id: 'tracks',          name: 'Track sections',  href: '/tracks',          icon: 'tracks' },
    { group: 'Elsewhere' },
    { id: 'home', name: 'Home',        href: 'https://robbiea.co.uk',      icon: 'home', ext: true },
    { id: 'blog', name: 'Blog',        href: 'https://blog.robbiea.co.uk', icon: 'blog', ext: true },
    { id: 'repo', name: 'The dataset', href: 'https://github.com/iiAnderson/uk-rail-open-data', icon: 'data', ext: true }
  ];

  var CSS = [
    '.siterail{position:fixed;top:0;left:0;bottom:0;width:' + RAIL_W + 'px;z-index:1200;',
    '  background:var(--raised);border-right:1px solid var(--rule);',
    '  display:flex;flex-direction:column;overflow:hidden;transition:width .16s ease}',
    '.siterail:hover,.siterail.pin{width:' + OPEN_W + 'px}',
    '.siterail:hover:not(.pin){box-shadow:6px 0 20px rgba(0,0,0,.34)}',
    ':root[data-theme="light"] .siterail:hover:not(.pin){box-shadow:6px 0 20px rgba(20,26,32,.13)}',
    '.siterail a{text-decoration:none}',
    '.siterail a:hover{text-decoration:none}',

    '.rl-mark{height:52px;flex:none;display:flex;align-items:center;gap:12px;',
    '  padding-left:14px;border-bottom:1px solid var(--rule);color:var(--accent)}',
    '.rl-mark svg{width:20px;height:20px;flex:none}',
    '.rl-mark span{font-family:var(--mono);font-size:10px;font-weight:600;letter-spacing:.07em;',
    '  white-space:nowrap;opacity:0;transition:opacity .12s}',

    '.rl-grp{padding:14px 0 5px;display:flex;flex-direction:column;gap:2px}',
    '.rl-grp+.rl-grp{border-top:1px solid var(--rs);margin-top:4px}',
    '.rl-hd{font-family:var(--mono);font-size:9px;font-weight:500;letter-spacing:.16em;',
    '  text-transform:uppercase;color:var(--muted);padding-left:15px;height:11px;',
    '  margin-bottom:4px;white-space:nowrap;opacity:0;transition:opacity .12s}',

    '.rl-item{display:flex;align-items:center;gap:12px;padding:8px 12px 8px 13px;',
    '  border-left:2px solid transparent;color:var(--ink2)}',
    '.rl-item:hover{background:var(--rs);color:var(--ink)}',
    '.rl-item[aria-current]{background:var(--rs);color:var(--hero);border-left-color:var(--accent)}',
    '.rl-item svg{width:18px;height:18px;flex:none;stroke:currentColor;fill:none;',
    '  stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}',
    '.rl-item[aria-current] svg{color:var(--accent)}',
    '.rl-item span{font-size:12px;white-space:nowrap;opacity:0;transition:opacity .12s}',

    '.rl-foot{margin-top:auto;padding:12px 13px 14px;display:flex;flex-direction:column;gap:10px}',
    '.rl-btn{background:none;border:1px solid var(--rule);border-radius:3px;color:var(--muted);',
    '  font-family:var(--mono);font-size:9px;letter-spacing:.12em;text-transform:uppercase;',
    '  padding:6px 0;cursor:pointer;display:flex;align-items:center;gap:11px;',
    '  padding-left:11px;width:100%;white-space:nowrap;overflow:hidden}',
    '.rl-btn:hover{color:var(--ink);border-color:var(--ink2)}',
    '.rl-btn b{font-family:var(--mono);font-size:12px;font-weight:400;width:18px;',
    '  flex:none;text-align:center;line-height:1}',
    '.rl-btn span{opacity:0;transition:opacity .12s}',
    '.rl-note{font-family:var(--mono);font-size:9px;letter-spacing:.1em;text-transform:uppercase;',
    '  color:var(--muted);white-space:nowrap;opacity:0;transition:opacity .12s;line-height:1.5}',

    /* Everything that only makes sense at full width fades in together. */
    '.siterail:hover .rl-mark span,.siterail.pin .rl-mark span,',
    '.siterail:hover .rl-hd,.siterail.pin .rl-hd,',
    '.siterail:hover .rl-item span,.siterail.pin .rl-item span,',
    '.siterail:hover .rl-btn span,.siterail.pin .rl-btn span,',
    '.siterail:hover .rl-note,.siterail.pin .rl-note{opacity:1}',

    /* The page is pushed by the collapsed width only; hover overlays it. */
    'body.has-rail{padding-left:' + RAIL_W + 'px}',
    'body.has-rail.rail-pinned{padding-left:' + OPEN_W + 'px}',

    '.siterail :focus-visible,.siterail a:focus-visible{outline:2px solid var(--accent);',
    '  outline-offset:-2px}',

    /* No hover on touch: the rail becomes a bar along the bottom edge. */
    '@media (max-width:900px){',
    '  .siterail{top:auto;right:0;bottom:0;width:auto;height:52px;flex-direction:row;',
    '    border-right:0;border-top:1px solid var(--rule);transition:none}',
    '  .siterail:hover,.siterail.pin{width:auto}',
    '  .siterail:hover:not(.pin){box-shadow:none}',
    '  .rl-mark,.rl-hd,.rl-note{display:none}',
    // Every destination stays reachable — the groups just run on from each
    // other instead of stacking. Pinning means nothing without a hover state.
    '  .rl-pin{display:none}',
    '  .rl-grp,.rl-grp+.rl-grp{flex-direction:row;padding:0;margin:0;border:0;flex:1;',
    '    justify-content:space-around}',
    '  .rl-item{flex-direction:column;gap:3px;justify-content:center;padding:7px 4px 6px;',
    '    border-left:0;border-top:2px solid transparent;flex:1}',
    '  .rl-item[aria-current]{border-left-color:transparent;border-top-color:var(--accent)}',
    '  .rl-item span{opacity:1;font-size:9px;letter-spacing:.02em}',
    '  .rl-foot{margin:0;padding:0 10px;flex-direction:row;align-items:center}',
    '  .rl-btn{width:auto;padding:6px 9px}',
    '  .rl-btn span{display:none}',
    '  body.has-rail,body.has-rail.rail-pinned{padding-left:0;padding-bottom:52px}',
    '}',
    '@media (prefers-reduced-motion:reduce){.siterail,.siterail *{transition:none}}'
  ].join('\n');

  function svg(name, cls) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"' + (cls ? ' class="' + cls + '"' : '') +
           ' fill="none" stroke="currentColor" stroke-width="1.6" ' +
           'stroke-linecap="round" stroke-linejoin="round">' + ICON[name] + '</svg>';
  }

  /* ---------------------------------------------------------------- theme */
  function readTheme() {
    try {
      // site-theme is the shared key; tracks-theme is what the map page used
      // before the rail existed, and is honoured once so nobody's choice is lost.
      return localStorage.getItem('site-theme') || localStorage.getItem('tracks-theme');
    } catch (e) { return null; }
  }

  function applyTheme(next) {
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('site-theme', next); } catch (e) { /* private window */ }
    var b = document.querySelector('.rl-theme');
    if (b) {
      b.innerHTML = '<b>' + (next === 'light' ? '◓' : '◒') + '</b><span>' +
                    (next === 'light' ? 'Dark' : 'Light') + '</span>';
      b.setAttribute('aria-label', 'Switch to ' + (next === 'light' ? 'dark' : 'light') + ' mode');
    }
    // Pages that draw with colour — the map tiles, the trend chart — listen for
    // this rather than the rail knowing anything about them.
    window.dispatchEvent(new CustomEvent('themechange', { detail: { theme: next } }));
  }

  /* ----------------------------------------------------------------- build */
  function build() {
    var current = document.body.dataset.page || '';

    var html = '<div class="rl-mark">' + svg('tracks') + '<span>UK RAIL OPEN DATA</span></div>';
    var open = false;
    ITEMS.forEach(function (it) {
      if (it.group) {
        if (open) html += '</div>';
        html += '<div class="rl-grp"><div class="rl-hd">' + it.group + '</div>';
        open = true;
        return;
      }
      html += '<a class="rl-item" href="' + it.href + '"' +
              (it.id === current ? ' aria-current="page"' : '') +
              (it.ext ? ' rel="noopener"' : '') + '>' +
              svg(it.icon) + '<span>' + it.name + '</span></a>';
    });
    if (open) html += '</div>';

    html += '<div class="rl-foot">' +
            '<button class="rl-btn rl-theme" type="button"></button>' +
            '<button class="rl-btn rl-pin" type="button" aria-pressed="false" ' +
            'aria-label="Keep the rail open"><b>⇥</b><span>Pin</span></button>' +
            '<div class="rl-note">Darwin feed<br>since Jan 2025</div></div>';

    var nav = document.createElement('nav');
    nav.className = 'siterail';
    nav.setAttribute('aria-label', 'Site');
    nav.innerHTML = html;
    document.body.appendChild(nav);
    document.body.classList.add('has-rail');

    var pinned = false;
    try { pinned = localStorage.getItem('rail-pinned') === '1'; } catch (e) { /* ignore */ }
    setPin(pinned);

    nav.querySelector('.rl-pin').addEventListener('click', function () {
      setPin(!nav.classList.contains('pin'));
    });
    nav.querySelector('.rl-theme').addEventListener('click', function () {
      applyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
    });

    function setPin(on) {
      nav.classList.toggle('pin', on);
      document.body.classList.toggle('rail-pinned', on);
      var b = nav.querySelector('.rl-pin');
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.innerHTML = '<b>' + (on ? '⇤' : '⇥') + '</b><span>' +
                    (on ? 'Unpin' : 'Pin') + '</span>';
      try { localStorage.setItem('rail-pinned', on ? '1' : '0'); } catch (e) { /* ignore */ }
      // Anything sized to the viewport has to be told the viewport moved.
      window.dispatchEvent(new Event('railresize'));
    }

    applyTheme(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
  }

  var style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);

  // The inline snippet in each page's <head> has already set data-theme, so
  // there is no flash to avoid here — only the markup is left to add.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else {
    build();
  }

  window.siteRail = { theme: readTheme };
})();
