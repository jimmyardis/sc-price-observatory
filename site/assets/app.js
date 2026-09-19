/* South Carolina Price Observatory — site behaviour.
   No dependencies, no build step. The site reads published snapshots only. */

export const SNAP = {
  measured: "snapshots/latest.json",
  regional: "snapshots/regional_latest.json",
  manifest: "snapshots/manifest.json",
  counties: "data/sc-counties.geojson",
};

export async function loadJSON(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

export function fail(el, err) {
  if (!el) return;
  el.innerHTML = `<p class="err">Could not load the published data (${String(err.message || err)}).
    Everything this page shows comes from the snapshot files, so nothing is rendered from memory.</p>`;
}

/* --- formatting ---------------------------------------------------------- */

export const fmt = {
  hours: (v) => (v == null ? "—" : v.toFixed(2).replace(/\.?0+$/, "") + " h"),
  hours1: (v) => (v == null ? "—" : v.toFixed(1)),
  usd: (v) => (v == null ? "—" : "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })),
  usd0: (v) => (v == null ? "—" : "$" + Math.round(v).toLocaleString("en-US")),
  num: (v, d = 2) => (v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })),
  pct: (v, d = 1) => (v == null ? "—" : (v > 0 ? "+" : "") + v.toFixed(d) + "%"),
  month: (ym) => {
    const [y, m] = ym.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
  },
  monthShort: (ym) => {
    const [y, m] = ym.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });
  },
  date: (iso) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" }),
};

/* --- chrome -------------------------------------------------------------- */

export function initChrome() {
  const saved = localStorage.getItem("theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  const btn = document.querySelector("button.theme");
  if (btn) {
    const label = () => {
      const dark = document.documentElement.getAttribute("data-theme") === "dark" ||
        (!document.documentElement.getAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
      btn.textContent = dark ? "Light" : "Dark";
      btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    };
    label();
    btn.addEventListener("click", () => {
      const dark = document.documentElement.getAttribute("data-theme") === "dark" ||
        (!document.documentElement.getAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
      const next = dark ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("theme", next);
      label();
      document.dispatchEvent(new CustomEvent("themechange"));
    });
  }
  const here = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll("nav.site a").forEach((a) => {
    if (a.getAttribute("href") === here) a.setAttribute("aria-current", "page");
  });
}

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/* --- tooltip ------------------------------------------------------------- */

function tooltipFor(holder) {
  let t = holder.querySelector(".tooltip");
  if (!t) {
    t = document.createElement("div");
    t.className = "tooltip";
    t.setAttribute("role", "status");
    holder.appendChild(t);
  }
  return {
    show(html, x, y) {
      t.innerHTML = html;
      t.style.opacity = "1";
      const box = holder.getBoundingClientRect();
      const w = t.offsetWidth, h = t.offsetHeight;
      t.style.left = Math.max(4, Math.min(x + 14, box.width - w - 4)) + "px";
      t.style.top = Math.max(4, y - h - 12) + "px";
    },
    hide() { t.style.opacity = "0"; },
  };
}

/* --- table view ---------------------------------------------------------- */

export function tableView({ columns, rows, caption }) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const cls = (c) => [c.num ? "num" : "", c.cls || ""].filter(Boolean).join(" ");
  const head = columns.map((c) => `<th scope="col"${cls(c) ? ` class="${cls(c)}"` : ""}>${c.label}</th>`).join("");
  const body = rows.map((r) => "<tr>" + columns.map((c) => `<td${cls(c) ? ` class="${cls(c)}"` : ""}>${c.get(r)}</td>`).join("") + "</tr>").join("");
  wrap.innerHTML = `<table>${caption ? `<caption>${caption}</caption>` : ""}<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  return wrap;
}

export function attachTableToggle(button, figure, buildTable) {
  let node = null;
  button.addEventListener("click", () => {
    const on = button.getAttribute("aria-pressed") === "true";
    if (on) {
      node?.remove();
      node = null;
      figure.querySelector(".chart-holder").classList.remove("hidden");
      button.setAttribute("aria-pressed", "false");
      button.textContent = "Table";
    } else {
      node = buildTable();
      figure.querySelector(".chart-holder").classList.add("hidden");
      figure.querySelector(".chart-holder").after(node);
      button.setAttribute("aria-pressed", "true");
      button.textContent = "Chart";
    }
  });
}

/* --- line chart ---------------------------------------------------------- */
/* series: [{ id, label, color, dashed, points: [{x: "YYYY-MM", y: Number|null}] }] */

export function lineChart(holder, { series, yFormat = fmt.num, yTitle = "", labelLast = true }) {
  const draw = () => {
    holder.querySelectorAll("svg").forEach((s) => s.remove());
    const W = 860, H = 300, M = { t: 14, r: 62, b: 28, l: 46 };
    const months = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort();
    const xi = new Map(months.map((m, i) => [m, i]));
    const ys = series.flatMap((s) => s.points.map((p) => p.y)).filter((v) => v != null);
    if (!months.length || !ys.length) return;
    let lo = Math.min(...ys), hi = Math.max(...ys);
    const pad = (hi - lo) * 0.12 || 1;
    lo = Math.max(0, lo - pad); hi = hi + pad;
    const X = (m) => M.l + (xi.get(m) / Math.max(1, months.length - 1)) * (W - M.l - M.r);
    const Y = (v) => H - M.b - ((v - lo) / (hi - lo)) * (H - M.t - M.b);

    const ticks = niceTicks(lo, hi, 5);
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${yTitle}. ${series.map((s) => s.label).join(" and ")}, ${fmt.month(months[0])} to ${fmt.month(months.at(-1))}. A table of the same numbers is available with the Table button.`);
    const el = (n, attrs, parent = svg) => {
      const e = document.createElementNS(svgNS, n);
      for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
      parent.appendChild(e);
      return e;
    };

    const grid = el("g", { class: "grid" });
    ticks.forEach((t) => {
      el("line", { x1: M.l, x2: W - M.r, y1: Y(t), y2: Y(t) }, grid);
      el("text", { x: M.l - 8, y: Y(t) + 4, "text-anchor": "end" }, svg).textContent = yFormat(t);
    });
    el("line", { class: "axis-line", x1: M.l, x2: W - M.r, y1: H - M.b, y2: H - M.b });

    const yearFirst = new Map();
    months.forEach((m) => { const y = m.slice(0, 4); if (!yearFirst.has(y)) yearFirst.set(y, m); });
    const years = [...yearFirst.keys()];
    const step = Math.ceil(years.length / 9);
    years.forEach((y, i) => {
      if (i % step) return;
      el("text", { x: X(yearFirst.get(y)), y: H - M.b + 18, "text-anchor": "middle" }, svg).textContent = y;
    });

    for (const s of series) {
      const color = css(s.color) || s.color;
      let run = [];
      const flush = () => {
        if (run.length > 1) {
          el("path", { class: "series-line", stroke: color, d: run.map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join(" ") });
        } else if (run.length === 1) {
          el("circle", { cx: X(run[0].x), cy: Y(run[0].y), r: 2.5, fill: color });
        }
        run = [];
      };
      for (const p of s.points) { if (p.y == null) flush(); else run.push(p); }
      flush();
      const last = [...s.points].reverse().find((p) => p.y != null);
      if (last) {
        el("circle", { class: "end-dot", cx: X(last.x), cy: Y(last.y), r: 4.5, fill: color });
        if (labelLast) {
          el("text", { x: X(last.x) + 9, y: Y(last.y) + 4, "text-anchor": "start" }, svg).textContent = yFormat(last.y);
        }
      }
    }

    const hover = el("g", { opacity: "0" });
    const vline = el("line", { y1: M.t, y2: H - M.b, stroke: css("--border-strong"), "stroke-width": "1" }, hover);
    const dots = series.map((s) => el("circle", { r: 4.5, fill: css(s.color) || s.color, class: "end-dot" }, hover));
    const tip = tooltipFor(holder);
    const hit = el("rect", { x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b, fill: "transparent" });

    const move = (evt) => {
      const pt = svg.getBoundingClientRect();
      const px = ((evt.touches ? evt.touches[0].clientX : evt.clientX) - pt.left) / pt.width * W;
      const idx = Math.round(((px - M.l) / (W - M.l - M.r)) * (months.length - 1));
      const m = months[Math.max(0, Math.min(months.length - 1, idx))];
      if (!m) return;
      hover.setAttribute("opacity", "1");
      vline.setAttribute("x1", X(m)); vline.setAttribute("x2", X(m));
      const rows = series.map((s, i) => {
        const p = s.points.find((q) => q.x === m);
        const d = dots[i];
        if (p && p.y != null) { d.setAttribute("cx", X(m)); d.setAttribute("cy", Y(p.y)); d.setAttribute("opacity", "1"); }
        else d.setAttribute("opacity", "0");
        return `<div class="t-row"><span>${s.label}</span><b>${p && p.y != null ? yFormat(p.y) : "no data"}</b></div>`;
      }).join("");
      const box = holder.getBoundingClientRect();
      tip.show(`<b>${fmt.month(m)}</b>${rows}`,
        (X(m) / W) * box.width, ((evt.touches ? evt.touches[0].clientY : evt.clientY) - box.top));
    };
    hit.addEventListener("mousemove", move);
    hit.addEventListener("touchmove", (e) => { move(e); e.preventDefault(); }, { passive: false });
    hit.addEventListener("mouseleave", () => { hover.setAttribute("opacity", "0"); tip.hide(); });
    holder.appendChild(svg);
  };
  draw();
  document.addEventListener("themechange", draw);
  return { redraw: draw };
}

function niceTicks(lo, hi, count) {
  const span = hi - lo;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || mag * 10;
  const out = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(Number(t.toFixed(6)));
  return out;
}

/* --- choropleth ---------------------------------------------------------- */
/* values: Map(fips -> {value, label, extra}) ; ramp: light -> dark = more hours */

export function choropleth(holder, { geo, values, onSelect, selected, rings = new Set(), unit = "hours" }) {
  const bins = quantiles([...values.values()].map((v) => v.value).filter((v) => v != null), 7);
  const ramp = ["--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5", "--seq-6", "--seq-7"];
  const colorFor = (v) => (v == null ? "transparent" : ramp[Math.min(bins.findIndex((b) => v <= b) === -1 ? ramp.length - 1 : bins.findIndex((b) => v <= b), ramp.length - 1)]);

  const draw = () => {
    holder.querySelectorAll("svg").forEach((s) => s.remove());
    const W = 860, H = 430, pad = 10;
    const lons = [], lats = [];
    for (const f of geo.features) eachRing(f.geometry, (ring) => ring.forEach(([x, y]) => { lons.push(x); lats.push(y); }));
    const lon0 = Math.min(...lons), lon1 = Math.max(...lons), lat0 = Math.min(...lats), lat1 = Math.max(...lats);
    const k = Math.cos(((lat0 + lat1) / 2) * Math.PI / 180);
    const sx = (W - pad * 2) / ((lon1 - lon0) * k), sy = (H - pad * 2) / (lat1 - lat0);
    const s = Math.min(sx, sy);
    const offX = pad + ((W - pad * 2) - (lon1 - lon0) * k * s) / 2;
    const offY = pad + ((H - pad * 2) - (lat1 - lat0) * s) / 2;
    const P = ([lon, lat]) => [offX + (lon - lon0) * k * s, offY + (lat1 - lat) * s];

    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Map of South Carolina counties shaded by ${unit}. The same numbers are in the county table below.`);
    const tip = tooltipFor(holder);

    for (const f of geo.features) {
      const v = values.get(f.id);
      const d = [];
      eachRing(f.geometry, (ring) => {
        d.push(ring.map((c, i) => `${i ? "L" : "M"}${P(c).map((n) => n.toFixed(1)).join(",")}`).join(" ") + "Z");
      });
      const path = document.createElementNS(svgNS, "path");
      path.setAttribute("d", d.join(" "));
      path.setAttribute("class", "county");
      path.setAttribute("fill", v && v.value != null ? `var(${colorFor(v.value)})` : "var(--surface-2)");
      path.setAttribute("tabindex", "0");
      path.setAttribute("role", "button");
      path.setAttribute("aria-pressed", String(f.id === selected));
      path.setAttribute("aria-label", `${f.properties.name} County: ${v && v.value != null ? v.label : "no data"}`);
      const show = (evt) => {
        const box = holder.getBoundingClientRect();
        const r = path.getBoundingClientRect();
        tip.show(`<b>${f.properties.name} County</b>
          <div class="t-row"><span>${unit}</span><b>${v && v.value != null ? v.label : "no data"}</b></div>
          ${v && v.extra ? `<div class="small muted">${v.extra}</div>` : ""}`,
          (evt.clientX ?? r.left + r.width / 2) - box.left, (evt.clientY ?? r.top) - box.top);
      };
      path.addEventListener("mousemove", show);
      path.addEventListener("mouseleave", () => tip.hide());
      path.addEventListener("focus", show);
      path.addEventListener("blur", () => tip.hide());
      path.addEventListener("click", () => onSelect && onSelect(f.id));
      path.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect && onSelect(f.id); } });
      svg.appendChild(path);

      if (rings.has(f.id)) {
        let n = 0, cx = 0, cy = 0;
        eachRing(f.geometry, (ring) => ring.forEach((c) => { const [x, y] = P(c); cx += x; cy += y; n++; }));
        const ring = document.createElementNS(svgNS, "circle");
        ring.setAttribute("class", "measured-ring");
        ring.setAttribute("cx", (cx / n).toFixed(1));
        ring.setAttribute("cy", (cy / n).toFixed(1));
        ring.setAttribute("r", "9");
        svg.appendChild(ring);
      }
    }
    holder.appendChild(svg);
  };
  draw();
  document.addEventListener("themechange", draw);
  return { bins, redraw: draw };
}

function eachRing(geometry, fn) {
  const polys = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  polys.forEach((poly) => poly.forEach((ring) => fn(ring)));
}

function quantiles(vals, n) {
  const s = [...vals].sort((a, b) => a - b);
  return Array.from({ length: n }, (_, i) => s[Math.min(s.length - 1, Math.floor(((i + 1) / n) * s.length) - 1)]);
}

export function rampLegend(el, bins, format) {
  el.innerHTML = `<span>${format(bins[0])}</span>
    <span class="ramp">${["--seq-1","--seq-2","--seq-3","--seq-4","--seq-5","--seq-6","--seq-7"]
      .map((c) => `<i style="background:var(${c})"></i>`).join("")}</span>
    <span>${format(bins.at(-1))}</span>`;
}
