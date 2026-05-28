// PantryAtlas marketing — progressive enhancement only.
// The page is fully readable with JS disabled; this only adds reveal-on-scroll.
// The hero "thinking" gradient motion is CSS-driven (see .hero__blob drift),
// so JS no longer touches transforms. prefers-reduced-motion handled in CSS.

(function () {
  "use strict";

  // Signal JS is active so CSS can hide reveal sections (no-JS users see everything).
  document.documentElement.classList.add("js");

  // ---- Reveal-on-scroll ----
  var reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && reveals.length) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    // No IO support: just show everything.
    reveals.forEach(function (el) { el.classList.add("is-visible"); });
  }
})();
