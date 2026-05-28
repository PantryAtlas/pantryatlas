// PantryAtlas marketing — progressive enhancement only.
// The page is fully readable with JS disabled; this adds reveal-on-scroll
// and a subtle hero gradient parallax. Both respect prefers-reduced-motion.

(function () {
  "use strict";

  // Signal JS is active so CSS can hide reveal sections (no-JS users see everything).
  document.documentElement.classList.add("js");

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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

  // ---- Hero gradient parallax (0.5x scroll) ----
  if (!reduceMotion) {
    var blob = document.querySelector(".hero__blob");
    if (blob) {
      var ticking = false;
      window.addEventListener("scroll", function () {
        if (!ticking) {
          window.requestAnimationFrame(function () {
            var y = window.scrollY * 0.5;
            blob.style.transform = "translateY(" + (-y) + "px)";
            ticking = false;
          });
          ticking = true;
        }
      }, { passive: true });
    }
  }
})();
