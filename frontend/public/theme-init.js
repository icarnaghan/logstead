// Apply the persisted (or system) theme before paint to avoid a flash.
// Kept as a static same-origin file (not inline) so the CSP can use script-src 'self'.
(function () {
  try {
    var pref = localStorage.getItem("logstead.theme");
    var dark =
      pref === "dark" ||
      (pref !== "light" &&
        window.matchMedia &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    if (dark) document.documentElement.classList.add("dark");
  } catch {
    // Storage or matchMedia unavailable: fall back to the default (light) theme.
  }
})();
