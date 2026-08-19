(function () {
  "use strict";

  const root = document.documentElement;
  const body = document.body;
  const PREFS_KEY = "stone-weaver-preferences";
  const THEMES = ["zhu", "bamboo", "begonia", "night"];
  const FONT_MIN = 17;
  const FONT_MAX = 27;
  const FONT_DEFAULT = 21;
  const MOBILE = window.matchMedia("(max-width: 880px)");

  let fontSize = FONT_DEFAULT;
  const savedSize = parseFloat(root.style.getPropertyValue("--reader-size"));
  if (Number.isFinite(savedSize)) fontSize = savedSize;

  const toolbar = document.getElementById("reader-toolbar");
  const progressBar = document.getElementById("progress-bar");
  const fontValue = document.getElementById("font-size-value");
  const fontSmaller = document.getElementById("font-smaller");
  const fontLarger = document.getElementById("font-larger");
  const themeToggle = document.getElementById("theme-toggle");
  const themePopover = document.getElementById("theme-popover");
  const tocToggle = document.getElementById("toc-toggle");
  const tocClose = document.getElementById("toc-close");
  const backdrop = document.getElementById("drawer-backdrop");
  const chapterJump = document.getElementById("chapter-jump");
  const mobileCurrent = document.getElementById("mobile-current");

  function savePrefs() {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({
        theme: root.dataset.theme,
        fontSize: fontSize,
      }));
    } catch (_) {}
  }

  function setFontSize(next, announce) {
    fontSize = Math.max(FONT_MIN, Math.min(FONT_MAX, next));
    root.style.setProperty("--reader-size", fontSize + "px");
    if (fontValue) fontValue.textContent = String(fontSize);
    if (fontSmaller) fontSmaller.disabled = fontSize <= FONT_MIN;
    if (fontLarger) fontLarger.disabled = fontSize >= FONT_MAX;
    savePrefs();
  }

  function setTheme(theme) {
    root.dataset.theme = theme;
    document.querySelectorAll(".theme-option").forEach(function (opt) {
      opt.setAttribute("aria-checked", String(opt.dataset.themeValue === theme));
    });
    if (themeToggle) themeToggle.setAttribute("aria-expanded", "false");
    savePrefs();
  }

  function setToc(open) {
    if (MOBILE.matches) {
      body.classList.toggle("toc-open", open);
      if (backdrop) backdrop.hidden = !open;
    } else {
      body.classList.toggle("toc-collapsed", !open);
    }
  }

  /* 工具栏滚动静隐 + 阅读进度 */
  let lastY = window.scrollY;
  let ticking = false;

  function updateScrollChrome() {
    const y = window.scrollY;
    if (toolbar) {
      if (y <= 16) toolbar.classList.remove("is-hidden");
      else if (y > lastY + 24) toolbar.classList.add("is-hidden");
      else if (y < lastY - 24) toolbar.classList.remove("is-hidden");
    }
    const doc = document.documentElement;
    const max = doc.scrollHeight - window.innerHeight;
    const ratio = max > 0 ? y / max : 0;
    if (progressBar) progressBar.style.width = ratio * 100 + "%";
    lastY = y;
    ticking = false;
  }

  window.addEventListener("scroll", function () {
    if (!ticking) {
      ticking = true;
      window.requestAnimationFrame(updateScrollChrome);
    }
  }, { passive: true });
  updateScrollChrome();

  /* 事件 */
  if (tocToggle) tocToggle.addEventListener("click", function () {
    const isOpen = MOBILE.matches
      ? body.classList.contains("toc-open")
      : !body.classList.contains("toc-collapsed");
    setToc(!isOpen);
  });
  if (tocClose) tocClose.addEventListener("click", function () { setToc(false); });
  if (backdrop) backdrop.addEventListener("click", function () { setToc(false); });
  if (chapterJump) chapterJump.addEventListener("click", function () { setToc(true); });
  if (mobileCurrent) mobileCurrent.addEventListener("click", function () { setToc(true); });

  if (fontSmaller) fontSmaller.addEventListener("click", function () { setFontSize(fontSize - 1); });
  if (fontLarger) fontLarger.addEventListener("click", function () { setFontSize(fontSize + 1); });

  if (themeToggle) themeToggle.addEventListener("click", function (e) {
    const open = themePopover && themePopover.classList.contains("is-open");
    if (themePopover) themePopover.classList.toggle("is-open", !open);
    themeToggle.setAttribute("aria-expanded", String(!open));
    e.stopPropagation();
  });

  document.querySelectorAll(".theme-option").forEach(function (opt) {
    opt.addEventListener("click", function () { setTheme(opt.dataset.themeValue); });
  });

  document.addEventListener("click", function (e) {
    if (themePopover && themePopover.classList.contains("is-open")
        && !themePopover.contains(e.target) && e.target !== themeToggle) {
      themePopover.classList.remove("is-open");
      if (themeToggle) themeToggle.setAttribute("aria-expanded", "false");
    }
  });

  /* 键盘翻回 */
  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
    if (e.target.matches("input, textarea, select, [contenteditable='true']")) return;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      const cur = Number(body.dataset.current);
      const total = Number(body.dataset.total);
      const target = e.key === "ArrowLeft" ? cur - 1 : cur + 1;
      if (target >= 1 && target <= total) location.href = "/chapter/" + target;
    } else if (e.key === "Escape") {
      setToc(false);
      if (themePopover) themePopover.classList.remove("is-open");
    }
  });

  /* 初始化 */
  setFontSize(fontSize, false);
  const savedTheme = (function () {
    try { return JSON.parse(localStorage.getItem(PREFS_KEY) || "{}").theme; } catch (_) { return null; }
  })();
  if (savedTheme && THEMES.indexOf(savedTheme) >= 0) setTheme(savedTheme);
  else setTheme(root.dataset.theme);
})();
