/* ESPRESSO DAILY — 前端筛选（动态标签多选 / 搜索 / 归档 / 状态持久化） */
(function () {
  "use strict";

  // 目录面板（归档目录 / 本期目录）：模板默认 open（桌面端常驻展开）；
  // 仅在确认窄屏（≤900px）时收起为标题行，用户可点击展开
  var navPanels = Array.prototype.slice.call(document.querySelectorAll("details.arch-nav, details.toc"));
  if (navPanels.length) {
    var navMedia = window.matchMedia("(max-width: 900px)");
    function syncNavPanels() {
      if (navMedia.matches) navPanels.forEach(function (d) { d.open = false; });
    }
    syncNavPanels();
    if (navMedia.addEventListener) navMedia.addEventListener("change", syncNavPanels);
    else if (navMedia.addListener) navMedia.addListener(syncNavPanels);
  }

  // —— 归档页专属：标题/日期搜索过滤 + 右侧目录滚动高亮 ——
  if (document.querySelector(".archive-list")) {
    var asearch = document.getElementById("search");
    var arc = document.getElementById("rc");
    var aempty = document.getElementById("empty");
    var aMonths = Array.prototype.slice.call(document.querySelectorAll(".arch-month"));
    var aRows = Array.prototype.slice.call(document.querySelectorAll(".arch-rows li"));
    var navMonths = Array.prototype.slice.call(document.querySelectorAll(".an-month"));

    function aApply() {
      var q = (asearch && asearch.value ? asearch.value : "").trim().toLowerCase();
      var visibleDays = 0;
      aRows.forEach(function (li) {
        var show = !q || li.textContent.toLowerCase().indexOf(q) !== -1;
        li.style.display = show ? "" : "none";
        if (show) visibleDays++;
      });
      var visibleMonths = 0;
      aMonths.forEach(function (m) {
        var has = Array.prototype.some.call(m.querySelectorAll(".arch-rows li"), function (li) {
          return li.style.display !== "none";
        });
        m.style.display = has ? "" : "none";
        if (has) visibleMonths++;
      });
      if (arc) arc.textContent = visibleDays;
      if (aempty) aempty.hidden = visibleDays !== 0;
    }
    if (asearch) asearch.addEventListener("input", aApply);

    if ("IntersectionObserver" in window && aMonths.length && navMonths.length) {
      var spy = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) {
            var label = en.target.getAttribute("data-month");
            navMonths.forEach(function (n) {
              n.classList.toggle("active", n.getAttribute("data-month") === label);
            });
          }
        });
      }, { rootMargin: "-110px 0px -72% 0px", threshold: 0 });
      aMonths.forEach(function (s) { spy.observe(s); });
    }
    return;
  }

  var chips = Array.prototype.slice.call(document.querySelectorAll("#tag-chips .chip"));
  var search = document.getElementById("search");
  var feed = document.getElementById("feed");
  var empty = document.getElementById("empty");
  var rc = document.getElementById("rc");
  var articles = feed ? Array.prototype.slice.call(feed.querySelectorAll(".entry")) : [];

  var selected = {}; // 选中的标签集合（多选，AND 逻辑）

  function activeTags() {
    return Object.keys(selected).filter(function (k) { return selected[k]; });
  }

  function apply() {
    var tags = activeTags();
    var q = (search && search.value ? search.value : "").trim().toLowerCase();
    var visible = 0;
    for (var i = 0; i < articles.length; i++) {
      var a = articles[i];
      var itemTags = (a.dataset.tags || "").split(",").map(function (s) { return s.trim(); });
      // 标签：选中的全部都要命中（AND，越选越窄）
      var okTags = tags.every(function (t) { return itemTags.indexOf(t) !== -1; });
      var okQ = !q || a.textContent.toLowerCase().indexOf(q) !== -1;
      var show = okTags && okQ;
      a.style.display = show ? "" : "none";
      if (show) visible++;
    }
    if (rc) rc.textContent = visible;
    if (empty) empty.hidden = visible !== 0;

    // 用 hash 持久化筛选状态，便于分享（无筛选时不改写 hash，以免清除锚点）
    var p = new URLSearchParams();
    if (tags.length) p.set("tags", tags.join(","));
    if (q) p.set("q", q);
    var hash = p.toString();
    if (hash) {
      history.replaceState(null, "", location.pathname + "#" + hash);
    }
  }

  chips.forEach(function (c) {
    c.addEventListener("click", function () {
      var t = c.dataset.tag;
      if (t === "__all__") {
        selected = {};
        chips.forEach(function (x) { x.classList.remove("active"); });
        c.classList.add("active");
      } else {
        // 取消“全部”
        var allChip = chips.filter(function (x) { return x.dataset.tag === "__all__"; })[0];
        if (allChip) allChip.classList.remove("active");
        if (selected[t]) { delete selected[t]; c.classList.remove("active"); }
        else { selected[t] = true; c.classList.add("active"); }
        if (activeTags().length === 0 && allChip) allChip.classList.add("active");
      }
      apply();
    });
  });
  if (search) search.addEventListener("input", apply);

  // 单日页：按评分排序（时间 = 初始 DOM 序，可切回；与搜索过滤互不干扰）
  var sortScore = document.getElementById("sort-score");
  var sortTime = document.getElementById("sort-time");
  if (sortScore && sortTime && feed) {
    var tocList = document.querySelector(".toc-list");
    var feedDefault = Array.prototype.slice.call(feed.querySelectorAll(".entry"));
    var tocDefault = tocList ? Array.prototype.slice.call(tocList.querySelectorAll(".toc-item")) : [];

    function setSort(scoreMode) {
      sortScore.classList.toggle("active", scoreMode);
      sortTime.classList.toggle("active", !scoreMode);
      sortScore.setAttribute("aria-pressed", scoreMode ? "true" : "false");
      sortTime.setAttribute("aria-pressed", scoreMode ? "false" : "true");
      if (scoreMode) {
        var sorted = Array.prototype.slice.call(feed.querySelectorAll(".entry")).sort(function (a, b) {
          return (parseInt(b.dataset.score, 10) || 0) - (parseInt(a.dataset.score, 10) || 0);
        });
        sorted.forEach(function (el) { feed.appendChild(el); });
        if (tocList) {
          var tsorted = Array.prototype.slice.call(tocList.querySelectorAll(".toc-item")).sort(function (a, b) {
            return (parseInt(b.dataset.score, 10) || 0) - (parseInt(a.dataset.score, 10) || 0);
          });
          tsorted.forEach(function (el) { tocList.appendChild(el); });
        }
      } else {
        feedDefault.forEach(function (el) { feed.appendChild(el); });
        if (tocList) tocDefault.forEach(function (el) { tocList.appendChild(el); });
      }
    }
    sortScore.addEventListener("click", function () { setSort(true); });
    sortTime.addEventListener("click", function () { setSort(false); });
  }

  // 归档手风琴
  Array.prototype.slice.call(document.querySelectorAll(".archive .acc")).forEach(function (b) {
    b.addEventListener("click", function () { b.parentElement.classList.toggle("open"); });
  });

  // 从 hash 恢复筛选
  function restore() {
    var h = location.hash.replace(/^#/, "");
    if (!h) return;
    var p = new URLSearchParams(h);
    var tags = p.get("tags");
    if (tags) {
      var allChip = chips.filter(function (x) { return x.dataset.tag === "__all__"; })[0];
      if (allChip) allChip.classList.remove("active");
      tags.split(",").forEach(function (t) {
        var chip = chips.filter(function (c) { return c.dataset.tag === t; })[0];
        if (chip) { selected[t] = true; chip.classList.add("active"); }
      });
    }
    var q = p.get("q");
    if (q && search) search.value = q;
    apply();
  }

  restore();
})();
