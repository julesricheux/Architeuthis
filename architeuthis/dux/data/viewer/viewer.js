/*
 * Architeuthis share viewer.
 *
 * Draws the scene embedded in the page (routes, forecast frames, exclusion
 * zones, land) on a MapLibre globe, with a layers panel, a timeline and
 * tooltips. Nothing is fetched except optional online map tiles, so the
 * page works offline. ui.py previews the same page in a frame and sends the
 * analyst's selection with postMessage ("architeuthis:settings"); in that
 * preview the analyst comments points of the routes, sent back to ui.py
 * ("architeuthis:comments").
 */
(function () {
  "use strict";

  const scene = JSON.parse(document.getElementById("architeuthis-scene").textContent);
  const $ = (id) => document.getElementById(id);

  const NO_DATA = 255;
  const MERCATOR_LIMIT = 85.05;
  const HOUR = 3600;
  const DAY = 86400;
  const STORAGE_KEY = "architeuthis-viewer:" + (scene.title || "");
  const EMPTY = { type: "FeatureCollection", features: [] };
  const BEARINGS = new Set(["cog", "ctw", "twd", "mwd", "cd"]);
  // Arrows drawn over a layer, and the quantities they need.
  const ARROW_QUANTITIES = { wind: ["wind_u", "wind_v"], waves: ["swh", "wave_x", "wave_y"], current: ["current_u", "current_v"] };
  const ARROW_LABELS = { wind: "Wind barbs", waves: "Waves", current: "Current" };
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  // Arrows and barbs are about this far apart on screen, in CSS pixels:
  // wave glyphs, longer in high seas, a little further.
  const ARROW_SPACING = { wind: 38, waves: 48, current: 40 };
  const MAX_ARROWS = 2500;
  // Valid time of a chart, in the window the timeline covers around it.
  const OVERLAY_MARGIN = 6 * HOUR;

  // Map colours of each theme. Arrows and barbs take the colour of the field
  // under them, made vivid with the lightness of the theme.
  const THEMES = {
    dark: {
      sea: "#26292d",
      land: "#3c4045",
      coast: "#000000",
      coastShade: 0.11,
      graticule: "rgba(255,255,255,0.10)",
      isobar: "#f2f4f6",
      glyphLightness: 0.64,
    },
    light: {
      sea: "#c9ced3",
      land: "#f7f7f5",
      coast: "#000000",
      coastShade: 0.06,
      graticule: "rgba(0,0,0,0.13)",
      isobar: "#1c2024",
      glyphLightness: 0.36,
    },
  };

  // The coastline: a sharp line, shaded on the sea side by lines of growing
  // width offset towards the sea, which overlap most along the coast. Each
  // entry is a layer id and its width at zoom 5, in pixels.
  const COAST_SHADES = 8;
  const COAST_SHADE_WIDTH = 10;
  const COAST_LAYERS = Array.from({ length: COAST_SHADES }, (_, i) => [`coast-shade-${i + 1}`, (COAST_SHADE_WIDTH * (i + 1)) / COAST_SHADES])
    .concat([["coast", 1.2]]);

  const ICONS = {
    layers: "M12 2 2 7l10 5 10-5-10-5zm-7.8 9.1L2 12.2l10 5 10-5-2.2-1.1L12 15l-7.8-3.9zm0 5L2 17.2l10 5 10-5-2.2-1.1L12 20l-7.8-3.9z",
    play: "M8 5v14l11-7z",
    pause: "M6 5h4v14H6zm8 0h4v14h-4z",
    prev: "M6 6h2v12H6zm3.5 6 8.5 6V6z",
    next: "M16 6h2v12h-2zM6 18l8.5-6L6 6z",
    picker: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm8.94 3A9 9 0 0 0 13 3.06V1h-2v2.06A9 9 0 0 0 3.06 11H1v2h2.06A9 9 0 0 0 11 20.94V23h2v-2.06A9 9 0 0 0 20.94 13H23v-2h-2.06zM12 19a7 7 0 1 1 0-14 7 7 0 0 1 0 14z",
    sun: "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM2 13h2a1 1 0 0 0 0-2H2a1 1 0 0 0 0 2zm18 0h2a1 1 0 0 0 0-2h-2a1 1 0 0 0 0 2zM11 2v2a1 1 0 0 0 2 0V2a1 1 0 0 0-2 0zm0 18v2a1 1 0 0 0 2 0v-2a1 1 0 0 0-2 0zM5.99 4.58a1 1 0 0 0-1.41 1.41l1.06 1.06a1 1 0 0 0 1.41-1.41L5.99 4.58zm12.37 12.37a1 1 0 0 0-1.41 1.41l1.06 1.06a1 1 0 0 0 1.41-1.41l-1.06-1.06zm1.06-10.96a1 1 0 0 0-1.41-1.41l-1.06 1.06a1 1 0 0 0 1.41 1.41l1.06-1.06zM7.05 18.36a1 1 0 0 0-1.41-1.41l-1.06 1.06a1 1 0 0 0 1.41 1.41l1.06-1.06z",
    moon: "M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a5.39 5.39 0 0 1-4.4 2.26 5.4 5.4 0 0 1-3.14-9.8c-.44-.06-.9-.1-1.36-.1z",
    close: "M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
  };

  // --------------------------------------------------------------------
  // State
  // --------------------------------------------------------------------

  const stored = restore();
  const state = {
    t: 0,
    t0: 0,
    t1: 1,
    playing: false,
    speed: 3,
    source: null,
    layer: null,
    // The arrows drawn: those of the layer when null, else "wind", "waves",
    // "current" or "" for none.
    arrowKind: null,
    isobars: true,
    isobarLabels: true,
    opacity: 0.75,
    basemap: "offline",
    seamarks: false,
    graticule: true,
    hidden: {},
    zones: {},
    overlays: {},
    panelOpen: window.innerWidth > 720,
    noteOpen: true,
    settings: Object.assign({ routes: null, sources: null, overlays: null, hover: null, fields: null }, scene.settings || {}),
    theme: (scene.settings && scene.settings.theme) === "light" ? "light" : "dark",
    title: scene.title,
    note: scene.note || "",
    // The analyst's names, descriptions and comments, which replace those of
    // the scene once ui.py sends them: {route id: text} for the first two and
    // {route id: {segment: text}}.
    labels: {},
    descriptions: {},
    comments: {},
    editable: false,
    editing: null,
    picker: null,
    pointer: null,
    popup: null,
    ready: false,
  };
  scene.zones.forEach((zone) => { state.zones[zone.id] = zone.visible; });
  scene.overlays.forEach((overlay) => { state.overlays[overlay.id] = overlay.visible; });
  if (stored) {
    ["speed", "source", "layer", "arrowKind", "isobars", "isobarLabels", "opacity", "basemap", "seamarks", "graticule", "panelOpen", "noteOpen", "theme", "picker"]
      .forEach((key) => { if (key in stored) state[key] = stored[key]; });
    ["hidden", "zones", "overlays"].forEach((key) => { Object.assign(state[key], stored[key] || {}); });
  }

  function restore() {
    try {
      const text = window.sessionStorage.getItem(STORAGE_KEY);
      return text ? JSON.parse(text) : null;
    } catch (error) {
      return null;
    }
  }

  let saveTimer = null;
  function persist() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      try {
        const view = map ? { center: map.getCenter().toArray(), zoom: map.getZoom(), bearing: map.getBearing() } : null;
        const keep = {
          t: state.t, view, speed: state.speed, source: state.source, layer: state.layer, arrowKind: state.arrowKind,
          isobars: state.isobars, isobarLabels: state.isobarLabels, opacity: state.opacity, basemap: state.basemap,
          seamarks: state.seamarks, graticule: state.graticule, hidden: state.hidden, zones: state.zones,
          overlays: state.overlays, panelOpen: state.panelOpen, noteOpen: state.noteOpen, theme: state.theme,
          picker: state.picker,
        };
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(keep));
      } catch (error) {
        // Storage may be refused (private window, local file): the view is simply not kept.
      }
    }, 300);
  }

  // --------------------------------------------------------------------
  // Formatting
  // --------------------------------------------------------------------

  function pad(value, width) { return String(value).padStart(width || 2, "0"); }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  function formatTime(t) {
    const d = new Date(t * 1000);
    return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
  }

  function formatShort(t) {
    const d = new Date(t * 1000);
    return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  }

  function formatDate(t) {
    const d = new Date(t * 1000);
    return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
  }

  function formatRelative(t) {
    const delta = t - Date.now() / 1000;
    const hours = Math.round(Math.abs(delta) / HOUR);
    if (hours === 0) return "now";
    const text = hours < 48 ? `${hours} h` : `${Math.floor(hours / 24)} d ${hours % 24} h`;
    return delta > 0 ? `in ${text}` : `${text} ago`;
  }

  function formatCoordinate(value, positive, negative, width) {
    const hemisphere = value >= 0 ? positive : negative;
    const absolute = Math.abs(value);
    let degrees = Math.floor(absolute);
    let minutes = Math.round((absolute - degrees) * 600) / 10;
    if (minutes >= 60) { degrees += 1; minutes = 0; }
    return `${pad(degrees, width)}°${minutes.toFixed(1).padStart(4, "0")}′${hemisphere}`;
  }

  function formatPosition(lat, lon) {
    const wrapped = ((lon + 540) % 360) - 180;
    return `${formatCoordinate(lat, "N", "S", 2)} ${formatCoordinate(wrapped, "E", "W", 3)}`;
  }

  function formatBearing(degrees) {
    return `${pad(Math.round(((degrees % 360) + 360) % 360) % 360, 3)}°`;
  }

  function formatValue(name, value) {
    const meta = scene.variables[name] || { unit: "", digits: 2 };
    if (value === null || value === undefined || Number.isNaN(value)) return "–";
    if (BEARINGS.has(name)) return formatBearing(value);
    if (meta.unit === "°") return `${Math.round(value)}°`;
    return `${value.toFixed(meta.digits)}${meta.unit ? " " + meta.unit : ""}`;
  }

  function formatLayerValue(info, value) {
    if (info.categories) {
      const category = info.categories.find((item) => item.value === Math.round(value));
      return category ? category.label : String(Math.round(value));
    }
    return `${value.toFixed(info.digits)}${info.unit ? " " + info.unit : ""}`;
  }

  function icon(name) {
    return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONS[name]}"/></svg>`;
  }

  // --------------------------------------------------------------------
  // Selection
  // --------------------------------------------------------------------

  function includedRoutes() {
    const ids = state.settings.routes;
    return scene.routes.filter((route) => !ids || ids.includes(route.id));
  }

  function shownRoutes() {
    return includedRoutes().filter((route) => !state.hidden[route.id]);
  }

  function includedSources() {
    const ids = state.settings.sources;
    return scene.sources.filter((source) => !ids || ids.includes(source.id));
  }

  function includedOverlays() {
    const ids = state.settings.overlays;
    return scene.overlays.filter((overlay) => !ids || ids.includes(overlay.id));
  }

  // The layers of a source that the file shows, in its order.
  function includedLayers(source) {
    const ids = state.settings.fields;
    return source ? source.layers.filter((layer) => scene.layers[layer] && (!ids || ids.includes(layer))) : [];
  }

  // The arrows a source can draw: those of a layer it shows.
  function availableArrows(source) {
    const layers = includedLayers(source);
    return Object.keys(ARROW_QUANTITIES).filter((kind) =>
      ARROW_QUANTITIES[kind].every((name) => source.quantities[name]) && layers.some((layer) => scene.layers[layer].arrows === kind));
  }

  // The arrows drawn: the analyst's, else those of the layer shown.
  function currentArrows(source) {
    if (!source) return null;
    const info = scene.layers[state.layer];
    const wanted = state.arrowKind === null ? (info ? info.arrows : null) : state.arrowKind;
    return availableArrows(source).includes(wanted) ? wanted : null;
  }

  function currentSource() {
    const sources = includedSources();
    return sources.find((source) => source.id === state.source) || sources[0] || null;
  }

  function hoverVariables() {
    const names = Object.keys(scene.variables);
    const chosen = state.settings.hover;
    return chosen ? chosen.filter((name) => names.includes(name)) : names;
  }

  function routeLabel(route) {
    return (state.labels[route.id] || "").trim() || route.label;
  }

  function routeDescription(route) {
    return route.id in state.descriptions ? state.descriptions[route.id] || "" : route.description || "";
  }

  // Comments on points of a route, by segment: [{k, text}], in order.
  function routeComments(route) {
    if (!(route.id in state.comments)) return route.comments || [];
    const given = state.comments[route.id] || {};
    return Object.keys(given)
      .map((k) => ({ k: Number(k), text: String(given[k] || "").trim() }))
      .filter((item) => item.text && item.k >= 0 && item.k < route.ctim.length)
      .sort((a, b) => a.k - b.k);
  }

  function commentAt(route, k) {
    const found = routeComments(route).find((item) => item.k === k);
    return found ? found.text : "";
  }

  function ensureSelection() {
    const source = currentSource();
    state.source = source ? source.id : null;
    const layers = includedLayers(source);
    if (source && state.layer && !layers.includes(state.layer)) state.layer = null;
    if (source && state.layer === null) {
      state.layer = layers.includes("wind") ? "wind" : (layers[0] || "");
    }
  }

  function computeRange() {
    let r0 = Infinity, r1 = -Infinity, s0 = Infinity, s1 = -Infinity;
    includedRoutes().forEach((route) => {
      r0 = Math.min(r0, route.tim[0]);
      r1 = Math.max(r1, route.tim[route.tim.length - 1]);
    });
    includedSources().forEach((source) => {
      if (!source.times.length) return;
      s0 = Math.min(s0, source.times[0]);
      s1 = Math.max(s1, source.times[source.times.length - 1]);
    });
    const routes = r0 <= r1, sources = s0 <= s1;
    if (routes && sources && s1 >= r0 && s0 <= r1) {
      state.t0 = Math.min(r0, s0);
      state.t1 = Math.max(r1, s1);
    } else if (routes) {
      state.t0 = r0; state.t1 = r1;
    } else if (sources) {
      state.t0 = s0; state.t1 = s1;
    } else {
      const now = Math.round(Date.now() / 1000 / HOUR) * HOUR;
      state.t0 = now - DAY; state.t1 = now + DAY;
    }
    // The timeline reaches the valid time of each chart shown over the map.
    includedOverlays().forEach((overlay) => {
      if (typeof overlay.time !== "number") return;
      state.t0 = Math.min(state.t0, overlay.time - OVERLAY_MARGIN);
      state.t1 = Math.max(state.t1, overlay.time + OVERLAY_MARGIN);
    });
    if (state.t1 <= state.t0) state.t1 = state.t0 + HOUR;
  }

  function initialTime() {
    const now = Date.now() / 1000;
    if (stored && typeof stored.t === "number" && stored.t >= state.t0 && stored.t <= state.t1) return stored.t;
    if (now >= state.t0 && now <= state.t1) return Math.round(now / HOUR) * HOUR;
    const routes = includedRoutes();
    if (routes.length) return Math.min(...routes.map((route) => route.tim[0]));
    return state.t0;
  }

  // --------------------------------------------------------------------
  // Forecast frames
  // --------------------------------------------------------------------

  function decodePng(uri) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = image.width;
        canvas.height = image.height;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        context.drawImage(image, 0, 0);
        resolve(context.getImageData(0, 0, image.width, image.height).data);
      };
      image.onerror = reject;
      image.src = uri;
    });
  }

  function decodeSources() {
    const tasks = [];
    scene.sources.forEach((source) => {
      const cells = source.grid.nlat * source.grid.nlon;
      source.data = {};
      Object.keys(source.quantities).forEach((name) => { source.data[name] = new Array(source.times.length); });
      source.packs.forEach((pack) => {
        pack.frames.forEach((uri, frame) => {
          tasks.push(decodePng(uri).then((pixels) => {
            pack.quantities.forEach((name, channel) => {
              const values = new Uint8Array(cells);
              for (let k = 0; k < cells; k++) values[k] = pixels[4 * k + channel];
              source.data[name][frame] = values;
            });
          }));
        });
      });
    });
    return Promise.all(tasks).then(() => { scene.sources.forEach((source) => { source.ready = true; }); });
  }

  function frameAt(source, t) {
    const times = source.times;
    const count = times.length;
    if (!source.ready || !count || t < times[0] - 1 || t > times[count - 1] + 1) return null;
    if (count === 1) return { i0: 0, i1: 0, a: 0 };
    let low = 0, high = count - 1;
    while (high - low > 1) {
      const middle = (low + high) >> 1;
      if (times[middle] <= t) low = middle; else high = middle;
    }
    const a = Math.min(1, Math.max(0, (t - times[low]) / (times[high] - times[low])));
    return { i0: low, i1: high, a };
  }

  let blendKey = null;
  let blendGrids = {};

  // The grid of a quantity at time t, interpolated between frames.
  function grid(source, name, t) {
    const key = `${source.id}@${t}`;
    if (key !== blendKey) { blendKey = key; blendGrids = {}; }
    if (name in blendGrids) return blendGrids[name];
    const frame = frameAt(source, t);
    const info = source.quantities[name];
    if (!frame || !info || !source.data[name]) return (blendGrids[name] = null);
    const first = source.data[name][frame.i0], second = source.data[name][frame.i1];
    const out = new Float32Array(first.length);
    // Categories are not blended: the nearest frame gives them.
    const a = info.categorical ? Math.round(frame.a) : frame.a, offset = info.offset, scale = info.scale;
    for (let k = 0; k < first.length; k++) {
      const b0 = first[k], b1 = second[k];
      out[k] = b0 === NO_DATA || b1 === NO_DATA ? NaN : offset + scale * (b0 + a * (b1 - b0));
    }
    return (blendGrids[name] = out);
  }

  // Bilinear value at fractional grid indices; NaN where missing values weigh most.
  function bilinear(values, g, x, y) {
    if (!(x >= 0 && y >= 0 && x <= g.nlon - 1 && y <= g.nlat - 1)) return NaN;
    const i = Math.min(Math.floor(x), g.nlon - 2), j = Math.min(Math.floor(y), g.nlat - 2);
    const fx = x - i, fy = y - j, n = g.nlon;
    const corners = [values[j * n + i], values[j * n + i + 1], values[(j + 1) * n + i], values[(j + 1) * n + i + 1]];
    const weights = [(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy];
    let sum = 0, weight = 0;
    for (let c = 0; c < 4; c++) {
      if (corners[c] === corners[c]) { sum += weights[c] * corners[c]; weight += weights[c]; }
    }
    return weight >= 0.5 ? sum / weight : NaN;
  }

  // The value of the nearest point of the grid, for categories.
  function nearest(values, g, x, y) {
    if (!(x >= -0.5 && y >= -0.5 && x <= g.nlon - 0.5 && y <= g.nlat - 0.5)) return NaN;
    const i = Math.min(g.nlon - 1, Math.max(0, Math.round(x))), j = Math.min(g.nlat - 1, Math.max(0, Math.round(y)));
    return values[j * g.nlon + i];
  }

  function interpolate(categorical, values, g, x, y) {
    return categorical ? nearest(values, g, x, y) : bilinear(values, g, x, y);
  }

  function sampleAt(source, name, t, lat, lon) {
    const values = grid(source, name, t);
    if (!values) return NaN;
    const g = source.grid;
    return interpolate(source.quantities[name].categorical, values, g, (lon - g.lon0) / g.dlon, (lat - g.lat0) / g.dlat);
  }

  // The values a layer colours: a quantity, or the norm of a vector.
  function valueGrid(source, layer, t) {
    const info = scene.layers[layer];
    if (!info) return null;
    if (info.vector) {
      const u = grid(source, info.vector[0], t), v = grid(source, info.vector[1], t);
      if (!u || !v) return null;
      const out = new Float32Array(u.length);
      for (let k = 0; k < u.length; k++) out[k] = Math.hypot(u[k], v[k]);
      return out;
    }
    return grid(source, info.quantity, t);
  }

  function layerValueAt(source, layer, t, lat, lon) {
    const info = scene.layers[layer];
    const values = valueGrid(source, layer, t);
    if (!values) return NaN;
    const g = source.grid;
    return interpolate(!!info.categories, values, g, (lon - g.lon0) / g.dlon, (lat - g.lat0) / g.dlat);
  }

  // --------------------------------------------------------------------
  // Field raster
  // --------------------------------------------------------------------

  const rasterCanvas = document.createElement("canvas");
  const rasterContext = rasterCanvas.getContext("2d");
  const lookupTables = {};

  function mercator(lat) {
    const s = Math.sin((lat * Math.PI) / 180);
    return 0.5 * Math.log((1 + s) / (1 - s));
  }

  function inverseMercator(y) {
    return ((2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180) / Math.PI;
  }

  function clampLat(lat) { return Math.max(-MERCATOR_LIMIT, Math.min(MERCATOR_LIMIT, lat)); }

  function rasterGeometry(source) {
    if (source.raster) return source.raster;
    const g = source.grid;
    const south = clampLat(g.lat0), north = clampLat(g.lat0 + g.dlat * (g.nlat - 1));
    const west = g.lon0, east = g.lon0 + g.dlon * (g.nlon - 1);
    const width = Math.max(64, Math.min(1200, g.nlon * 3));
    const span = ((east - west) * Math.PI) / 180;
    const height = Math.max(32, Math.min(1200, Math.round((width * (mercator(north) - mercator(south))) / span)));
    const rows = new Float32Array(height), columns = new Float32Array(width);
    const top = mercator(north), bottom = mercator(south);
    for (let r = 0; r < height; r++) {
      const lat = inverseMercator(top - ((r + 0.5) / height) * (top - bottom));
      rows[r] = (lat - g.lat0) / g.dlat;
    }
    for (let c = 0; c < width; c++) {
      const lon = west + ((c + 0.5) / width) * (east - west);
      columns[c] = (lon - g.lon0) / g.dlon;
    }
    source.raster = {
      width, height, rows, columns,
      coordinates: [[west, north], [east, north], [east, south], [west, south]],
      bounds: [[west, south], [east, north]],
    };
    return source.raster;
  }

  function lookupTable(layer) {
    if (lookupTables[layer]) return lookupTables[layer];
    const info = scene.layers[layer];
    const colors = info.categories ? info.categories.map((category) => category.color || "#000000") : info.colormap.colors;
    const table = new Uint8Array(colors.length * 3);
    colors.forEach((hex, index) => {
      table[3 * index] = parseInt(hex.slice(1, 3), 16);
      table[3 * index + 1] = parseInt(hex.slice(3, 5), 16);
      table[3 * index + 2] = parseInt(hex.slice(5, 7), 16);
    });
    return (lookupTables[layer] = table);
  }

  // The entry of the colour table of a layer for a value, or -1 for none:
  // a category without colour, or a value under the floor of the layer.
  function colourIndex(layer) {
    const info = scene.layers[layer];
    if (info.categories) {
      const byValue = {};
      info.categories.forEach((category, index) => { if (category.color) byValue[category.value] = index; });
      return (value) => { const index = byValue[Math.round(value)]; return index === undefined ? -1 : index; };
    }
    const steps = lookupTable(layer).length / 3 - 1;
    const low = info.colormap.min, span = info.colormap.max - info.colormap.min;
    const floor = typeof info.floor === "number" ? info.floor : -Infinity;
    return (value) => (value < floor ? -1 : Math.max(0, Math.min(steps, Math.round(((value - low) / span) * steps))));
  }

  function renderField() {
    const source = currentSource();
    const layer = state.layer;
    let drawn = false;
    if (source && layer && includedLayers(source).includes(layer)) {
      const values = valueGrid(source, layer, state.t);
      if (values) {
        const geometry = rasterGeometry(source);
        const table = lookupTable(layer);
        const indexOf = colourIndex(layer);
        const categorical = !!scene.layers[layer].categories;
        if (rasterCanvas.width !== geometry.width) rasterCanvas.width = geometry.width;
        if (rasterCanvas.height !== geometry.height) rasterCanvas.height = geometry.height;
        const image = rasterContext.createImageData(geometry.width, geometry.height);
        const pixels = image.data;
        let p = 0;
        for (let r = 0; r < geometry.height; r++) {
          const y = geometry.rows[r];
          for (let c = 0; c < geometry.width; c++, p += 4) {
            const value = interpolate(categorical, values, source.grid, geometry.columns[c], y);
            if (value !== value) continue;
            const entry = indexOf(value);
            if (entry < 0) continue;
            const index = 3 * entry;
            pixels[p] = table[index];
            pixels[p + 1] = table[index + 1];
            pixels[p + 2] = table[index + 2];
            pixels[p + 3] = 255;
          }
        }
        rasterContext.putImageData(image, 0, 0);
        map.getSource("field").updateImage({ url: rasterCanvas.toDataURL(), coordinates: geometry.coordinates });
        drawn = true;
      }
    }
    setVisible("field", drawn);
    updateLegend(drawn ? layer : null);
  }

  function updateLegend(layer) {
    const legend = $("legend");
    if (!layer) { legend.hidden = true; return; }
    const info = scene.layers[layer];
    const source = currentSource();
    const unit = [info.unit, source ? source.label : ""].filter(Boolean).join(" · ");
    let scale;
    if (info.categories) {
      scale = '<div class="categories">' + info.categories.filter((category) => category.color).map((category) =>
        `<span><i class="swatch" style="background:${category.color}"></i>${escapeHtml(category.label)}</span>`).join("") + "</div>";
    } else {
      const colormap = info.colormap;
      const stops = colormap.colors.map((color, index) => `${color} ${((100 * index) / (colormap.colors.length - 1)).toFixed(1)}%`);
      const ticks = info.ticks.map((tick) => {
        const left = (100 * (tick - colormap.min)) / (colormap.max - colormap.min);
        return `<span style="left:${left.toFixed(1)}%">${tick}</span>`;
      });
      scale = `<div class="bar" style="background:linear-gradient(to right, ${stops.join(", ")})"></div><div class="ticks">${ticks.join("")}</div>`;
    }
    legend.innerHTML =
      `<div class="legend-title"><b>${escapeHtml(info.label)}</b><span>${escapeHtml(unit)}</span></div>` +
      scale + (currentArrows(source) === "waves" ? WAVE_KEY : "");
    legend.hidden = false;
  }

  // How to read the wave glyphs, under the wave scale.
  const WAVE_KEY =
    '<div class="key" title="Each glyph points where the waves go: a solid head for 4 m, an open chevron for 1 m">' +
    '<span><svg viewBox="0 0 14 14"><path d="M7 2l6 9H1z" stroke="none"/></svg>4 m</span>' +
    '<span><svg viewBox="0 0 14 14"><path d="M2 10 7 4l5 6" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>1 m</span>' +
    "<span>towards where they go</span></div>";

  // --------------------------------------------------------------------
  // Arrows, barbs and isobars
  // --------------------------------------------------------------------

  function drawImage(size, draw) {
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext("2d");
    context.lineCap = "round";
    context.lineJoin = "round";
    draw(context);
    return context.getImageData(0, 0, size, size);
  }

  function ensureImage(id, size, draw) {
    if (!map.hasImage(id)) map.addImage(id, drawImage(size, draw), { pixelRatio: 2 });
    return id;
  }

  function hsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    const l = (max + min) / 2;
    if (max === min) return [0, 0, l];
    const d = max - min;
    const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    let h;
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    return [h * 60, s, l];
  }

  // The colour of a value on the scale of a layer, made vivid for arrows and
  // barbs: the hue of the field under them, saturated, with the lightness of
  // the theme, so that they stand out from the field in its own colours.
  const glyphColors = {};
  function glyphColor(layer, value) {
    const table = lookupTable(layer);
    const index = colourIndex(layer)(value);
    const key = `${state.theme}-${layer}-${index}`;
    if (!(key in glyphColors)) {
      // A value without colour, such as no precipitation, gives a grey.
      const [h, s, l] = index < 0 ? [0, 0, 0.6] : hsl(table[3 * index], table[3 * index + 1], table[3 * index + 2]);
      // Greys stay grey, as saturating them would give them a hue they do not
      // have, and stand out by their lightness instead.
      const grey = s < 0.08;
      const saturation = grey ? s : Math.max(s, 0.9);
      const lightness = grey ? (l > 0.5 ? 0.2 : 0.88) : THEMES[state.theme].glyphLightness;
      glyphColors[key] = { key: `${layer}${index}`, css: `hsl(${h.toFixed(0)}, ${Math.round(100 * saturation)}%, ${Math.round(100 * lightness)}%)` };
    }
    return glyphColors[key];
  }

  // A wind barb pointing north, feathers on the right in the northern
  // hemisphere and on the left in the southern one, in one flat colour.
  function ensureBarb(knots, south, color) {
    const id = `barb-${state.theme}-${south ? "s" : "n"}-${knots}-${color.key}`;
    return ensureImage(id, 96, (context) => {
      const side = south ? -1 : 1;
      const x = 48;
      const lines = [];
      const flags = [];
      if (knots < 5) {
        lines.push((c) => { c.moveTo(x + 5, 48); c.arc(x, 48, 5, 0, 2 * Math.PI); });
      } else {
        lines.push((c) => { c.moveTo(x, 48); c.lineTo(x, 10); });
        let rest = knots, y = 10;
        while (rest >= 50) {
          const at = y;
          flags.push((c) => { c.moveTo(x, at); c.lineTo(x + side * 16, at - 2); c.lineTo(x, at + 8); c.closePath(); });
          y += 11;
          rest -= 50;
        }
        const full = Math.floor(rest / 10);
        for (let k = 0; k < full; k++) {
          const at = y;
          lines.push((c) => { c.moveTo(x, at); c.lineTo(x + side * 16, at - 7); });
          y += 7;
        }
        if (rest % 10 >= 5) {
          // A lone half barb stands back from the end of the staff.
          const at = full === 0 && knots < 50 ? y + 7 : y;
          lines.push((c) => { c.moveTo(x, at); c.lineTo(x + side * 8.5, at - 3.5); });
        }
      }
      context.strokeStyle = color.css;
      context.fillStyle = color.css;
      context.lineWidth = 3;
      lines.forEach((path) => { context.beginPath(); path(context); context.stroke(); });
      flags.forEach((path) => { context.beginPath(); path(context); context.fill(); });
    });
  }

  // The parts of a wave glyph of a height in metres: a solid head for each
  // 4 m, then an open chevron for each metre left.
  function waveParts(metres) {
    const heads = Math.min(4, Math.floor(metres / 4));
    return { heads, chevrons: Math.min(3, metres - 4 * heads) };
  }

  // A wave glyph pointing where the waves go, heads first, in one flat
  // colour; a dot under half a metre. Heads overlap like the tiers of a fir
  // tree, each tier a notch, so that the glyph stays short in high seas.
  function ensureWaveGlyph(metres, color) {
    const id = `wave-${state.theme}-${metres}-${color.key}`;
    return ensureImage(id, 96, (context) => {
      const x = 48, HALF = 12, HEAD = 15, HEAD_STEP = 9, GAP = 5, CHEVRON = 9, CHEVRON_STEP = 7;
      context.fillStyle = color.css;
      context.strokeStyle = color.css;
      if (metres <= 0) {
        context.beginPath();
        context.arc(x, 48, 4, 0, 2 * Math.PI);
        context.fill();
        return;
      }
      const { heads, chevrons } = waveParts(metres);
      let length = 0;
      if (heads) length += HEAD + (heads - 1) * HEAD_STEP;
      if (heads && chevrons) length += GAP;
      if (chevrons) length += CHEVRON + (chevrons - 1) * CHEVRON_STEP;
      let y = 48 - length / 2;
      for (let i = 0; i < heads; i++) {
        context.beginPath();
        context.moveTo(x, y);
        context.lineTo(x + HALF, y + HEAD);
        context.lineTo(x - HALF, y + HEAD);
        context.closePath();
        context.fill();
        y += i < heads - 1 ? HEAD_STEP : HEAD + GAP;
      }
      context.lineWidth = 3.5;
      for (let i = 0; i < chevrons; i++) {
        context.beginPath();
        context.moveTo(x - HALF + 1.5, y + CHEVRON);
        context.lineTo(x, y + 1);
        context.lineTo(x + HALF - 1.5, y + CHEVRON);
        context.stroke();
        y += CHEVRON_STEP;
      }
    });
  }

  function ensureCurrentArrow(color) {
    const id = `current-${state.theme}-${color.key}`;
    return ensureImage(id, 64, (context) => {
      context.strokeStyle = color.css;
      context.fillStyle = color.css;
      context.lineWidth = 3.5;
      context.beginPath();
      context.moveTo(32, 54);
      context.lineTo(32, 20);
      context.stroke();
      context.beginPath();
      context.moveTo(32, 7);
      context.lineTo(23, 23);
      context.lineTo(41, 23);
      context.closePath();
      context.fill();
    });
  }

  // Boats and comment bubbles belong to their route: its colour, with the
  // same thin white outline.
  function ensureBoat(route) {
    const id = `boat-${route.color}`;
    return ensureImage(id, 64, (context) => {
      context.beginPath();
      context.moveTo(32, 5);
      context.bezierCurveTo(41, 15, 43, 27, 43, 38);
      context.lineTo(42, 58);
      context.lineTo(22, 58);
      context.lineTo(21, 38);
      context.bezierCurveTo(21, 27, 23, 15, 32, 5);
      context.closePath();
      context.fillStyle = route.color;
      context.fill();
      context.strokeStyle = "#ffffff";
      context.lineWidth = 2;
      context.stroke();
    });
  }

  function ensureCommentIcon(route) {
    const id = `comment-${route.color}`;
    return ensureImage(id, 48, (context) => {
      context.beginPath();
      context.moveTo(18, 4);
      context.lineTo(38, 4);
      context.quadraticCurveTo(45, 4, 45, 11);
      context.lineTo(45, 23);
      context.quadraticCurveTo(45, 30, 38, 30);
      context.lineTo(22, 30);
      context.lineTo(4, 44);
      context.lineTo(12, 30);
      context.quadraticCurveTo(11, 30, 11, 23);
      context.lineTo(11, 11);
      context.quadraticCurveTo(11, 4, 18, 4);
      context.closePath();
      context.fillStyle = route.color;
      context.fill();
      context.strokeStyle = "#ffffff";
      context.lineWidth = 2;
      context.stroke();
      context.fillStyle = "#ffffff";
      [20, 28, 36].forEach((cx) => { context.beginPath(); context.arc(cx, 17, 2.4, 0, 2 * Math.PI); context.fill(); });
    });
  }

  // Arrows sit on a fixed lattice of positions: rows every `spacing` degrees
  // of latitude from the equator, and along each row every `spacing` over
  // the cosine of its latitude from the prime meridian, so that they are
  // evenly spread on the globe whatever the grid of the forecast. The
  // spacing changes with the zoom only, by half zoom levels: panning or
  // rotating the globe moves no arrow.
  // On the globe, a degree of latitude spans 512 * 2^zoom / 360 / cos(latitude
  // of the view) pixels; the middle of the grid stands for the view, so that
  // the lattice does not move with it.
  function latticeSpacing(g, layer) {
    const middle = g.lat0 + (g.dlat * (g.nlat - 1)) / 2;
    const scale = Math.max(Math.cos((middle * Math.PI) / 180), 0.3);
    const zoom = Math.round(2 * map.getZoom()) / 2;
    return (ARROW_SPACING[layer] * 360 * scale) / (512 * Math.pow(2, zoom));
  }

  // The view, with a margin, in degrees, or null when unknown.
  function viewBox() {
    try {
      const bounds = map.getBounds();
      const south = bounds.getSouth(), north = bounds.getNorth(), west = bounds.getWest(), east = bounds.getEast();
      if (!(east - west < 360)) return null;
      const dy = 0.2 * (north - south), dx = 0.2 * (east - west);
      return { south: south - dy, north: north + dy, west: west - dx, east: east + dx };
    } catch (error) {
      return null;
    }
  }

  function arrowFields(source, kind) {
    const t = state.t;
    if (kind === "waves") {
      const h = grid(source, "swh", t), x = grid(source, "wave_x", t), y = grid(source, "wave_y", t);
      return h && x && y ? { h, x, y } : null;
    }
    const u = grid(source, kind === "wind" ? "wind_u" : "current_u", t);
    const v = grid(source, kind === "wind" ? "wind_v" : "current_v", t);
    return u && v ? { u, v } : null;
  }

  function updateArrows() {
    const source = currentSource();
    const kind = currentArrows(source);
    const features = [];
    const fields = kind && frameAt(source, state.t) ? arrowFields(source, kind) : null;
    if (fields) {
      const g = source.grid;
      const spacing = latticeSpacing(g, kind);
      // Arrows take the colour of the layer shown under them, else their own.
      const shown = state.layer && includedLayers(source).includes(state.layer) ? state.layer : null;
      const colours = shown ? valueGrid(source, shown, state.t) : null;
      const categorical = shown && !!scene.layers[shown].categories;
      let south = g.lat0, north = g.lat0 + g.dlat * (g.nlat - 1);
      let west = g.lon0, east = g.lon0 + g.dlon * (g.nlon - 1);
      const middle = Math.cos(((south + north) * Math.PI) / 360);
      // Too many arrows over the whole grid: those of the view only.
      if (((north - south) / spacing) * (((east - west) * middle) / spacing) > MAX_ARROWS) {
        const view = viewBox();
        if (view) {
          south = Math.max(south, view.south); north = Math.min(north, view.north);
          west = Math.max(west, view.west); east = Math.min(east, view.east);
        }
      }
      for (let j = Math.ceil(south / spacing); j * spacing <= north && features.length < MAX_ARROWS; j++) {
        const lat = j * spacing;
        if (Math.abs(lat) > 82) continue;
        const step = spacing / Math.cos((lat * Math.PI) / 180);
        const y = (lat - g.lat0) / g.dlat;
        for (let i = Math.ceil(west / step); i * step <= east && features.length < MAX_ARROWS; i++) {
          const lon = i * step;
          const x = (lon - g.lon0) / g.dlon;
          const under = colours ? interpolate(categorical, colours, g, x, y) : NaN;
          const colour = (own, value) => (under === under ? glyphColor(shown, under) : glyphColor(own, value));
          const feature = arrowFeature(fields, kind, (values) => bilinear(values, g, x, y), lat, lon, colour);
          if (feature) features.push(feature);
        }
      }
    }
    map.getSource("arrows").setData({ type: "FeatureCollection", features });
  }

  // The arrow of a position, from `at`, which interpolates a grid there,
  // and `colour`, which gives its colour from its own layer and value.
  function arrowFeature(fields, kind, at, lat, lon, colour) {
    const geometry = { type: "Point", coordinates: [lon, lat] };
    if (kind === "wind") {
      const u = at(fields.u), v = at(fields.v);
      if (!(u === u && v === v)) return null;
      const speed = Math.hypot(u, v);
      const knots = Math.min(150, Math.round(speed / 5) * 5);
      const from = (Math.atan2(-u, -v) * 180) / Math.PI;
      return { type: "Feature", geometry, properties: { icon: ensureBarb(knots, lat < 0, colour("wind", speed)), rotate: from, size: 1 } };
    }
    if (kind === "waves") {
      const height = at(fields.h), x = at(fields.x), y = at(fields.y);
      if (!(height === height && x === x && y === y)) return null;
      const towards = (Math.atan2(x, y) * 180) / Math.PI + 180;
      return { type: "Feature", geometry, properties: { icon: ensureWaveGlyph(Math.round(height), colour("waves", height)), rotate: towards, size: 1 } };
    }
    const u = at(fields.u), v = at(fields.v);
    const speed = Math.hypot(u, v);
    if (!(speed === speed) || speed < 0.05) return null;
    const towards = (Math.atan2(u, v) * 180) / Math.PI;
    return { type: "Feature", geometry, properties: { icon: ensureCurrentArrow(colour("current", speed)), rotate: towards, size: 0.45 + (0.65 * Math.min(speed, 3)) / 3 } };
  }

  // Segments of the contour of a level, by marching squares.
  function contour(values, g, level) {
    const segments = [];
    const n = g.nlon;
    const point = (x, y) => [Math.round((g.lon0 + x * g.dlon) * 1e3) / 1e3, Math.round((g.lat0 + y * g.dlat) * 1e3) / 1e3];
    for (let j = 0; j < g.nlat - 1; j++) {
      for (let i = 0; i < n - 1; i++) {
        const v0 = values[j * n + i], v1 = values[j * n + i + 1];
        const v2 = values[(j + 1) * n + i + 1], v3 = values[(j + 1) * n + i];
        if (!(v0 === v0 && v1 === v1 && v2 === v2 && v3 === v3)) continue;
        const index = (v0 >= level ? 1 : 0) | (v1 >= level ? 2 : 0) | (v2 >= level ? 4 : 0) | (v3 >= level ? 8 : 0);
        if (index === 0 || index === 15) continue;
        const edge = [
          () => point(i + (level - v0) / (v1 - v0), j),
          () => point(i + 1, j + (level - v1) / (v2 - v1)),
          () => point(i + (level - v3) / (v2 - v3), j + 1),
          () => point(i, j + (level - v0) / (v3 - v0)),
        ];
        const center = (v0 + v1 + v2 + v3) / 4;
        let pairs;
        switch (index) {
          case 1: case 14: pairs = [[3, 0]]; break;
          case 2: case 13: pairs = [[0, 1]]; break;
          case 4: case 11: pairs = [[1, 2]]; break;
          case 8: case 7: pairs = [[2, 3]]; break;
          case 3: case 12: pairs = [[3, 1]]; break;
          case 6: case 9: pairs = [[0, 2]]; break;
          case 5: pairs = center >= level ? [[0, 1], [2, 3]] : [[3, 0], [1, 2]]; break;
          case 10: pairs = center >= level ? [[3, 0], [1, 2]] : [[0, 1], [2, 3]]; break;
          default: pairs = [];
        }
        pairs.forEach(([a, b]) => segments.push([edge[a](), edge[b]()]));
      }
    }
    return segments;
  }

  const isobarMarkers = [];

  function updateIsobars() {
    const source = currentSource();
    const features = [];
    const labels = [];
    const values = state.isobars && source && source.quantities.pressure && includedLayers(source).includes("pressure") ? grid(source, "pressure", state.t) : null;
    if (values) {
      let low = Infinity, high = -Infinity;
      for (let k = 0; k < values.length; k++) {
        if (values[k] === values[k]) { low = Math.min(low, values[k]); high = Math.max(high, values[k]); }
      }
      for (let level = Math.ceil(low / 4) * 4; level <= high; level += 4) {
        const segments = contour(values, source.grid, level);
        if (!segments.length) continue;
        features.push({ type: "Feature", properties: { level }, geometry: { type: "MultiLineString", coordinates: segments } });
        if (!state.isobarLabels) continue;
        const picks = segments.length > 80 ? [0.3, 0.7] : [0.5];
        picks.forEach((fraction) => {
          const segment = segments[Math.floor(fraction * (segments.length - 1))];
          labels.push({ lon: segment[0][0], lat: segment[0][1], text: String(level) });
        });
      }
    }
    map.getSource("isobars").setData({ type: "FeatureCollection", features });
    while (isobarMarkers.length < labels.length) {
      const element = document.createElement("div");
      element.className = "map-label isobar-label";
      isobarMarkers.push({ marker: new maplibregl.Marker({ element }), added: false });
    }
    isobarMarkers.forEach((item, index) => {
      if (index < labels.length) {
        item.marker.getElement().textContent = labels[index].text;
        item.marker.setLngLat([labels[index].lon, labels[index].lat]);
        if (!item.added) { item.marker.addTo(map); item.added = true; }
      } else if (item.added) {
        item.marker.remove();
        item.added = false;
      }
    });
  }

  // --------------------------------------------------------------------
  // Routes, zones, overlays
  // --------------------------------------------------------------------

  function routePosition(route, t) {
    const times = route.tim;
    const last = times.length - 1;
    if (t <= times[0]) return { lat: route.lat[0], lon: route.lon[0], k: 0, phase: "before" };
    if (t >= times[last]) return { lat: route.lat[last], lon: route.lon[last], k: Math.max(0, last - 1), phase: "after" };
    let low = 0, high = last;
    while (high - low > 1) {
      const middle = (low + high) >> 1;
      if (times[middle] <= t) low = middle; else high = middle;
    }
    const f = (t - times[low]) / (times[high] - times[low]);
    return {
      lat: route.lat[low] + f * (route.lat[high] - route.lat[low]),
      lon: route.lon[low] + f * (route.lon[high] - route.lon[low]),
      k: Math.min(low, route.ctim.length - 1),
      phase: "under way",
    };
  }

  function updateRoutes() {
    const shown = shownRoutes();
    map.getSource("routes").setData({
      type: "FeatureCollection",
      features: shown.map((route) => ({
        type: "Feature",
        properties: { id: route.id, color: route.color },
        geometry: { type: "LineString", coordinates: route.lon.map((lon, i) => [lon, route.lat[i]]) },
      })),
    });
    const points = [];
    shown.forEach((route) => {
      route.clat.forEach((lat, k) => {
        points.push({ type: "Feature", properties: { id: route.id, k, color: route.color }, geometry: { type: "Point", coordinates: [route.clon[k], lat] } });
      });
    });
    map.getSource("route-points").setData({ type: "FeatureCollection", features: points });
    updateComments();
    updateBoats();
  }

  function updateComments() {
    if (!map.getSource("comments")) return;
    const features = [];
    shownRoutes().forEach((route) => {
      routeComments(route).forEach((item) => {
        features.push({
          type: "Feature",
          properties: { id: route.id, k: item.k, icon: ensureCommentIcon(route) },
          geometry: { type: "Point", coordinates: [route.clon[item.k], route.clat[item.k]] },
        });
      });
    });
    map.getSource("comments").setData({ type: "FeatureCollection", features });
  }

  function updateBoats() {
    if (!map.getSource("boats")) return;
    map.getSource("boats").setData({
      type: "FeatureCollection",
      features: shownRoutes().map((route) => {
        const position = routePosition(route, state.t);
        return {
          type: "Feature",
          properties: { id: route.id, icon: ensureBoat(route), rotate: route.cog[position.k] || 0, opacity: position.phase === "under way" ? 1 : 0.55 },
          geometry: { type: "Point", coordinates: [position.lon, position.lat] },
        };
      }),
    });
  }

  const zoneMarkers = [];

  function updateZones() {
    const visible = scene.zones.filter((zone) => state.zones[zone.id] && zone.outline.length >= 2);
    map.getSource("zones").setData({
      type: "FeatureCollection",
      features: visible.map((zone) => ({ type: "Feature", properties: { color: zone.color }, geometry: { type: "LineString", coordinates: zone.outline } })),
    });
    zoneMarkers.splice(0).forEach((marker) => marker.remove());
    visible.forEach((zone) => {
      const element = document.createElement("div");
      element.className = "map-label";
      element.style.color = zone.color;
      element.textContent = zone.label;
      const lon = zone.outline.reduce((sum, p) => sum + p[0], 0) / zone.outline.length;
      const lat = zone.outline.reduce((sum, p) => sum + p[1], 0) / zone.outline.length;
      zoneMarkers.push(new maplibregl.Marker({ element }).setLngLat([lon, lat]).addTo(map));
    });
  }

  function updateBasemap() {
    setVisible("osm", state.basemap === "osm");
    setVisible("land", state.basemap !== "osm");
    COAST_LAYERS.forEach(([id]) => setVisible(id, state.basemap !== "osm"));
    setVisible("seamarks", state.seamarks);
    setVisible("graticule", state.graticule);
    const included = includedOverlays();
    scene.overlays.forEach((overlay) => setVisible(`overlay-${overlay.id}`, included.includes(overlay) && !!state.overlays[overlay.id]));
  }

  function setVisible(layer, visible) {
    if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", visible ? "visible" : "none");
  }

  function fitRoutes() {
    const routes = shownRoutes().length ? shownRoutes() : includedRoutes();
    let bounds = null;
    routes.forEach((route) => route.lon.forEach((lon, i) => {
      const point = [lon, route.lat[i]];
      bounds = bounds ? bounds.extend(point) : new maplibregl.LngLatBounds(point, point);
    }));
    if (!bounds) {
      const source = currentSource();
      if (!source) return;
      const b = rasterGeometry(source).bounds;
      bounds = new maplibregl.LngLatBounds(b[0], b[1]);
    }
    const canvas = map.getCanvas();
    const width = canvas.clientWidth, height = canvas.clientHeight;
    const timeline = $("timeline").offsetHeight;
    const left = state.panelOpen && width > 720 ? $("panel").offsetWidth + 40 : 40;
    const padding = {
      top: Math.min(90, height / 4),
      bottom: Math.min(timeline + 50, height / 3),
      left: Math.min(left, width / 3),
      right: Math.min(70, width / 4),
    };
    map.fitBounds(bounds, { padding, duration: 600, maxZoom: 7 });
  }

  // --------------------------------------------------------------------
  // Tooltips and readout
  // --------------------------------------------------------------------

  let popup = null;

  function routeById(id) { return scene.routes.find((route) => route.id === id); }

  function popupContent(route, k, t, phase) {
    const rows = hoverVariables()
      .filter((name) => route.values[name])
      .map((name) => {
        const meta = scene.variables[name];
        return `<tr><td title="${escapeHtml(meta.description)}">${escapeHtml(meta.label)}</td><td>${escapeHtml(formatValue(name, route.values[name][k]))}</td></tr>`;
      });
    let when = formatTime(t);
    if (phase === "before") when = `Not under way yet · ETD ${formatShort(route.etd)}`;
    if (phase === "after") when = `Arrived · ETA ${formatShort(route.eta)}`;
    const total = route.summary.fuel !== null ? `<tr><td>Voyage fuel</td><td>${route.summary.fuel.toFixed(1)} t</td></tr>` : "";
    // A point tells its comment, a boat the description of its route.
    const comment = phase === "segment" ? commentAt(route, k) : "";
    const description = phase === "segment" ? "" : routeDescription(route);
    return (
      `<div class="popup-title"><span class="swatch" style="background:${route.color}"></span>${escapeHtml(routeLabel(route))}</div>` +
      `<div class="popup-time">${escapeHtml(when)}</div>` +
      (comment ? `<div class="popup-text comment">${escapeHtml(comment)}</div>` : "") +
      (description ? `<div class="popup-text">${escapeHtml(description)}</div>` : "") +
      `<table class="popup-table">${phase === "under way" || phase === "segment" ? rows.join("") : ""}${total}</table>` +
      (state.editable && phase === "segment" ? `<div class="popup-hint">Click to ${comment ? "edit the" : "add a"} comment</div>` : "")
    );
  }

  function showPopup() {
    const target = state.popup;
    if (!target) { if (popup) { popup.remove(); popup = null; } return; }
    const route = routeById(target.id);
    if (!route || state.hidden[route.id] || !includedRoutes().includes(route)) { state.popup = null; showPopup(); return; }
    let lngLat, html;
    if (target.kind === "boat") {
      const position = routePosition(route, state.t);
      lngLat = [position.lon, position.lat];
      html = popupContent(route, position.k, state.t, position.phase);
    } else {
      lngLat = [route.clon[target.k], route.clat[target.k]];
      html = popupContent(route, target.k, route.ctim[target.k], "segment");
    }
    if (!popup) popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: "300px" });
    popup.setLngLat(lngLat).setHTML(html);
    if (!popup.isOpen()) popup.addTo(map);
  }

  function pick(point) {
    const hits = map.queryRenderedFeatures(point, { layers: ["boats", "comments", "route-hit"] });
    if (!hits.length) return null;
    const hit = hits.find((feature) => feature.layer.id === "boats") || hits.find((feature) => feature.layer.id === "comments") || hits[0];
    return hit.layer.id === "boats"
      ? { kind: "boat", id: hit.properties.id }
      : { kind: "point", id: hit.properties.id, k: hit.properties.k };
  }

  function onPointer(event) {
    const target = pick(event.point);
    map.getCanvas().style.cursor = target ? "pointer" : "";
    if (!state.editing) {
      state.popup = target;
      showPopup();
    }
    state.pointer = event.lngLat;
    updateReadout();
  }

  function onClick(event) {
    const target = pick(event.point);
    if (state.editable && target && target.kind === "point") {
      openEditor(target);
      return;
    }
    if (state.editing) closeEditor();
    if (!target && state.picker) setPicker({ lat: event.lngLat.lat, lon: wrapLongitude(event.lngLat.lng) });
    onPointer(event);
  }

  function wrapLongitude(lon) { return ((lon + 540) % 360) - 180; }

  // ------------------------------------------------------------------
  // Comments of the analyst, in the preview of ui.py
  // ------------------------------------------------------------------

  let editor = null;

  function openEditor(target) {
    const route = routeById(target.id);
    if (!route) return;
    closeEditor();
    state.editing = { id: route.id, k: target.k };
    state.popup = null;
    showPopup();
    updateReadout();
    const node = element("div", "editor");
    node.innerHTML =
      `<div class="popup-title"><span class="swatch" style="background:${route.color}"></span>${escapeHtml(routeLabel(route))}</div>` +
      `<div class="popup-time">${escapeHtml(formatTime(route.ctim[target.k]))}<br>${escapeHtml(formatPosition(route.clat[target.k], route.clon[target.k]))}</div>`;
    const area = element("textarea");
    area.rows = 4;
    area.placeholder = "Comment for the crew at this point of the route";
    area.value = commentAt(route, target.k);
    const buttons = element("div", "editor-buttons");
    const button = (label, className, action) => {
      const item = element("button", className, escapeHtml(label));
      item.type = "button";
      item.addEventListener("click", action);
      buttons.append(item);
    };
    button("Save", "primary", () => { saveComment(route, target.k, area.value); closeEditor(); });
    if (area.value) button("Delete", "", () => { saveComment(route, target.k, ""); closeEditor(); });
    button("Cancel", "", closeEditor);
    area.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeEditor();
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { saveComment(route, target.k, area.value); closeEditor(); }
    });
    node.append(area, buttons);
    editor = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: "320px" })
      .setLngLat([route.clon[target.k], route.clat[target.k]])
      .setDOMContent(node)
      .addTo(map);
    area.focus();
  }

  function closeEditor() {
    state.editing = null;
    if (editor) { editor.remove(); editor = null; }
  }

  function saveComment(route, k, text) {
    const current = {};
    routeComments(route).forEach((item) => { current[item.k] = item.text; });
    if (text.trim()) current[k] = text.trim(); else delete current[k];
    state.comments[route.id] = current;
    updateComments();
    buildTimeline();
    sendComments();
  }

  // Every comment, sent to ui.py so that the file it writes holds them.
  function sendComments() {
    if (window.parent === window) return;
    const comments = {};
    scene.routes.forEach((route) => {
      const items = routeComments(route);
      if (items.length) {
        comments[route.id] = {};
        items.forEach((item) => { comments[route.id][String(item.k)] = item.text; });
      }
    });
    try { window.parent.postMessage({ type: "architeuthis:comments", comments }, "*"); } catch (error) { /* not embedded */ }
  }

  // ------------------------------------------------------------------
  // Weather at a point: cursor readout and picker
  // ------------------------------------------------------------------

  // The weather of the current source at a point, now: rows of label,
  // value and detail, or a message.
  function conditions(lat, lon) {
    const source = currentSource();
    if (!source) return { message: "No forecast in this file" };
    const t = state.t;
    lon = wrapLongitude(lon);
    if (!frameAt(source, t)) return { message: `No ${source.label} forecast at this time`, source };
    const q = source.quantities;
    const rows = [];
    // One row per layer of the file, with the direction of wind, waves and current.
    includedLayers(source).forEach((layer) => {
      const info = scene.layers[layer];
      if (layer === "wind") {
        const u = sampleAt(source, "wind_u", t, lat, lon), v = sampleAt(source, "wind_v", t, lat, lon);
        const speed = Math.hypot(u, v);
        if (speed === speed) rows.push({ label: "Wind", value: `${speed.toFixed(0)} kt`, detail: `from ${formatBearing((Math.atan2(-u, -v) * 180) / Math.PI)}` });
      } else if (layer === "waves") {
        const height = sampleAt(source, "swh", t, lat, lon);
        const x = q.wave_x ? sampleAt(source, "wave_x", t, lat, lon) : NaN, y = q.wave_y ? sampleAt(source, "wave_y", t, lat, lon) : NaN;
        if (height === height) rows.push({ label: "Waves", value: `${height.toFixed(1)} m`, detail: x === x && y === y ? `from ${formatBearing((Math.atan2(x, y) * 180) / Math.PI)}` : "" });
      } else if (layer === "current") {
        const u = sampleAt(source, "current_u", t, lat, lon), v = sampleAt(source, "current_v", t, lat, lon);
        const speed = Math.hypot(u, v);
        if (speed === speed) rows.push({ label: "Current", value: `${speed.toFixed(1)} kt`, detail: `to ${formatBearing((Math.atan2(u, v) * 180) / Math.PI)}` });
      } else {
        const value = layerValueAt(source, layer, t, lat, lon);
        if (value === value) rows.push({ label: info.label, value: formatLayerValue(info, value), detail: "" });
      }
    });
    if (!rows.length) return { message: `Outside the ${source.label} forecast`, source };
    return { rows, source };
  }

  function updateReadout() {
    const readout = $("readout");
    const pointer = state.pointer;
    // A route tooltip already tells the conditions there.
    if (!pointer || state.popup || state.editing) { readout.hidden = true; return; }
    const items = [`<span class="position">${formatPosition(pointer.lat, pointer.lng)}</span>`];
    const found = conditions(pointer.lat, pointer.lng);
    if (found.rows) {
      found.rows.forEach((row) => items.push(`<span class="item">${escapeHtml(row.label)} <b>${escapeHtml(row.value)}</b>${row.detail ? " " + escapeHtml(row.detail) : ""}</span>`));
      if (includedSources().length > 1) items.push(`<span class="muted">${escapeHtml(found.source.label)}</span>`);
    } else {
      items.push(`<span class="muted">${escapeHtml(found.message)}</span>`);
    }
    readout.innerHTML = items.join("");
    readout.hidden = false;
  }

  let pickerMarker = null;
  let pickerShown = false;

  // The picker: a dot to drag anywhere, with a line up to the left side of
  // a card telling the weather there as the time changes. Clicking the map
  // moves it there.
  function setPicker(position) {
    state.picker = position ? { lat: Math.max(-85, Math.min(85, position.lat)), lon: wrapLongitude(position.lon) } : null;
    const button = document.querySelector(".picker-control");
    if (button) button.classList.toggle("active", !!state.picker);
    if (!map) return;
    if (!state.picker) {
      if (pickerMarker && pickerShown) pickerMarker.remove();
      pickerShown = false;
      persist();
      return;
    }
    if (!pickerMarker) {
      const node = element("div", "picker");
      node.innerHTML = '<div class="picker-dot"></div><div class="picker-card"></div>';
      pickerMarker = new maplibregl.Marker({ element: node, draggable: true, anchor: "center" });
      pickerMarker.on("drag", () => {
        const point = pickerMarker.getLngLat();
        state.picker = { lat: point.lat, lon: wrapLongitude(point.lng) };
        updatePicker();
      });
      pickerMarker.on("dragend", persist);
      node.addEventListener("click", (event) => {
        if (event.target.closest(".picker-close")) { event.stopPropagation(); setPicker(null); }
      });
    }
    pickerMarker.setLngLat([state.picker.lon, state.picker.lat]);
    if (!pickerShown) { pickerMarker.addTo(map); pickerShown = true; }
    updatePicker();
    persist();
  }

  function togglePicker() {
    if (state.picker) { setPicker(null); return; }
    const center = map.getCenter();
    setPicker({ lat: center.lat, lon: center.lng });
  }

  function updatePicker() {
    if (!pickerMarker || !state.picker) return;
    const card = pickerMarker.getElement().querySelector(".picker-card");
    const found = conditions(state.picker.lat, state.picker.lon);
    const rows = found.rows
      ? found.rows.map((row) => `<tr><td>${escapeHtml(row.label)}</td><td><b>${escapeHtml(row.value)}</b></td><td>${escapeHtml(row.detail)}</td></tr>`).join("")
      : `<tr><td colspan="3" class="muted">${escapeHtml(found.message)}</td></tr>`;
    card.innerHTML =
      `<div class="picker-head"><span>${escapeHtml(formatPosition(state.picker.lat, state.picker.lon))}</span>` +
      `<button class="picker-close" type="button" title="Remove the picker">${icon("close")}</button></div>` +
      `<table>${rows}</table>` +
      `<div class="picker-foot">${escapeHtml(found.source ? found.source.label + " · " : "")}${escapeHtml(formatShort(state.t))}</div>`;
  }

  // --------------------------------------------------------------------
  // Panel
  // --------------------------------------------------------------------

  function element(tag, className, html) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (html !== undefined) node.innerHTML = html;
    return node;
  }

  function section(title, links) {
    const node = element("section", "section");
    const heading = element("h2", "", `<span>${escapeHtml(title)}</span>`);
    if (links) {
      const span = element("span", "links");
      links.forEach(([text, action]) => {
        const button = element("button", "", escapeHtml(text));
        button.type = "button";
        button.addEventListener("click", action);
        span.append(button);
      });
      heading.append(span);
    }
    node.append(heading);
    return node;
  }

  function segmented(options, value, onChange) {
    const group = element("div", "seg");
    group.setAttribute("role", "radiogroup");
    options.forEach(([key, label]) => {
      const button = element("button", key === value ? "active" : "", escapeHtml(label));
      button.type = "button";
      button.setAttribute("role", "radio");
      button.setAttribute("aria-checked", key === value ? "true" : "false");
      button.addEventListener("click", () => onChange(key));
      group.append(button);
    });
    return group;
  }

  function checkbox(label, checked, onChange, options) {
    const settings = options || {};
    const node = element("label", "check" + (settings.disabled ? " disabled" : ""));
    const input = element("input");
    input.type = "checkbox";
    input.checked = !!checked;
    input.disabled = !!settings.disabled;
    input.addEventListener("change", () => onChange(input.checked));
    node.append(input);
    if (settings.color) {
      const swatch = element("span", "swatch" + (settings.line ? " line" : ""));
      swatch.style.background = settings.color;
      node.append(swatch);
    }
    node.append(element("span", "", escapeHtml(label)));
    return node;
  }

  function buildPanel() {
    const panel = $("panel");
    panel.innerHTML = "";
    const source = currentSource();

    if (source) {
      const weather = section("Weather");
      const sources = includedSources();
      if (sources.length > 1) {
        weather.append(segmented(sources.map((s) => [s.id, s.label]), source.id, (id) => {
          state.source = id;
          state.layer = null;
          ensureSelection();
          onFieldsChanged();
        }));
      }
      const layers = includedLayers(source).map((layer) => [layer, scene.layers[layer].label]).concat([["", "Off"]]);
      weather.append(segmented(layers, state.layer || "", (layer) => { state.layer = layer; state.arrowKind = null; onFieldsChanged(); }));
      const kinds = availableArrows(source);
      if (kinds.length) {
        weather.append(element("div", "seg-label", "Arrows"));
        const arrows = kinds.map((kind) => [kind, ARROW_LABELS[kind]]).concat([["", "Off"]]);
        weather.append(segmented(arrows, currentArrows(source) || "", (kind) => { state.arrowKind = kind; onFieldsChanged(); }));
      }
      if (source.quantities.pressure && includedLayers(source).includes("pressure")) {
        weather.append(checkbox("Isobars, every 4 hPa", state.isobars, (on) => { state.isobars = on; onFieldsChanged(); }));
        const labels = checkbox("Pressure labels", state.isobarLabels, (on) => { state.isobarLabels = on; onFieldsChanged(); }, { disabled: !state.isobars });
        labels.classList.add("sub");
        weather.append(labels);
      }
      const range = element("label", "range", "<span>Opacity</span>");
      const slider = element("input");
      slider.type = "range";
      slider.min = "0.1";
      slider.max = "1";
      slider.step = "0.05";
      slider.value = String(state.opacity);
      slider.addEventListener("input", () => {
        state.opacity = Number(slider.value);
        map.setPaintProperty("field", "raster-opacity", state.opacity);
        persist();
      });
      range.append(slider);
      weather.append(range);
      panel.append(weather);
    }

    const routes = includedRoutes();
    const routeSection = section("Routes", routes.length ? [
      ["Zoom", fitRoutes],
      ["All", () => { routes.forEach((route) => { delete state.hidden[route.id]; }); onRoutesChanged(); }],
      ["None", () => { routes.forEach((route) => { state.hidden[route.id] = true; }); onRoutesChanged(); }],
    ] : null);
    if (!routes.length) routeSection.append(element("div", "empty", "No route"));
    routes.forEach((route) => {
      const off = !!state.hidden[route.id];
      const row = element("div", "route-row" + (off ? " off" : ""));
      const input = element("input");
      input.type = "checkbox";
      input.checked = !off;
      input.title = "Show this route";
      input.addEventListener("change", () => {
        if (input.checked) delete state.hidden[route.id]; else state.hidden[route.id] = true;
        onRoutesChanged();
      });
      const name = element("button", "route-name");
      name.type = "button";
      name.title = "Zoom to this route";
      const badges = [];
      if (route.summary.status === 2) badges.push('<span class="badge" title="The solver did not converge">not converged</span>');
      if (route.summary.max_z !== null && route.summary.max_z > 0) badges.push('<span class="badge" title="The route touches land or an exclusion zone">land or zone</span>');
      name.innerHTML = `<i class="swatch line" style="background:${route.color}"></i><span>${escapeHtml(routeLabel(route))}</span>${badges.join("")}`;
      name.addEventListener("click", () => zoomTo(route));
      const figures = [];
      if (route.summary.fuel !== null) figures.push(`${route.summary.fuel.toFixed(1)} t`);
      if (route.summary.distance !== null) figures.push(`${Math.round(route.summary.distance)} nm`);
      if (route.summary.sog !== null) figures.push(`${route.summary.sog.toFixed(1)} kt`);
      const details = element("div", "route-details", `${figures.join(" · ")}<br>${formatShort(route.etd)} → ${formatShort(route.eta)}`);
      row.append(input, name, details);
      const description = routeDescription(route);
      if (description) row.append(element("div", "route-description", escapeHtml(description)));
      routeSection.append(row);
    });
    panel.append(routeSection);

    if (scene.zones.length) {
      const zones = section("Exclusion zones");
      scene.zones.forEach((zone) => {
        const empty = zone.outline.length < 2;
        zones.append(checkbox(empty ? `${zone.label} (unavailable)` : zone.label, !empty && state.zones[zone.id], (on) => {
          state.zones[zone.id] = on;
          updateZones();
          persist();
        }, { color: zone.color, line: true, disabled: empty }));
      });
      panel.append(zones);
    }

    const base = section("Map");
    base.append(segmented([["offline", "Offline map"], ["osm", "OpenStreetMap"]], state.basemap, (value) => {
      state.basemap = value;
      updateBasemap();
      buildPanel();
      persist();
    }));
    base.append(checkbox("Sea marks (OpenSeaMap, online)", state.seamarks, (on) => { state.seamarks = on; updateBasemap(); persist(); }));
    base.append(checkbox("Latitude and longitude lines", state.graticule, (on) => { state.graticule = on; updateBasemap(); persist(); }));
    includedOverlays().forEach((overlay) => {
      const label = typeof overlay.time === "number" ? `${overlay.label}, ${formatShort(overlay.time)}` : overlay.label;
      base.append(checkbox(label, state.overlays[overlay.id], (on) => {
        state.overlays[overlay.id] = on;
        updateBasemap();
        buildTimeline();
        if (on) showChartTime(overlay);
        persist();
      }));
    });
    panel.append(base);
  }

  // A chart is drawn at its valid time: showing one brings the forecast,
  // the routes and the timeline to that time.
  function showChartTime(overlay) {
    if (typeof overlay.time !== "number") return;
    pause();
    setTime(overlay.time);
  }

  function zoomTo(route) {
    let bounds = null;
    route.lon.forEach((lon, i) => {
      const point = [lon, route.lat[i]];
      bounds = bounds ? bounds.extend(point) : new maplibregl.LngLatBounds(point, point);
    });
    if (state.hidden[route.id]) { delete state.hidden[route.id]; onRoutesChanged(); }
    const canvas = map.getCanvas();
    const pad = Math.min(80, canvas.clientWidth / 5, canvas.clientHeight / 5);
    map.fitBounds(bounds, { padding: { top: pad, bottom: Math.min($("timeline").offsetHeight + 40, canvas.clientHeight / 3), left: pad, right: pad }, duration: 600, maxZoom: 7 });
  }

  function setPanel(open) {
    state.panelOpen = open;
    $("panel").hidden = !open;
    $("panel-toggle").setAttribute("aria-expanded", open ? "true" : "false");
    document.body.classList.toggle("panel-open", open);
    persist();
  }

  // --------------------------------------------------------------------
  // Header
  // --------------------------------------------------------------------

  function updateHeader() {
    const title = state.title || scene.title;
    $("title").textContent = title;
    document.title = title;
    const count = includedRoutes().length;
    $("subtitle").textContent = `${count} route${count === 1 ? "" : "s"} · made ${formatDate(scene.created)}`;
    const note = state.note || "";
    $("note").textContent = note;
    $("note-toggle").hidden = !note;
    $("note").hidden = !note || !state.noteOpen;
    $("note-toggle").classList.toggle("active", !!note && state.noteOpen);
  }

  // --------------------------------------------------------------------
  // Timeline
  // --------------------------------------------------------------------

  function percent(t) { return (100 * (t - state.t0)) / (state.t1 - state.t0); }

  function buildTimeline() {
    const labels = $("tl-labels"), rows = $("tl-rows");
    labels.innerHTML = '<div class="tl-axis-spacer"></div>';
    rows.innerHTML = "";
    const addRow = (label, title, className) => {
      const name = element("div", "tl-label", escapeHtml(label));
      name.title = title || label;
      labels.append(name);
      const row = element("div", "tl-row" + (className ? " " + className : ""));
      rows.append(row);
      return row;
    };
    includedSources().forEach((source) => {
      const row = addRow(source.label, `${source.label} forecast: one mark per step`);
      if (!source.times.length) return;
      const span = element("div", "tl-span source");
      span.style.left = `${percent(source.times[0])}%`;
      span.style.width = `${percent(source.times[source.times.length - 1]) - percent(source.times[0])}%`;
      row.append(span);
      source.times.forEach((time) => {
        const mark = element("i", "tl-frame");
        mark.style.left = `${percent(time)}%`;
        row.append(mark);
      });
    });
    // Routes sharing a schedule share a lane, striped with their colours.
    const groups = [];
    includedRoutes().forEach((route) => {
      const start = route.tim[0], end = route.tim[route.tim.length - 1];
      let group = groups.find((item) => item.start === start && item.end === end);
      if (!group) groups.push((group = { start, end, routes: [] }));
      group.routes.push(route);
    });
    groups.forEach((group) => {
      const shown = group.routes.filter((route) => !state.hidden[route.id]);
      const label = group.routes.length === 1 ? routeLabel(group.routes[0]) : `${group.routes.length} routes`;
      const names = group.routes.map(routeLabel).join(", ");
      const row = addRow(label, `${names}: ${formatShort(group.start)} → ${formatShort(group.end)}`, shown.length ? "" : "off");
      const colors = (shown.length ? shown : group.routes).map((route) => route.color);
      const stripes = colors.map((color, i) => `${color} ${(100 * i) / colors.length}% ${(100 * (i + 1)) / colors.length}%`);
      const span = element("div", "tl-span" + (colors.length > 1 ? " group" : ""));
      span.style.left = `${percent(group.start)}%`;
      span.style.width = `${Math.max(0.3, percent(group.end) - percent(group.start))}%`;
      span.style.background = colors.length > 1 ? `linear-gradient(to bottom, ${stripes.join(", ")})` : colors[0];
      row.append(span);
      // A dot where the analyst commented the route.
      shown.forEach((route) => {
        routeComments(route).forEach((item) => {
          const mark = element("i", "tl-comment");
          mark.style.left = `${percent(route.ctim[item.k])}%`;
          mark.style.background = route.color;
          row.append(mark);
        });
      });
    });
    // Charts at their valid time: a click shows the chart and goes there.
    const charts = includedOverlays().filter((overlay) => typeof overlay.time === "number");
    if (charts.length) {
      const row = addRow(charts.length === 1 ? "Analysis" : "Analyses", "Valid time of the charts over the map");
      charts.forEach((overlay) => {
        const mark = element("i", "tl-chart");
        mark.style.left = `${percent(overlay.time)}%`;
        mark.title = `${overlay.label}, ${formatShort(overlay.time)}`;
        mark.dataset.overlay = overlay.id;
        mark.style.opacity = state.overlays[overlay.id] ? "1" : "0.45";
        row.append(mark);
      });
    }
    const now = Date.now() / 1000;
    const nowMark = rows.parentElement.querySelector(".tl-now");
    if (nowMark) nowMark.remove();
    if (now >= state.t0 && now <= state.t1) {
      const mark = element("div", "tl-now");
      mark.title = "Now";
      mark.style.left = `${percent(now)}%`;
      $("tl-lanes").append(mark);
    }
    $("tl-now").hidden = !(now >= state.t0 && now <= state.t1);
    buildAxis();
    updateCursor();
    updateTimelineHeight();
  }

  function buildAxis() {
    const axis = $("tl-axis");
    axis.innerHTML = "";
    const width = $("tl-lanes").clientWidth || 600;
    const days = (state.t1 - state.t0) / DAY;
    const perDay = width / Math.max(days, 1e-6);
    const minor = perDay > 160 ? 3 * HOUR : perDay > 48 ? 6 * HOUR : perDay > 20 ? 12 * HOUR : 0;
    const every = Math.max(1, Math.ceil(64 / perDay));
    if (minor) {
      for (let t = Math.ceil(state.t0 / minor) * minor; t <= state.t1; t += minor) {
        if (t % DAY === 0) continue;
        const tick = element("div", "tl-tick");
        tick.style.left = `${percent(t)}%`;
        axis.append(tick);
      }
    }
    let index = 0;
    for (let t = Math.ceil(state.t0 / DAY) * DAY; t <= state.t1; t += DAY, index++) {
      const tick = element("div", "tl-tick day");
      tick.style.left = `${percent(t)}%`;
      axis.append(tick);
      if (index % every === 0 && percent(t) < 96) {
        const date = new Date(t * 1000);
        const label = element("div", "tl-day" + (date.getUTCDay() % 6 === 0 ? " weekend" : ""), `${DAYS[date.getUTCDay()]} ${date.getUTCDate()}`);
        label.style.left = `${percent(t)}%`;
        axis.append(label);
      }
    }
  }

  function updateCursor() {
    $("tl-cursor").style.left = `${percent(state.t)}%`;
    const source = currentSource();
    const relative = formatRelative(state.t);
    let extra = relative === "now" ? "now" : relative;
    if (source && source.ready && !frameAt(source, state.t)) extra += ` · no ${source.label} forecast`;
    $("tl-time").innerHTML = `${escapeHtml(formatTime(state.t))}<span class="muted">${escapeHtml(extra)}</span>`;
  }

  function updateTimelineHeight() {
    document.documentElement.style.setProperty("--tl-height", `${$("timeline").offsetHeight}px`);
  }

  function timeFromEvent(event) {
    const box = $("tl-lanes").getBoundingClientRect();
    const fraction = Math.max(0, Math.min(1, (event.clientX - box.left) / box.width));
    return state.t0 + fraction * (state.t1 - state.t0);
  }

  function setupTimeline() {
    $("tl-prev").innerHTML = icon("prev");
    $("tl-next").innerHTML = icon("next");
    $("tl-speed").value = String(state.speed);
    updatePlayButton();
    $("tl-play").addEventListener("click", togglePlay);
    $("tl-prev").addEventListener("click", () => step(-1));
    $("tl-next").addEventListener("click", () => step(1));
    $("tl-now").addEventListener("click", () => setTime(Date.now() / 1000));
    $("tl-speed").addEventListener("change", () => { state.speed = Number($("tl-speed").value); persist(); });

    const lanes = $("tl-lanes");
    const hover = $("tl-hover");
    let dragging = false;
    lanes.addEventListener("pointerdown", (event) => {
      pause();
      // A chart's mark shows that chart at its time.
      const chart = event.target.closest && event.target.closest(".tl-chart");
      if (chart) {
        const overlay = includedOverlays().find((item) => item.id === chart.dataset.overlay);
        if (overlay) {
          state.overlays[overlay.id] = true;
          updateBasemap();
          buildPanel();
          buildTimeline();
          showChartTime(overlay);
          return;
        }
      }
      dragging = true;
      lanes.setPointerCapture(event.pointerId);
      setTime(Math.round(timeFromEvent(event) / 900) * 900);
    });
    lanes.addEventListener("pointermove", (event) => {
      const t = Math.round(timeFromEvent(event) / 900) * 900;
      hover.hidden = false;
      hover.style.left = `${percent(t)}%`;
      hover.textContent = formatShort(t);
      if (dragging) setTime(t);
    });
    const stop = () => { dragging = false; };
    lanes.addEventListener("pointerup", stop);
    lanes.addEventListener("pointercancel", stop);
    lanes.addEventListener("pointerleave", () => { hover.hidden = true; });

    if (window.ResizeObserver) {
      new ResizeObserver(() => { buildAxis(); updateTimelineHeight(); }).observe($("timeline"));
    }
  }

  function setTime(t) {
    state.t = Math.max(state.t0, Math.min(state.t1, t));
    scheduleRender(true);
    persist();
  }

  function step(direction) {
    const source = currentSource();
    const times = source ? source.times : [];
    let target = null;
    if (direction > 0) target = times.find((time) => time > state.t + 1);
    else for (let i = times.length - 1; i >= 0; i--) if (times[i] < state.t - 1) { target = times[i]; break; }
    if (target === null || target === undefined) target = state.t + direction * 3 * HOUR;
    pause();
    setTime(target);
  }

  let lastTick = null;
  function tick(timestamp) {
    if (!state.playing) return;
    if (lastTick !== null) {
      let t = state.t + ((timestamp - lastTick) / 1000) * state.speed * HOUR;
      if (t > state.t1) t = state.t0;
      state.t = t;
      scheduleRender(true);
    }
    lastTick = timestamp;
    requestAnimationFrame(tick);
  }

  function play() {
    if (state.playing) return;
    if (state.t >= state.t1) state.t = state.t0;
    state.playing = true;
    lastTick = null;
    updatePlayButton();
    requestAnimationFrame(tick);
  }

  function pause() {
    if (!state.playing) return;
    state.playing = false;
    updatePlayButton();
    persist();
  }

  function togglePlay() { if (state.playing) pause(); else play(); }

  function updatePlayButton() {
    const button = $("tl-play");
    button.innerHTML = icon(state.playing ? "pause" : "play");
    button.title = state.playing ? "Pause (space)" : "Play (space)";
  }

  // --------------------------------------------------------------------
  // Rendering
  // --------------------------------------------------------------------

  let renderPending = false;
  let fieldsPending = false;
  let lastFields = 0;
  let fieldsTimer = null;

  function scheduleRender(fields) {
    if (fields) fieldsPending = true;
    if (renderPending) return;
    renderPending = true;
    requestAnimationFrame(render);
    // Background tabs pause animation frames: the timer still draws.
    setTimeout(render, 150);
  }

  function render() {
    if (!renderPending) return;
    renderPending = false;
    if (!state.ready) return;
    updateCursor();
    updateBoats();
    showPopup();
    updateReadout();
    updatePicker();
    if (fieldsPending) {
      const wait = (state.playing ? 100 : 40) - (performance.now() - lastFields);
      clearTimeout(fieldsTimer);
      if (wait <= 0) drawFields();
      else fieldsTimer = setTimeout(drawFields, wait);
    }
  }

  function drawFields() {
    fieldsPending = false;
    lastFields = performance.now();
    renderField();
    updateArrows();
    updateIsobars();
    updatePicker();
  }

  function onFieldsChanged() {
    ensureSelection();
    buildPanel();
    buildTimeline();
    scheduleRender(true);
    persist();
  }

  function onRoutesChanged() {
    buildPanel();
    buildTimeline();
    updateRoutes();
    showPopup();
    persist();
  }

  function refresh() {
    computeRange();
    state.t = Math.max(state.t0, Math.min(state.t1, state.t));
    ensureSelection();
    updateHeader();
    buildPanel();
    buildTimeline();
    if (!state.ready) return;
    updateRoutes();
    updateZones();
    updateBasemap();
    scheduleRender(true);
  }

  // Selection sent by ui.py, the analyst's preview of this page: what the
  // file will hold, the theme, and the analyst's route names, descriptions
  // and comments, which the preview lets them edit.
  function applySettings(settings) {
    const before = includedOverlays();
    ["routes", "sources", "overlays", "hover", "fields"].forEach((key) => { if (key in settings) state.settings[key] = settings[key]; });
    if ("title" in settings) state.title = settings.title || scene.title;
    if ("note" in settings) state.note = settings.note || "";
    if ("editable" in settings) state.editable = !!settings.editable;
    if (settings.labels) state.labels = Object.assign({}, settings.labels);
    if (settings.descriptions) state.descriptions = Object.assign({}, settings.descriptions);
    if (settings.comments) state.comments = JSON.parse(JSON.stringify(settings.comments));
    if (settings.theme === "light" || settings.theme === "dark") applyTheme(settings.theme);
    refresh();
    // A chart the analyst has just added is shown at its time.
    const added = includedOverlays().find((overlay) => !before.includes(overlay) && state.overlays[overlay.id] && typeof overlay.time === "number");
    if (added) showChartTime(added);
  }

  // --------------------------------------------------------------------
  // Theme
  // --------------------------------------------------------------------

  function applyTheme(theme) {
    state.theme = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = state.theme;
    const button = $("theme-toggle");
    button.innerHTML = icon(state.theme === "light" ? "moon" : "sun");
    button.title = state.theme === "light" ? "Dark map (T)" : "Light map (T)";
    if (map && map.getLayer("sea")) {
      const colors = THEMES[state.theme];
      map.setPaintProperty("sea", "background-color", colors.sea);
      map.setPaintProperty("land", "fill-color", colors.land);
      map.setPaintProperty("graticule", "line-color", colors.graticule);
      map.setPaintProperty("isobars", "line-color", colors.isobar);
      COAST_LAYERS.forEach(([id]) => {
        map.setPaintProperty(id, "line-color", colors.coast);
        if (id !== "coast") map.setPaintProperty(id, "line-opacity", colors.coastShade);
      });
      // Glyphs take the lightness of the theme: they are drawn again.
      if (state.ready) updateArrows();
    }
    persist();
  }

  function toggleTheme() {
    applyTheme(state.theme === "light" ? "dark" : "light");
    // ui.py keeps its own switch in step with the preview.
    if (window.parent !== window) {
      try { window.parent.postMessage({ type: "architeuthis:theme", theme: state.theme }, "*"); } catch (error) { /* not embedded */ }
    }
  }

  // --------------------------------------------------------------------
  // Map
  // --------------------------------------------------------------------

  function landData() {
    const quantum = scene.land.quantum;
    return {
      type: "FeatureCollection",
      features: scene.land.polygons.map((rings) => ({
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: rings.map((ring) => {
            const points = [];
            let x = 0, y = 0;
            for (let i = 0; i < ring.length; i += 2) {
              x += ring[i];
              y += ring[i + 1];
              points.push([x * quantum, y * quantum]);
            }
            return points;
          }),
        },
      })),
    };
  }

  // Signed area of a ring, positive when it turns anticlockwise.
  function ringArea(points) {
    let area = 0;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      area += points[j][0] * points[i][1] - points[i][0] * points[j][1];
    }
    return area / 2;
  }

  // Edges that are not coast: the cuts along the antimeridian and the
  // southern edge of Antarctica.
  function artificialEdge(a, b) {
    return (Math.abs(a[0]) >= 179.99 && Math.abs(b[0]) >= 179.99) || (a[1] <= -84.9 && b[1] <= -84.9);
  }

  // The coastline as lines with the sea on their right: outer rings turn
  // anticlockwise and holes clockwise, so that a positive offset goes
  // towards the sea, cut where the rings follow no coast.
  function coastData(land) {
    const lines = [];
    land.features.forEach((feature) => {
      feature.geometry.coordinates.forEach((ring, index) => {
        let points = ring.slice();
        if (points.length > 1 && points[0][0] === points[points.length - 1][0] && points[0][1] === points[points.length - 1][1]) points.pop();
        if (points.length < 2) return;
        if ((ringArea(points) > 0) !== (index === 0)) points.reverse();
        // Start on a cut, if any, so that no line goes across it.
        const cut = points.findIndex((point, i) => artificialEdge(point, points[(i + 1) % points.length]));
        const closed = cut < 0;
        if (!closed) points = points.slice(cut + 1).concat(points.slice(0, cut + 1));
        let line = [points[0]];
        for (let i = 1; i <= points.length; i++) {
          if (i === points.length && !closed) break;
          const point = points[i % points.length];
          if (artificialEdge(line[line.length - 1], point)) {
            if (line.length > 1) lines.push(line);
            line = [point];
          } else {
            line.push(point);
          }
        }
        if (line.length > 1) lines.push(line);
      });
    });
    return { type: "Feature", properties: {}, geometry: { type: "MultiLineString", coordinates: lines } };
  }

  function graticuleData() {
    const lines = [];
    for (let lon = -180; lon < 180; lon += 10) {
      const line = [];
      for (let lat = -80; lat <= 80; lat += 5) line.push([lon, lat]);
      lines.push(line);
    }
    for (let lat = -80; lat <= 80; lat += 10) {
      const line = [];
      for (let lon = -180; lon <= 180; lon += 5) line.push([lon, lat]);
      lines.push(line);
    }
    return { type: "Feature", properties: {}, geometry: { type: "MultiLineString", coordinates: lines } };
  }

  function blankImage() {
    const canvas = document.createElement("canvas");
    canvas.width = 2;
    canvas.height = 2;
    return canvas.toDataURL();
  }

  // A width in pixels at zoom 5, narrower on the whole globe, wider close up.
  function zoomed(width) {
    return ["interpolate", ["linear"], ["zoom"], 1, width * 0.4, 5, width, 9, width * 1.4];
  }

  function mapStyle() {
    const geojson = (data) => ({ type: "geojson", data: data || EMPTY });
    const blank = blankImage();
    const theme = THEMES[state.theme];
    const land = landData();
    const sources = {
      land: geojson(land),
      coast: geojson(coastData(land)),
      graticule: geojson(graticuleData()),
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        maxzoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
      seamarks: {
        type: "raster",
        tiles: ["https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"],
        tileSize: 256,
        maxzoom: 18,
        attribution: '© <a href="https://www.openseamap.org">OpenSeaMap</a> contributors',
      },
      field: { type: "image", url: blank, coordinates: [[-1, 1], [1, 1], [1, -1], [-1, -1]] },
      isobars: geojson(),
      arrows: geojson(),
      zones: geojson(),
      routes: geojson(),
      "route-points": geojson(),
      comments: geojson(),
      boats: geojson(),
    };
    scene.overlays.forEach((overlay) => {
      sources[`overlay-${overlay.id}`] = {
        type: "image",
        url: overlay.url,
        coordinates: [[overlay.west, overlay.north], [overlay.east, overlay.north], [overlay.east, overlay.south], [overlay.west, overlay.south]],
      };
    });
    const hidden = { visibility: "none" };
    const round = { "line-join": "round", "line-cap": "round" };
    // Land is flat and covers the weather and the coast shade, which then
    // shows on the sea side only, even where the offset lines cross a cape.
    const layers = [
      { id: "sea", type: "background", paint: { "background-color": theme.sea } },
      { id: "osm", type: "raster", source: "osm", layout: hidden },
      { id: "field", type: "raster", source: "field", layout: hidden, paint: { "raster-opacity": state.opacity, "raster-fade-duration": 0, "raster-resampling": "linear" } },
    ];
    const line = (id, width, opacity, offset) => ({
      id,
      type: "line",
      source: "coast",
      layout: round,
      paint: { "line-color": theme.coast, "line-width": zoomed(width), "line-opacity": opacity, "line-offset": zoomed(offset) },
    });
    COAST_LAYERS.forEach(([id, width]) => { if (id !== "coast") layers.push(line(id, width, theme.coastShade, width / 2)); });
    layers.push(
      { id: "land", type: "fill", source: "land", paint: { "fill-color": theme.land } },
      line("coast", 1.2, 1, 0)
    );
    layers.push(
      { id: "graticule", type: "line", source: "graticule", paint: { "line-color": theme.graticule, "line-width": 0.6 } },
      { id: "seamarks", type: "raster", source: "seamarks", layout: hidden }
    );
    scene.overlays.forEach((overlay) => {
      layers.push({ id: `overlay-${overlay.id}`, type: "raster", source: `overlay-${overlay.id}`, layout: hidden, paint: { "raster-opacity": overlay.opacity, "raster-fade-duration": 0 } });
    });
    layers.push(
      { id: "isobars", type: "line", source: "isobars", paint: { "line-color": theme.isobar, "line-width": 0.9, "line-opacity": 0.7 } },
      {
        id: "arrows",
        type: "symbol",
        source: "arrows",
        layout: {
          "icon-image": ["get", "icon"],
          "icon-rotate": ["get", "rotate"],
          "icon-size": ["get", "size"],
          "icon-rotation-alignment": "map",
          "icon-pitch-alignment": "map",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
      },
      { id: "zones", type: "line", source: "zones", paint: { "line-color": ["get", "color"], "line-width": 2, "line-dasharray": [3, 2] } },
      // Routes alone have an outline: thin, white and sharp.
      { id: "route-casing", type: "line", source: "routes", layout: round, paint: { "line-color": "#ffffff", "line-width": 4.4 } },
      { id: "route-line", type: "line", source: "routes", layout: round, paint: { "line-color": ["get", "color"], "line-width": 2.6 } },
      {
        id: "route-points",
        type: "circle",
        source: "route-points",
        paint: {
          "circle-color": ["get", "color"],
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 0.8, 5, 2, 8, 3.5],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 4, 0, 6, 0.9],
        },
      },
      { id: "route-hit", type: "circle", source: "route-points", paint: { "circle-radius": 9, "circle-opacity": 0 } },
      {
        id: "comments",
        type: "symbol",
        source: "comments",
        layout: {
          "icon-image": ["get", "icon"],
          "icon-anchor": "bottom-left",
          "icon-offset": [-2, 2],
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
      },
      {
        id: "boats",
        type: "symbol",
        source: "boats",
        layout: {
          "icon-image": ["get", "icon"],
          "icon-rotate": ["get", "rotate"],
          "icon-rotation-alignment": "map",
          "icon-pitch-alignment": "map",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
          "icon-size": 0.9,
        },
        paint: { "icon-opacity": ["get", "opacity"] },
      }
    );
    return { version: 8, projection: { type: "globe" }, sources, layers };
  }

  let map = null;

  function fail(message) {
    $("loading").hidden = true;
    $("error").textContent = message;
    $("error").hidden = false;
  }

  function start() {
    if (typeof maplibregl === "undefined") {
      fail("The map library could not be loaded. This file loads it from the internet: open it with a connection, or ask for a file that includes it.");
      return;
    }

    computeRange();
    ensureSelection();
    state.t = initialTime();
    $("panel-toggle").innerHTML = icon("layers");
    $("panel-toggle").addEventListener("click", () => setPanel(!state.panelOpen));
    $("note-toggle").addEventListener("click", () => { state.noteOpen = !state.noteOpen; updateHeader(); persist(); });
    $("theme-toggle").addEventListener("click", toggleTheme);
    applyTheme(state.theme);
    setPanel(state.panelOpen);
    updateHeader();
    setupTimeline();
    buildPanel();
    buildTimeline();

    const view = stored && stored.view;
    try {
      map = new maplibregl.Map({
        container: "map",
        style: mapStyle(),
        center: view ? view.center : [-30, 45],
        zoom: view ? view.zoom : 2.2,
        bearing: view ? view.bearing : 0,
        attributionControl: false,
        keyboard: false,
        maxPitch: 0,
      });
    } catch (error) {
      fail(`The map cannot be drawn in this browser (${error.message}). A browser with WebGL is needed.`);
      return;
    }
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    if (maplibregl.GlobeControl) map.addControl(new maplibregl.GlobeControl(), "top-right");
    map.addControl({
      onAdd() {
        this.box = element("div", "maplibregl-ctrl maplibregl-ctrl-group");
        const button = element("button", "picker-control" + (state.picker ? " active" : ""), icon("picker"));
        button.type = "button";
        button.title = "Weather at a point: drag the pin, or click the map (P)";
        button.setAttribute("aria-label", "Weather at a point");
        button.addEventListener("click", togglePicker);
        this.box.append(button);
        return this.box;
      },
      onRemove() { this.box.remove(); },
    }, "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "nautical", maxWidth: 120 }), "bottom-left");
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: scene.credits ? `Forecasts: ${escapeHtml(scene.credits)}` : undefined }), "bottom-right");

    map.on("load", () => {
      state.ready = true;
      updateRoutes();
      updateZones();
      updateBasemap();
      if (state.picker) setPicker(state.picker);
      if (!view) fitRoutes();
      decodeSources()
        .then(() => {
          $("loading").hidden = true;
          buildTimeline();
          scheduleRender(true);
        })
        .catch((error) => fail(`The forecast could not be read: ${error && error.message ? error.message : error}`));
      if (!scene.sources.length) $("loading").hidden = true;
      scheduleRender(true);
    });
    map.on("mousemove", onPointer);
    map.on("click", onClick);
    map.on("mouseout", () => { state.pointer = null; state.popup = null; showPopup(); updateReadout(); });
    map.on("moveend", () => { if (state.ready) { updateArrows(); persist(); } });

    document.addEventListener("keydown", (event) => {
      if (event.target.closest && event.target.closest("input, select, textarea")) return;
      if (event.key === " ") { togglePlay(); event.preventDefault(); }
      else if (event.key === "ArrowRight") { if (event.shiftKey) setTime(state.t + DAY); else step(1); event.preventDefault(); }
      else if (event.key === "ArrowLeft") { if (event.shiftKey) setTime(state.t - DAY); else step(-1); event.preventDefault(); }
      else if (event.key === "l" || event.key === "L") setPanel(!state.panelOpen);
      else if (event.key === "p" || event.key === "P") togglePicker();
      else if (event.key === "t" || event.key === "T") toggleTheme();
      else if (event.key === "Escape") { state.popup = null; showPopup(); closeEditor(); if (window.innerWidth <= 720) setPanel(false); }
    });

    // For the browser console and automated checks.
    window.architeuthisViewer = { map, state, scene, setTime, applySettings, applyTheme, setPicker };

    window.addEventListener("message", (event) => {
      const data = event.data;
      if (data && data.type === "architeuthis:settings" && data.settings) applySettings(data.settings);
    });
    if (window.parent !== window) {
      try { window.parent.postMessage({ type: "architeuthis:ready" }, "*"); } catch (error) { /* not embedded */ }
    }
  }

  start();
})();
