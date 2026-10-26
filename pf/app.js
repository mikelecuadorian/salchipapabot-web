/* ============================================================
   Portafolio · interacción mínima y deliberada
   - Aparición al hacer scroll (respeta prefers-reduced-motion)
   - Detección real de dispositivo para ajustar densidad y tipografía
   - Sin dependencias, sin rastreo, sin CDN externo
   ============================================================ */
(function () {
  'use strict';

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- 1. Aparición al hacer scroll ---------- */
  var items = document.querySelectorAll('.reveal');
  if (!reduce && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add('in');
          io.unobserve(e.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.06 });
    items.forEach(function (el) { io.observe(el); });
  } else {
    items.forEach(function (el) { el.classList.add('in'); });
  }

  /* ---------- 2. Detección de dispositivo ----------
     No se usa user-agent sniffing: se mira el ancho real del viewport
     y la capacidad de puntero fino. La clase en <html> permite ajustar
     densidad de información, no contenido. */
  var root = document.documentElement;

  function classify() {
    var w = window.innerWidth;
    var fine = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    var cls = w < 560 ? 'is-phone'
            : w < 900 ? 'is-tablet'
            : 'is-desktop';
    root.classList.remove('is-phone', 'is-tablet', 'is-desktop');
    root.classList.add(cls);
    root.classList.toggle('has-pointer', fine);
    /* Alto real de la barra del navegador móvil, para no cortar el hero */
    root.style.setProperty('--vh', (window.innerHeight * 0.01) + 'px');
  }

  classify();
  var t;
  window.addEventListener('resize', function () {
    clearTimeout(t);
    t = setTimeout(classify, 120);
  }, { passive: true });
  window.addEventListener('orientationchange', function () {
    setTimeout(classify, 250);
  }, { passive: true });

  /* ---------- 3. Marcar el enlace activo de la barra ---------- */
  var links = Array.prototype.slice.call(document.querySelectorAll('.topbar nav a'));
  var secs = links.map(function (a) {
    return document.querySelector(a.getAttribute('href'));
  }).filter(Boolean);

  if ('IntersectionObserver' in window && secs.length) {
    var navIo = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        links.forEach(function (a) {
          var on = a.getAttribute('href') === '#' + e.target.id;
          a.style.color = on ? 'var(--txt)' : '';
          a.style.background = on ? 'rgba(255,255,255,.06)' : '';
        });
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    secs.forEach(function (s) { navIo.observe(s); });
  }
})();
