/**
 * artifact-security-harness.js — replicación del mecanismo de shell.js para
 * verificar que un artefacto HTML/hostil NO pueda escapar de su iframe
 * sandbox="allow-scripts" (sin allow-same-origin) cargando
 * artifact-frame.html (CSP propia con connect-src 'none').
 *
 * El artefacto hostil intenta: leer window.parent/.top (document y window
 * .hermis del overlay), fetch externo, window.open y navegar el padre.
 * Reporta cada intento por postMessage; el main de Electron decide PASS/FAIL
 * (incluida la URL del top, que no puede cambiar).
 */
'use strict';

(function () {
  var pending = 0;
  var results = {};

  // HTML hostil: igual forma en la que shell.js le pasa contenido al frame.
  var HOSTILE_HTML = [
    '<!doctype html><html><head><title>pwn</title></head><body><script>',
    "(function () {",
    "  var results = {};",
    "  function report(name, escaped, detail) { results[name] = { escaped: !!escaped, detail: String(detail).slice(0, 120) }; }",
    "  try { var d = window.parent.document; report('parent_document', false, 'LEIDO'); }",
    "  catch (e) { report('parent_document', true, e.name); }",
    "  try { var h = window.parent.hermis; report('parent_hermis', h === undefined, typeof h); }",
    "  catch (e) { report('parent_hermis', true, e.name); }",
    "  try { var t = window.top.document; report('top_document', false, 'LEIDO'); }",
    "  catch (e) { report('top_document', true, e.name); }",
    "  fetch('https://example.com/pwn', { mode: 'no-cors' }).then(",
    "    function () { report('fetch_external', false, 'RESPONDIO'); finish(); },",
    "    function (e) { report('fetch_external', true, e.name); finish(); });",
    "  try { var w = window.open('https://example.com'); report('window_open', !w, w ? 'ABRIO' : 'null'); }",
    "  catch (e) { report('window_open', true, e.name); }",
    "  try { window.top.location.href = 'https://example.com/pwn'; report('top_navigation', true, 'setter no lanzó; el main verifica la URL'); }",
    "  catch (e) { report('top_navigation', true, e.name); }",
    "  try { window.parent.location.href = 'https://example.com/pwn2'; report('parent_navigation', true, 'setter no lanzó; el main verifica la URL'); }",
    "  catch (e) { report('parent_navigation', true, e.name); }",
    "  var done = false;",
    "  function finish() {",
    "    if (done) return;",
    "    done = true;",
    "    window.parent.postMessage({ type: 'artifact-security-report', results: results }, '*');",
    "  }",
    "  setTimeout(finish, 1500);",
    "}());",
    '<\/script></body></html>',
  ].join('\n');

  window.addEventListener('message', function (e) {
    var d = e.data;
    if (!d || d.type !== 'artifact-security-report') return;
    results = d.results || {};
    // La navegación del padre no lanza: la verifica el main con la URL real.
    results.parent_navigation.verdict = 'main';
    finish();
  });

  function finish() {
    clearTimeout(guard);
    console.log('HERMIS_ARTIFACT_SECURITY_RESULT:' + JSON.stringify(results));
  }

  var guard = setTimeout(finish, 8000);

  var frame = document.createElement('iframe');
  frame.setAttribute('sandbox', 'allow-scripts');
  frame.style.cssText = 'width:800px;height:600px;border:0';
  frame.addEventListener('load', function () {
    frame.contentWindow.postMessage({ type: 'hermis-artifact', kind: 'html', content: HOSTILE_HTML }, '*');
  });
  frame.src = '../renderer/artifact-frame.html';
  document.body.appendChild(frame);
}());
