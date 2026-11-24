/*
 * Architeuthis share viewer.
 *
 * Draws the scene embedded in the page (routes, forecast frames, exclusion
 * zones, land) on a MapLibre globe, with a layers panel, a timeline and
 * tooltips. Nothing is fetched except optional online map tiles, so the
 * page works offline. ui.py previews the same page in a frame and sends the
 * analyst's selection with postMessage ("architeuthis:settings"); in that
 * preview the analyst comments points of the routes, sent back to ui.py
 * ("architeuthis:comments"), with the zones ticked ("architeuthis:zones").
 */
(function () {
  "use strict";

  const scene = JSON.parse(document.getElementById("architeuthis-scene").textContent);
  const $ = (id) => document.getElementById(id);

  // The points of a route sit halfway along the great circle between its
  // nodes, on the line drawn, rather than halfway in latitude and longitude
  // as the reports place them: a few hundred metres apart at most.
  scene.routes.forEach((route) => {
    for (let k = 0; k < route.clat.length && k + 1 < route.lat.length; k++) {
      [route.clat[k], route.clon[k]] = greatCircle(route.lat[k], route.lon[k], route.lat[k + 1], route.lon[k + 1], 0.5);
    }
  });

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
  // OpenStreetMap as a basemap, offered again when this is true.
  const OSM_ENABLED = false;
  // OpenSeaMap draws its sea marks from zoom 9: further out, its tiles of
  // zoom 9 are shown smaller, by these map zooms and tile sizes, so that
  // traffic separation schemes and restricted areas show from further away.
  const SEAMARK_ZOOM = 9;
  const SEAMARK_LEVELS = [[SEAMARK_ZOOM, 256], [SEAMARK_ZOOM - 1, 128], [SEAMARK_ZOOM - 2, 64]];
  // Valid time of a chart, in the window the timeline covers around it.
  const OVERLAY_MARGIN = 6 * HOUR;
  // Size of the points of the routes, 1 for the radius of the first pages:
  // it scales their radius and their white outline at every zoom.
  const ROUTE_POINT_SCALE = 1.3;
  // Spacings of the isobars offered in the layers, in hPa, and the first.
  const ISOBAR_STEPS = [2, 4];
  const DEFAULT_ISOBAR_STEP = 4;
  // Highs and lows: the lowest or highest pressure within this many degrees
  // of latitude around, at least CENTRE_DEPTH hPa below or above the mean
  // pressure on the edge of that disc, so that a dent of an isobar is not
  // taken for a system.
  const CENTRE_RADIUS = 6;
  const CENTRE_DEPTH = 1.5;
  // Between two frames, a centre is the same system as the nearest one of its
  // kind in the next frame if that one is within the way a system moving at
  // CENTRE_SPEED knots goes in the time between them, and at least
  // CENTRE_REACH degrees of latitude. Others fade out or in.
  const CENTRE_SPEED = 60;
  const CENTRE_REACH = 3;

  // Map colours of each theme. The weather is drawn the same in both: arrows
  // and barbs take the colour of the field under them, made vivid with
  // GLYPH_LIGHTNESS, and isobars are ISOBAR_COLOR.
  const GLYPH_SATURATION = 1;
  const GLYPH_LIGHTNESS = 0.7;
  const ISOBAR_COLOR = "#f2f4f6";
  const COAST_OPACITY = 0.22;
  const THEMES = {
    dark: {
      sea: "#26292d",
      land: "#3c4045",
      coast: "#000000",
      coastShade: 0.08,
      graticule: "rgba(255,255,255,0.24)",
    },
    light: {
      sea: "#c9ced3",
      land: "#f7f7f5",
      coast: "#000000",
      coastShade: 0.045,
      graticule: "rgba(0,0,0,0.26)",
    },
  };
  const GRATICULE_WIDTH = 0.8;

  // The coastline: a thin line, shaded on the sea side by lines of growing
  // width offset towards the sea, which overlap most along the coast. Each
  // entry is a layer id and its width at zoom 5, in pixels.
  const COAST_SHADES = 8;
  const COAST_SHADE_WIDTH = 10;
  const COAST_LAYERS = Array.from({ length: COAST_SHADES }, (_, i) => [`coast-shade-${i + 1}`, (COAST_SHADE_WIDTH * (i + 1)) / COAST_SHADES])
    .concat([["coast", 0.5]]);
  // The land and its coast are drawn from two levels of the file: the whole
  // globe from the coarse one, and from DETAIL_ZOOM the finer one, read once
  // the page is shown so that it never delays it. Each layer has a twin of
  // the finer level, its id ending with "-detail".
  const DETAIL_ZOOM = 5;
  const LAND_LAYERS = ["land"].concat(COAST_LAYERS.map(([id]) => id));
  const DETAIL = "-detail";

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
    plots: "M3.5 18.49 9.5 12.48l4 4L22 6.92l-1.41-1.41-7.09 7.97-4-4L2 16.99z",
    print: "M19 8H5c-1.66 0-3 1.34-3 3v6h4v4h12v-4h4v-6c0-1.66-1.34-3-3-3zm-3 11H8v-5h8v5zm3-7c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1zm-1-9H6v4h12V3z",
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
    isobarStep: DEFAULT_ISOBAR_STEP,
    centres: true,
    opacity: 1,
    basemap: "offline",
    seamarks: false,
    graticule: true,
    hidden: {},
    zones: {},
    overlays: {},
    panelOpen: window.innerWidth > 720,
    // The plots of a route beside the map, and the route they show (the
    // first shown when null).
    plotsOpen: window.innerWidth > 1100 && scene.routes.length > 0,
    plotRoute: null,
    // Widths of the left panel and of the plots dragged by the user, in
    // pixels, or null for those of the stylesheet.
    panelWidth: null,
    plotsWidth: null,
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
    ["speed", "source", "layer", "arrowKind", "isobars", "isobarLabels", "isobarStep", "centres", "opacity", "basemap", "seamarks", "graticule", "panelOpen", "plotsOpen", "plotRoute", "panelWidth", "plotsWidth", "noteOpen", "theme", "picker"]
      .forEach((key) => { if (key in stored) state[key] = stored[key]; });
    ["hidden", "zones", "overlays"].forEach((key) => { Object.assign(state[key], stored[key] || {}); });
  }
  if (!OSM_ENABLED) state.basemap = "offline";
  if (!ISOBAR_STEPS.includes(state.isobarStep)) state.isobarStep = DEFAULT_ISOBAR_STEP;

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
          isobars: state.isobars, isobarLabels: state.isobarLabels, isobarStep: state.isobarStep, centres: state.centres, opacity: state.opacity, basemap: state.basemap,
          seamarks: state.seamarks, graticule: state.graticule, hidden: state.hidden, zones: state.zones,
          overlays: state.overlays, panelOpen: state.panelOpen, plotsOpen: state.plotsOpen, plotRoute: state.plotRoute,
          panelWidth: state.panelWidth, plotsWidth: state.plotsWidth,
          noteOpen: state.noteOpen, theme: state.theme,
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

  // The precipitation over a layer of clouds at a point, as text, or "".
  function rainText(source, layer, t, lat, lon) {
    const rain = scene.layers[layer] && scene.layers[layer].rain;
    if (!rain) return "";
    const amount = sampleAt(source, rain.quantity, t, lat, lon) * rain.hours;
    return amount >= rain.floor ? `${amount.toFixed(1)} ${rain.unit}` : "";
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

  // The colours of the precipitation over a layer of clouds, every 0.1 mm
  // from 0 to its last step, interpolated between the steps of its scale.
  function rainTable(layer) {
    const key = `${layer}:rain`;
    if (lookupTables[key]) return lookupTables[key];
    const stops = scene.layers[layer].rain.stops.map(([value, hex]) => [value, parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)]);
    const count = Math.round(stops[stops.length - 1][0] * 10) + 1;
    const table = new Uint8Array(3 * count);
    for (let k = 0, s = 0; k < count; k++) {
      const value = k / 10;
      while (s < stops.length - 2 && value > stops[s + 1][0]) s++;
      const [v0, ...c0] = stops[s], [v1, ...c1] = stops[s + 1];
      const f = Math.max(0, Math.min(1, (value - v0) / (v1 - v0)));
      for (let c = 0; c < 3; c++) table[3 * k + c] = Math.round(c0[c] + f * (c1[c] - c0[c]));
    }
    return (lookupTables[key] = table);
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
        // Clouds: the precipitation over the cover, as on Windy.
        const rain = scene.layers[layer].rain;
        const rainValues = rain ? grid(source, rain.quantity, state.t) : null;
        const rainColours = rainValues ? rainTable(layer) : null;
        const rainLast = rainColours ? rainColours.length / 3 - 1 : 0;
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
            if (rainValues) {
              const amount = bilinear(rainValues, source.grid, geometry.columns[c], y) * rain.hours;
              if (amount >= rain.floor) {
                const at = 3 * Math.min(rainLast, Math.round(amount * 10));
                const a = 0.9 * smoothstep(rain.floor, rain.floor + 1, amount);
                pixels[p] += a * (rainColours[at] - pixels[p]);
                pixels[p + 1] += a * (rainColours[at + 1] - pixels[p + 1]);
                pixels[p + 2] += a * (rainColours[at + 2] - pixels[p + 2]);
              }
            }
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
    const unit = [info.unit, info.rain ? info.rain.unit : "", source ? source.label : ""].filter(Boolean).join(" · ");
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
      if (info.rain) {
        scale += `<div class="steps" title="Precipitation in ${escapeHtml(info.rain.unit)}">` +
          info.rain.stops.slice(1).map(([value, color]) => `<span style="--step:${color}">${value}</span>`).join("") + "</div>";
      }
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
    '<span><svg viewBox="0 0 14 14"><path d="M3 9.5 7 4.5l4 5" fill="none" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>1 m</span>' +
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
  // GLYPH_LIGHTNESS, so that they stand out from the field in its own
  // colours, whatever the theme.
  const glyphColors = {};
  function glyphColor(layer, value) {
    const table = lookupTable(layer);
    const index = colourIndex(layer)(value);
    const key = `${layer}-${index}`;
    if (!(key in glyphColors)) {
      // A value without colour, such as no precipitation, gives a grey.
      const [h, s, l] = index < 0 ? [0, 0, 0.6] : hsl(table[3 * index], table[3 * index + 1], table[3 * index + 2]);
      // Greys stay grey, as saturating them would give them a hue they do not
      // have, and stand out by their lightness instead.
      const grey = s < 0.08;
      const saturation = grey ? s : Math.max(s, GLYPH_SATURATION);
      const lightness = grey ? (l > 0.5 ? 0.2 : 0.88) : GLYPH_LIGHTNESS;
      glyphColors[key] = { key: `${layer}${index}`, css: `hsl(${h.toFixed(0)}, ${Math.round(100 * saturation)}%, ${Math.round(100 * lightness)}%)` };
    }
    return glyphColors[key];
  }

  // A wind barb pointing north, feathers on the right in the northern
  // hemisphere and on the left in the southern one, in one flat colour.
  function ensureBarb(knots, south, color) {
    const id = `barb-${south ? "s" : "n"}-${knots}-${color.key}`;
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
    const id = `wave-${metres}-${color.key}`;
    return ensureImage(id, 96, (context) => {
      // A thin stroke looks bigger than a solid shape of the same size, so
      // chevrons are drawn inside the outline of a head, and the first one
      // touches the base of the last head.
      const x = 48, HALF = 12, HEAD = 15, HEAD_STEP = 9;
      const LINE = 2.6, CHEVRON_HALF = 9, CHEVRON = 10, CHEVRON_STEP = 6.5;
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
      if (chevrons) length += LINE + CHEVRON + (chevrons - 1) * CHEVRON_STEP;
      let y = 48 - length / 2;
      for (let i = 0; i < heads; i++) {
        context.beginPath();
        context.moveTo(x, y);
        context.lineTo(x + HALF, y + HEAD);
        context.lineTo(x - HALF, y + HEAD);
        context.closePath();
        context.fill();
        y += i < heads - 1 ? HEAD_STEP : HEAD;
      }
      // The tip of a chevron, half a line below y, so that its stroke starts at y.
      y += LINE / 2;
      context.lineWidth = LINE;
      for (let i = 0; i < chevrons; i++) {
        context.beginPath();
        context.moveTo(x - CHEVRON_HALF, y + CHEVRON);
        context.lineTo(x, y);
        context.lineTo(x + CHEVRON_HALF, y + CHEVRON);
        context.stroke();
        y += CHEVRON_STEP;
      }
    });
  }

  function ensureCurrentArrow(color) {
    const id = `current-${color.key}`;
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
      // Over the clouds, whose colours are greys, arrows keep their own.
      const colours = shown && !scene.layers[shown].rain ? valueGrid(source, shown, state.t) : null;
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
  const centreMarkers = [];

  // The highs and lows of a pressure grid: [{lat, lon, high, value}]. A
  // point is one where it is the lowest (highest) of the disc of
  // CENTRE_RADIUS around it, and CENTRE_DEPTH below (above) the mean of
  // the edge of that disc. Only points that are already the lowest
  // (highest) of their eight neighbours are tried, so that it stays fast.
  function pressureCentres(values, g) {
    const n = g.nlon, rows = g.nlat;
    const reach = Math.max(2, Math.round(CENTRE_RADIUS / Math.abs(g.dlat)));
    const margin = Math.max(2, Math.round(reach / 3));
    const found = [];
    for (let j = margin; j < rows - margin; j++) {
      const lat = g.lat0 + j * g.dlat;
      const across = Math.min(n, Math.max(2, Math.round(reach * Math.abs(g.dlat) / (Math.abs(g.dlon) * Math.max(Math.cos((lat * Math.PI) / 180), 0.2)))));
      for (let i = margin; i < n - margin; i++) {
        const value = values[j * n + i];
        if (value !== value) continue;
        let lowest = true, highest = true;
        for (let dj = -1; dj <= 1 && (lowest || highest); dj++) {
          for (let di = -1; di <= 1; di++) {
            if (!di && !dj) continue;
            const other = values[(j + dj) * n + i + di];
            if (other !== other) continue;
            if (other < value) lowest = false;
            if (other > value) highest = false;
          }
        }
        if (lowest === highest) continue; // flat or neither
        // The disc around, clipped to the grid, and the mean of its edge.
        let extreme = true, edge = 0, count = 0;
        for (let dj = -reach; dj <= reach && extreme; dj++) {
          const jj = j + dj;
          if (jj < 0 || jj >= rows) continue;
          for (let di = -across; di <= across; di++) {
            const ii = i + di;
            if (ii < 0 || ii >= n) continue;
            const r = (dj / reach) * (dj / reach) + (di / across) * (di / across);
            if (r > 1) continue;
            const other = values[jj * n + ii];
            if (other !== other) continue;
            if (lowest ? other < value : other > value) { extreme = false; break; }
            if (r > 0.7) { edge += other; count++; }
          }
        }
        if (!extreme || !count) continue;
        const depth = lowest ? edge / count - value : value - edge / count;
        if (depth < CENTRE_DEPTH) continue;
        // A flat bottom gives several points: the first is kept.
        const close = found.some((item) => item.high === highest && Math.abs(item.j - j) <= reach && Math.abs(item.i - i) <= across);
        if (!close) found.push({ i, j, lat, lon: g.lon0 + i * g.dlon, high: highest, value });
      }
    }
    // Between the points of the grid, at the bottom (top) of a parabola
    // through each point and its neighbours, so that a centre moves smoothly
    // from one frame to the next.
    found.forEach((centre) => {
      const at = (di, dj) => values[(centre.j + dj) * n + centre.i + di];
      const shift = (before, after) => {
        const curvature = before - 2 * centre.value + after;
        return curvature === curvature && Math.abs(curvature) > 1e-9 ? Math.max(-0.5, Math.min(0.5, (before - after) / (2 * curvature))) : 0;
      };
      const di = shift(at(-1, 0), at(1, 0)), dj = shift(at(0, -1), at(0, 1));
      centre.lat = g.lat0 + (centre.j + dj) * g.dlat;
      centre.lon = g.lon0 + (centre.i + di) * g.dlon;
    });
    return found;
  }

  // The pressure of one frame of a source, in hPa.
  function frameValues(source, name, index) {
    const info = source.quantities[name], bytes = source.data[name][index];
    const out = new Float32Array(bytes.length);
    for (let k = 0; k < bytes.length; k++) out[k] = bytes[k] === NO_DATA ? NaN : info.offset + info.scale * bytes[k];
    return out;
  }

  // The highs and lows of a frame, found once.
  function frameCentres(source, index) {
    source.centres = source.centres || [];
    if (!source.centres[index]) source.centres[index] = pressureCentres(frameValues(source, "pressure", index), source.grid);
    return source.centres[index];
  }

  // The highs and lows at time t, moving between the frames before and after
  // it: each is paired with the nearest of its kind in the next frame, and
  // its position and pressure interpolated in time, as the fields are. A
  // centre without a pair fades out, a new one fades in.
  function movingCentres(source, t) {
    const frame = frameAt(source, t);
    if (!frame) return [];
    const first = frameCentres(source, frame.i0);
    if (frame.i0 === frame.i1 || frame.a === 0) return first.map((centre) => ({ ...centre, opacity: 1 }));
    const second = frameCentres(source, frame.i1);
    if (frame.a === 1) return second.map((centre) => ({ ...centre, opacity: 1 }));
    const hours = (source.times[frame.i1] - source.times[frame.i0]) / 3600;
    const reach = Math.max(CENTRE_REACH, (CENTRE_SPEED * hours) / 60);
    const pairs = [];
    first.forEach((a, ia) => second.forEach((b, ib) => {
      if (a.high !== b.high) return;
      const distance = Math.hypot(b.lat - a.lat, (b.lon - a.lon) * Math.cos((((a.lat + b.lat) / 2) * Math.PI) / 180));
      if (distance <= reach) pairs.push([distance, ia, ib]);
    }));
    pairs.sort((p, q) => p[0] - q[0]);
    const pairedFirst = new Set(), pairedSecond = new Set(), out = [];
    const a = frame.a, mix = (x, y) => x + a * (y - x);
    pairs.forEach(([, ia, ib]) => {
      if (pairedFirst.has(ia) || pairedSecond.has(ib)) return;
      pairedFirst.add(ia);
      pairedSecond.add(ib);
      const c0 = first[ia], c1 = second[ib];
      out.push({ high: c0.high, lat: mix(c0.lat, c1.lat), lon: mix(c0.lon, c1.lon), value: mix(c0.value, c1.value), opacity: 1 });
    });
    first.forEach((centre, index) => { if (!pairedFirst.has(index)) out.push({ ...centre, opacity: 1 - a }); });
    second.forEach((centre, index) => { if (!pairedSecond.has(index)) out.push({ ...centre, opacity: a }); });
    return out.filter((centre) => centre.opacity > 0.05);
  }

  function updateCentres(source) {
    const centres = source && state.centres ? movingCentres(source, state.t) : [];
    while (centreMarkers.length < centres.length) {
      const element = document.createElement("div");
      element.className = "map-label pressure-centre";
      centreMarkers.push({ marker: new maplibregl.Marker({ element }), added: false });
    }
    centreMarkers.forEach((item, index) => {
      if (index < centres.length) {
        const centre = centres[index];
        const element = item.marker.getElement();
        element.innerHTML = `<b>${centre.high ? "H" : "L"}</b><span>${Math.round(centre.value)}</span>`;
        element.title = `${centre.high ? "High" : "Low"}, ${Math.round(centre.value)} hPa`;
        // On its content: MapLibre sets the opacity of the marker itself.
        element.style.setProperty("--fade", centre.opacity < 1 ? centre.opacity.toFixed(2) : "1");
        item.marker.setLngLat([centre.lon, centre.lat]);
        if (!item.added) { item.marker.addTo(map); item.added = true; }
      } else if (item.added) {
        item.marker.remove();
        item.added = false;
      }
    });
  }

  function updateIsobars() {
    const source = currentSource();
    const features = [];
    const labels = [];
    const values = state.isobars && source && source.quantities.pressure && includedLayers(source).includes("pressure") ? grid(source, "pressure", state.t) : null;
    updateCentres(values ? source : null);
    if (values) {
      let low = Infinity, high = -Infinity;
      for (let k = 0; k < values.length; k++) {
        if (values[k] === values[k]) { low = Math.min(low, values[k]); high = Math.max(high, values[k]); }
      }
      const spacing = state.isobarStep;
      for (let level = Math.ceil(low / spacing) * spacing; level <= high; level += spacing) {
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
    const [lat, lon] = greatCircle(route.lat[low], route.lon[low], route.lat[high], route.lon[high], f);
    return { lat, lon, k: Math.min(low, route.ctim.length - 1), phase: "under way" };
  }

  // The point a fraction `f` of the way along the great circle between two
  // positions, as the routing computes its legs.
  function greatCircle(lat1, lon1, lat2, lon2, f) {
    const rad = Math.PI / 180;
    const a = [Math.cos(lat1 * rad) * Math.cos(lon1 * rad), Math.cos(lat1 * rad) * Math.sin(lon1 * rad), Math.sin(lat1 * rad)];
    const b = [Math.cos(lat2 * rad) * Math.cos(lon2 * rad), Math.cos(lat2 * rad) * Math.sin(lon2 * rad), Math.sin(lat2 * rad)];
    const angle = Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2])));
    if (angle < 1e-9) return [lat1 + f * (lat2 - lat1), lon1 + f * (lon2 - lon1)];
    const wa = Math.sin((1 - f) * angle) / Math.sin(angle), wb = Math.sin(f * angle) / Math.sin(angle);
    const x = wa * a[0] + wb * b[0], y = wa * a[1] + wb * b[1], z = wa * a[2] + wb * b[2];
    const lat = Math.atan2(z, Math.hypot(x, y)) / rad;
    let lon = Math.atan2(y, x) / rad;
    // Kept on the side of the first point, so that lines do not jump.
    while (lon - lon1 > 180) lon -= 360;
    while (lon - lon1 < -180) lon += 360;
    return [lat, lon];
  }

  // The line of a route along the great circles between its nodes, a
  // point every half degree or so.
  function routeLine(route) {
    if (route.line) return route.line;
    const line = [[route.lon[0], route.lat[0]]];
    for (let i = 1; i < route.lat.length; i++) {
      const lat1 = route.lat[i - 1], lon1 = line[line.length - 1][0];
      const span = Math.hypot(route.lat[i] - lat1, (route.lon[i] - route.lon[i - 1]) * Math.cos((lat1 * Math.PI) / 180));
      const pieces = Math.max(1, Math.ceil(span / 0.5));
      for (let p = 1; p <= pieces; p++) {
        const [lat, lon] = greatCircle(lat1, lon1, route.lat[i], route.lon[i], p / pieces);
        line.push([lon, lat]);
      }
    }
    return (route.line = line);
  }

  function updateRoutes() {
    const shown = shownRoutes();
    map.getSource("routes").setData({
      type: "FeatureCollection",
      features: shown.map((route) => ({
        type: "Feature",
        properties: { id: route.id, color: route.color },
        geometry: { type: "LineString", coordinates: routeLine(route) },
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
    LAND_LAYERS.forEach((id) => {
      setVisible(id, state.basemap !== "osm");
      setVisible(id + DETAIL, state.basemap !== "osm");
    });
    SEAMARK_LEVELS.forEach(([zoom]) => setVisible(`seamarks-${zoom}`, state.seamarks));
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
      right: Math.min(state.plotsOpen && width > 720 ? $("plots").offsetWidth + 30 : 70, width / 3),
    };
    map.fitBounds(bounds, { padding, duration: 600, maxZoom: 7 });
  }

  // --------------------------------------------------------------------
  // Tooltips and readout
  // --------------------------------------------------------------------

  let popup = null;

  function routeById(id) { return scene.routes.find((route) => route.id === id); }

  // Variables that share a row of the route tooltip, and gusts, each on a
  // row of its own under its speed.
  const PAIRS = [["sog", "cog"], ["stw", "ctw"], ["tws", "twa"], ["aws", "awa"], ["swh", "mwa"], ["cs", "cd"], ["bhp", "max_bhp"], ["total_power", "hotel_load"], ["hourly_consumption", "sfoc"]];
  const GUSTS = { tws_gust: "tws", aws_gust: "aws" };

  // The variables of a tooltip in rows of two: pairs together, gusts alone
  // under their speed, the others two by two, in the order chosen.
  function tooltipRows(names) {
    const rows = [];
    const placed = new Set();
    const partner = (name) => {
      const pair = PAIRS.find((item) => item.includes(name));
      return pair ? pair.find((other) => other !== name && names.includes(other)) : undefined;
    };
    let open = null; // a row of one variable without partner, to complete
    names.forEach((name) => {
      if (placed.has(name)) return;
      if (GUSTS[name] && names.includes(GUSTS[name])) return; // placed under its speed
      const other = partner(name);
      let row;
      if (other) {
        const pair = PAIRS.find((item) => item.includes(name));
        row = { cells: pair.filter((item) => item === name || item === other) };
        placed.add(other);
      } else if (open) {
        open.cells.push(name);
        open = null;
        placed.add(name);
        return;
      } else {
        row = { cells: [name] };
        open = row;
      }
      placed.add(name);
      rows.push(row);
      if (other) open = null;
      // The gust of a speed of this row, alone under it.
      row.cells.forEach((cell) => {
        Object.keys(GUSTS).forEach((gust) => {
          if (GUSTS[gust] === cell && names.includes(gust)) {
            rows.push({ cells: [gust], alone: true });
            placed.add(gust);
            if (open === row) open = null;
          }
        });
      });
    });
    return rows;
  }

  function popupContent(route, k, t, phase) {
    const cell = (name) => {
      if (!name) return '<span></span><span></span>';
      const meta = scene.variables[name];
      return `<span class="pt-label" title="${escapeHtml(meta.description)}">${escapeHtml(meta.label)}</span>` +
        `<span class="pt-value">${escapeHtml(formatValue(name, route.values[name][k]))}</span>`;
    };
    const rows = tooltipRows(hoverVariables().filter((name) => route.values[name]))
      .map((row) => cell(row.cells[0]) + cell(row.cells[1]));
    let when = formatTime(t);
    if (phase === "before") when = `Not under way yet · ETD ${formatShort(route.etd)}`;
    if (phase === "after") when = `Arrived · ETA ${formatShort(route.eta)}`;
    const shown = phase === "under way" || phase === "segment";
    const total = route.summary.fuel !== null ? `<div class="popup-fuel"><span>Voyage fuel</span><b>${route.summary.fuel.toFixed(1)} t</b></div>` : "";
    // A point tells its comment, a boat the description of its route.
    const comment = phase === "segment" ? commentAt(route, k) : "";
    const description = phase === "segment" ? "" : routeDescription(route);
    return (
      `<div class="popup-title"><span class="swatch" style="background:${route.color}"></span>${escapeHtml(routeLabel(route))}</div>` +
      `<div class="popup-time">${escapeHtml(when)}</div>` +
      (comment ? `<div class="popup-text comment" style="--route:${route.color}">${escapeHtml(comment)}</div>` : "") +
      (description ? `<div class="popup-text">${escapeHtml(description)}</div>` : "") +
      (shown && rows.length ? `<div class="popup-grid">${rows.join("")}</div>` : "") +
      total +
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
    if (!popup) popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: "380px" });
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
    // A route clicked is the route of the plots.
    if (target && target.id !== state.plotRoute) selectPlotRoute(target.id);
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

  // The charts shown, sent to ui.py at each toggle, so that its choice of the
  // charts shown at opening follows the preview.
  function sendOverlays() {
    if (window.parent === window) return;
    const overlays = {};
    scene.overlays.forEach((overlay) => { overlays[overlay.id] = !!state.overlays[overlay.id]; });
    try { window.parent.postMessage({ type: "architeuthis:overlays", overlays }, "*"); } catch (error) { /* not embedded */ }
  }

  // The zones ticked, sent to ui.py at each toggle and once loaded: the file
  // it writes holds only those, shown.
  function sendZones() {
    if (window.parent === window) return;
    const zones = {};
    scene.zones.forEach((zone) => { zones[zone.id] = zone.outline.length >= 2 && !!state.zones[zone.id]; });
    try { window.parent.postMessage({ type: "architeuthis:zones", zones }, "*"); } catch (error) { /* not embedded */ }
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
        if (value === value) rows.push({ label: info.label, value: formatLayerValue(info, value), detail: rainText(source, layer, t, lat, lon) });
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

  const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  function compass(degrees) { return COMPASS[Math.round((((degrees % 360) + 360) % 360) / 22.5) % 16]; }

  // A small arrow pointing where the flow goes, as the glyphs of the map.
  function flowArrow(towards) {
    return `<svg class="pk-arrow" viewBox="0 0 12 12" style="transform:rotate(${towards.toFixed(0)}deg)"><path d="M6 1 10 10 6 8 2 10z"/></svg>`;
  }

  // What the picker tells: wind with its gusts, waves and pressure, then
  // the field shown if it is another one, each when the file has it.
  function pickerConditions(lat, lon) {
    const source = currentSource();
    if (!source) return { message: "No forecast in this file" };
    const t = state.t;
    lon = wrapLongitude(lon);
    if (!frameAt(source, t)) return { message: `No forecast at this time`, source };
    const q = source.quantities;
    const at = (name) => (q[name] ? sampleAt(source, name, t, lat, lon) : NaN);
    const rows = [];
    const u = at("wind_u"), v = at("wind_v"), gust = at("gust");
    if (u === u && v === v) {
      const from = (Math.atan2(-u, -v) * 180) / Math.PI;
      rows.push({
        label: "Wind", value: Math.hypot(u, v).toFixed(0), unit: "kt", towards: from + 180,
        detail: compass(from) + (gust === gust ? ` · gusts ${gust.toFixed(0)} kt` : ""),
      });
    } else if (gust === gust) {
      rows.push({ label: "Gusts", value: gust.toFixed(0), unit: "kt", detail: "" });
    }
    const height = at("swh"), x = at("wave_x"), y = at("wave_y");
    if (height === height) {
      const from = (Math.atan2(x, y) * 180) / Math.PI;
      const known = x === x && y === y && height > 0.05;
      rows.push({ label: "Waves", value: height.toFixed(1), unit: "m", towards: known ? from + 180 : null, detail: known ? compass(from) : "" });
    }
    const pressure = at("pressure");
    if (pressure === pressure) rows.push({ label: "Pressure", value: pressure.toFixed(0), unit: (scene.layers.pressure || {}).unit || "hPa", detail: "" });
    const shown = state.layer;
    if (shown && !["wind", "gust", "waves", "pressure"].includes(shown) && includedLayers(source).includes(shown)) {
      const info = scene.layers[shown];
      const value = layerValueAt(source, shown, t, lat, lon);
      if (value === value) {
        const text = formatLayerValue(info, value);
        const unit = info.unit && text.endsWith(" " + info.unit) ? info.unit : "";
        rows.push({ label: info.label, value: unit ? text.slice(0, -unit.length - 1) : text, unit, detail: rainText(source, shown, t, lat, lon), shown: true });
      }
    }
    if (!rows.length) return { message: "Outside the forecast", source };
    return { rows, source };
  }

  function updatePicker() {
    if (!pickerMarker || !state.picker) return;
    const card = pickerMarker.getElement().querySelector(".picker-card");
    const found = pickerConditions(state.picker.lat, state.picker.lon);
    const rows = found.rows
      ? found.rows.map((row) =>
        `<div class="pk-row${row.shown ? " shown" : ""}"><span class="pk-label">${escapeHtml(row.label)}</span>` +
        `<span class="pk-value">${escapeHtml(row.value)}<small>${escapeHtml(row.unit)}</small></span>` +
        `<span class="pk-detail">${row.towards !== undefined && row.towards !== null ? flowArrow(row.towards) : ""}${escapeHtml(row.detail)}</span></div>`).join("")
      : `<div class="pk-message">${escapeHtml(found.message)}</div>`;
    card.innerHTML =
      `<div class="picker-head"><div><div class="pk-position">${escapeHtml(formatPosition(state.picker.lat, state.picker.lon))}</div>` +
      `<div class="pk-sub">${found.source ? `<span class="pk-model">${escapeHtml(found.source.label)}</span>` : ""}${escapeHtml(formatShort(state.t))}</div></div>` +
      `<button class="picker-close" type="button" title="Remove the picker">${icon("close")}</button></div>` +
      `<div class="pk-rows">${rows}</div>`;
  }

  // --------------------------------------------------------------------
  // Plots of a route, beside the map
  // --------------------------------------------------------------------

  // Width of the axis labels on the left of the plots, and the colours of
  // the curves, vivid enough for both themes.
  const PLOT_GUTTER = 34;
  // Widths of the lines of the plots, and the dashes of the secondary ones.
  const PLOT_LINE = 1.1;
  const PLOT_THIN = 0.9;
  const PLOT_DASH = [3, 2];
  const PLOT_COLORS = {
    sog: "#4cc9f0",
    stw: "#f8961e",
    sails: "#2ec4b6",
    hotel: "#f9c74f",
    propulsion: "#9b5de5",
    wind: "#90e0ef",
    waves: "#48bfe3",
    pressure: "#c77dff",
  };
  // The sky of the cloud plot: by day and by night, horizon and top, and the
  // clouds lit and in shade, as plot_utils.plot_sky draws it.
  const DAY_SKY = [[0.74, 0.87, 0.96], [0.18, 0.44, 0.73]];
  const NIGHT_SKY = [[0.50, 0.61, 0.75], [0.13, 0.29, 0.50]];
  // The night is only a hint, as in plot_sky: from the Sun at TWILIGHT[0]
  // deg (civil twilight) to day at TWILIGHT[1] (sunset), the clouds keeping
  // NIGHT_CLOUD_LIGHT of their brightness.
  const TWILIGHT = [-6, 0];
  const NIGHT_CLOUD_LIGHT = 0.85;
  const CLOUD_LIT = [1, 1, 1];
  const CLOUD_SHADE = [0.33, 0.36, 0.42];
  const ROW_KM = [0, 2, 6, 12];
  // Per genus: bottom and top in km ("base" for the cloud base, "cape" for a
  // depth growing with the CAPE), opacity, darkness and texture.
  const SKY_LAYERS = {
    St: ["base", 0.45, 0.95, 0.45, "flat"],
    Sc: ["base", 0.9, 0.9, 0.35, "rolls"],
    Cu: ["base", "cape", 0.95, 0.2, "puffs"],
    Cb: ["base", 11.0, 1.0, 0.75, "tower"],
    Ns: [0.6, 6.5, 1.0, 0.8, "flat"],
    As: [3.0, 6.0, 0.85, 0.5, "flat"],
    Ac: [3.2, 4.6, 0.8, 0.15, "rolls"],
    Cs: [7.0, 10.0, 0.6, 0.05, "veil"],
    Ci: [8.0, 10.5, 0.75, 0.0, "fibres"],
  };
  const RAIN_RATE = 0.1; // mm/h
  const RAIN_COLOR = "rgba(30, 136, 229, 0.9)";
  const SNOW_COLOR = "#e3f2fd";
  const LIGHTNING_COLOR = "#ffd54f";
  const FOG_COLOR = [0.86, 0.87, 0.88];
  const SNOW_TEMPERATURE = 274.15; // K
  // The printed report: plots drawn on white, at this many pixels per CSS
  // pixel and this width (an A4 page within its margins), their fills
  // lighter by this factor to save ink, the sky white by day and light
  // grey by night, and the comments marked in this colour.
  let printing = false;
  const PRINT_RATIO = 3;
  const PRINT_WIDTH = 700;
  const PRINT_INK = 0.45;
  const PRINT_SKY = { day: [[1, 1, 1], [1, 1, 1]], night: [[0.965, 0.97, 0.975], [0.945, 0.95, 0.96]], lit: [0.88, 0.9, 0.92], shade: [0.58, 0.61, 0.66], snow: "#90a4ae", cirrus: "120, 130, 140" };
  const PRINT_MARK = "#c1121f";

  // The opacity of a fill, lighter on paper.
  function ink(alpha) {
    return printing ? alpha * PRINT_INK : alpha;
  }

  // The route of the plots: the one chosen while it is shown, else the
  // first shown, else the first of the file.
  function plotRoute() {
    const shown = shownRoutes();
    return shown.find((route) => route.id === state.plotRoute) || shown[0] || includedRoutes()[0] || null;
  }

  function series(route, name) {
    const values = (route.series && route.series[name]) || route.values[name];
    return values && values.some((value) => value !== null) ? values : null;
  }

  function niceStep(span, count) {
    const raw = span / Math.max(count, 1);
    const power = Math.pow(10, Math.floor(Math.log10(raw)));
    const unit = raw / power;
    return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10) * power;
  }

  // The range of a plot over some series: `low` and `high` where given
  // (null leaves a bound free), else the extremes of the values with a
  // little room, and round ticks inside it.
  function plotRange(lists, low, high) {
    let min = Infinity, max = -Infinity;
    lists.forEach((values) => (values || []).forEach((value) => {
      if (value !== null && value === value) { min = Math.min(min, value); max = Math.max(max, value); }
    }));
    if (!(max >= min)) { min = low === null ? 0 : low; max = high === null ? min + 1 : high; }
    const from = low === null ? min : low, to = high === null ? max : high;
    let room = 0.08 * Math.abs(to - from);
    if (room < 1e-9) room = Math.max(0.5, 0.05 * Math.abs(to));
    low = low === null ? min - room : low;
    high = high === null ? Math.max(max + room, low + 1e-6) : high;
    const step = niceStep(high - low, 3);
    const ticks = [];
    for (let tick = Math.ceil(low / step - 1e-9) * step; tick <= high + step * 1e-9; tick += step) ticks.push(Math.round(tick * 1e6) / 1e6);
    return { low, high, ticks };
  }

  function cssColor(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  }

  function rgba(hex, alpha) {
    const value = parseInt(hex.slice(1), 16);
    return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
  }

  // The colour of a value on the scale of a layer, or null without it.
  function scaleColor(layer, value) {
    const info = scene.layers[layer];
    if (!info || !info.colormap) return null;
    const colors = info.colormap.colors;
    const index = Math.round(((value - info.colormap.min) / (info.colormap.max - info.colormap.min)) * (colors.length - 1));
    return colors[Math.max(0, Math.min(colors.length - 1, index))];
  }

  // A canvas of a plot with its geometry: time and value to pixels.
  function plotFrame(canvas, route, range) {
    // At least twice the pixels of the page, so that thin lines stay smooth.
    const ratio = printing ? PRINT_RATIO : Math.max(2, window.devicePixelRatio || 1);
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (canvas.width !== Math.round(width * ratio)) canvas.width = Math.round(width * ratio);
    if (canvas.height !== Math.round(height * ratio)) canvas.height = Math.round(height * ratio);
    const context = canvas.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    const t0 = route.tim[0], t1 = route.tim[route.tim.length - 1];
    const left = PLOT_GUTTER, right = width - 4, top = 4, bottom = height - 3;
    return {
      context, width, height, left, right, top, bottom, t0, t1,
      x: (t) => left + ((t - t0) / (t1 - t0)) * (right - left),
      y: range ? (value) => bottom - ((value - range.low) / (range.high - range.low)) * (bottom - top) : null,
    };
  }

  // Horizontal lines at the ticks, their values in the gutter, and a line
  // at each midnight UTC.
  function drawGrid(frame, range, format) {
    const c = frame.context;
    c.save();
    c.strokeStyle = cssColor("--line");
    c.fillStyle = cssColor("--muted");
    // One pixel of the screen, aligned on it.
    const pixel = printing ? 0.5 : 1 / (window.devicePixelRatio || 1);
    const align = (value) => (Math.round(value / pixel) + 0.5) * pixel;
    c.lineWidth = pixel;
    c.font = "10px system-ui, sans-serif";
    c.textAlign = "right";
    c.textBaseline = "middle";
    if (range) {
      range.ticks.forEach((tick) => {
        const y = align(frame.y(tick));
        c.beginPath(); c.moveTo(frame.left, y); c.lineTo(frame.right, y); c.stroke();
        c.fillText(format ? format(tick) : String(tick), frame.left - 5, Math.max(6, Math.min(frame.height - 5, y)));
      });
    }
    c.setLineDash([2, 2]);
    for (let t = Math.ceil(frame.t0 / DAY) * DAY; t < frame.t1; t += DAY) {
      const x = align(frame.x(t));
      c.beginPath(); c.moveTo(x, frame.top); c.lineTo(x, frame.bottom); c.stroke();
    }
    c.restore();
  }

  // The path of a series per segment, as steps from node to node, broken
  // where values are missing and kept inside the frame. `base` closes it
  // into an area down to it.
  function stepPath(frame, route, values, base) {
    const c = frame.context;
    const parts = [];
    let part = null;
    values.forEach((value, k) => {
      if (value === null || value !== value) { part = null; return; }
      if (!part) parts.push((part = []));
      const y = Math.max(frame.top, Math.min(frame.bottom, frame.y(value)));
      part.push([frame.x(route.tim[k]), y, k], [frame.x(route.tim[k + 1]), y, k]);
    });
    c.beginPath();
    parts.forEach((points) => {
      points.forEach(([x, y], index) => (index ? c.lineTo(x, y) : c.moveTo(x, y)));
      if (base) {
        for (let index = points.length - 1; index >= 0; index--) {
          const b = typeof base === "function" ? base(points[index][2], points[index]) : base;
          c.lineTo(points[index][0], b);
        }
        c.closePath();
      }
    });
  }

  // The segment of the route at the time shown, or -1 off the route.
  function plotSegment(route) {
    if (state.t < route.tim[0] || state.t > route.tim[route.tim.length - 1]) return -1;
    return routePosition(route, state.t).k;
  }

  // A vertical gradient along the scale of a layer, from `low` to `high`,
  // or a plain colour without that layer.
  function scaleFill(frame, layer, low, high, alpha, fallback) {
    if (!scene.layers[layer] || !scene.layers[layer].colormap) return rgba(fallback, ink(alpha));
    const gradient = frame.context.createLinearGradient(0, frame.y(low), 0, frame.y(high));
    for (let s = 0; s <= 8; s++) {
      const color = scaleColor(layer, low + (s / 8) * (high - low));
      gradient.addColorStop(s / 8, rgba(color, ink(alpha)));
    }
    return gradient;
  }

  function strokeSeries(frame, route, values, color, width, dash) {
    const c = frame.context;
    stepPath(frame, route, values);
    c.save();
    c.strokeStyle = color;
    c.lineWidth = width;
    c.lineJoin = "round";
    if (dash) c.setLineDash(dash);
    c.stroke();
    c.restore();
  }

  function fillSeries(frame, route, values, fill, base) {
    stepPath(frame, route, values, base === undefined ? frame.bottom : base);
    frame.context.fillStyle = fill;
    frame.context.fill();
  }

  // A translucent band in the colour of the text, from a series down to
  // `lower(k)` on each segment.
  function fillBand(frame, route, values, lower) {
    stepPath(frame, route, values, (k) => {
      const value = lower(k);
      return value === null || value !== value ? frame.bottom : Math.max(frame.top, Math.min(frame.bottom, frame.y(value)));
    });
    const c = frame.context;
    c.save();
    c.globalAlpha = 0.12;
    c.fillStyle = cssColor("--fg");
    c.fill();
    c.restore();
  }

  function formatFixed(value, digits) {
    return value === null || value === undefined || value !== value ? "–" : value.toFixed(digits);
  }

  function chip(color, dashed) {
    return `<i class="${dashed ? "dashed" : ""}" style="--chip:${color}"></i>`;
  }

  // A speed and its gust, its area coloured by the wind scale.
  function windPlot(id, title, speed, gust) {
    return {
      id, title, unit: "kt", height: 96,
      available: (route) => !!series(route, speed),
      draw(canvas, route) {
        const values = series(route, speed), gusts = series(route, gust);
        const range = plotRange([values, gusts], 0, null);
        const frame = plotFrame(canvas, route, range);
        drawGrid(frame, range);
        fillSeries(frame, route, values, scaleFill(frame, "wind", range.low, range.high, 0.8, PLOT_COLORS.wind));
        if (gusts) {
          // From the mean wind up to the gusts, in the colour of their lines.
          fillBand(frame, route, gusts, (k) => values[k]);
          strokeSeries(frame, route, gusts, cssColor("--fg"), PLOT_THIN, PLOT_DASH);
        }
        strokeSeries(frame, route, values, cssColor("--fg"), PLOT_LINE);
        return frame;
      },
      readout(route, k) {
        const values = series(route, speed), gusts = series(route, gust);
        return `${chip(scaleColor("wind", values[k] || 0) || PLOT_COLORS.wind)}<b>${formatFixed(values[k], 1)}</b>` +
          (gusts ? `${chip(cssColor("--fg"), true)}gust <b>${formatFixed(gusts[k], 1)}</b>` : "") + " kt";
      },
    };
  }

  // Propulsion and hotel load stacked, from the brake power, else the total.
  function powerParts(route) {
    const hotel = series(route, "hotel_load");
    const bhp = series(route, "bhp"), total = series(route, "total_power");
    let propulsion = bhp;
    if (!propulsion && total) propulsion = hotel ? total.map((value, k) => (value === null || hotel[k] === null ? null : value - hotel[k])) : total;
    if (!propulsion && !hotel) return null;
    const zero = (propulsion || hotel).map(() => 0);
    const max = series(route, "max_bhp");
    return { hotel: hotel || zero, propulsion: propulsion || zero, fluctuation: max && bhp ? max.map((value, k) => (value === null || bhp[k] === null ? null : value - bhp[k])) : null, hasHotel: !!hotel, hasPropulsion: !!propulsion };
  }

  const PLOTS = [
    {
      id: "speed", title: "Speed", unit: "kt", height: 90,
      available: (route) => !!(series(route, "sog") || series(route, "stw")),
      draw(canvas, route) {
        const sog = series(route, "sog"), stw = series(route, "stw");
        const range = plotRange([sog, stw], null, null);
        const frame = plotFrame(canvas, route, range);
        drawGrid(frame, range);
        if (sog) {
          const fill = frame.context.createLinearGradient(0, frame.top, 0, frame.bottom);
          fill.addColorStop(0, rgba(PLOT_COLORS.sog, ink(0.35)));
          fill.addColorStop(1, rgba(PLOT_COLORS.sog, ink(0.02)));
          fillSeries(frame, route, sog, fill);
        }
        if (stw) strokeSeries(frame, route, stw, PLOT_COLORS.stw, PLOT_LINE);
        if (sog) strokeSeries(frame, route, sog, PLOT_COLORS.sog, PLOT_LINE);
        return frame;
      },
      readout(route, k) {
        const sog = series(route, "sog"), stw = series(route, "stw");
        return (sog ? `${chip(PLOT_COLORS.sog)}SOG <b>${formatFixed(sog[k], 1)}</b>` : "") +
          (stw ? `${chip(PLOT_COLORS.stw)}STW <b>${formatFixed(stw[k], 1)}</b>` : "") + " kt";
      },
    },
    {
      id: "sails", title: "Sails", unit: "%", height: 69,
      available: (route) => !!series(route, "sails_contribution"),
      draw(canvas, route) {
        const values = series(route, "sails_contribution");
        const range = plotRange([], 0, 100);
        const frame = plotFrame(canvas, route, range);
        drawGrid(frame, range);
        const fill = frame.context.createLinearGradient(0, frame.top, 0, frame.bottom);
        fill.addColorStop(0, rgba(PLOT_COLORS.sails, ink(0.75)));
        fill.addColorStop(1, rgba(PLOT_COLORS.sails, ink(0.12)));
        fillSeries(frame, route, values, fill);
        strokeSeries(frame, route, values, PLOT_COLORS.sails, PLOT_LINE);
        return frame;
      },
      readout(route, k) {
        return `${chip(PLOT_COLORS.sails)}<b>${formatFixed(series(route, "sails_contribution")[k], 0)}</b> % of the thrust`;
      },
    },
    {
      id: "power", title: "Power", unit: "kW", height: 108,
      available: (route) => !!powerParts(route),
      draw(canvas, route) {
        const parts = powerParts(route);
        const total = parts.propulsion.map((value, k) => (value === null || parts.hotel[k] === null ? null : value + parts.hotel[k]));
        const upper = parts.fluctuation ? total.map((value, k) => (value === null || parts.fluctuation[k] === null ? null : value + parts.fluctuation[k])) : null;
        const lower = upper ? total.map((value, k) => (value === null || parts.fluctuation[k] === null ? null : value - parts.fluctuation[k])) : null;
        const range = plotRange([total, upper], 0, null);
        const frame = plotFrame(canvas, route, range);
        drawGrid(frame, range, (tick) => (tick >= 1000 ? `${tick / 1000}k` : String(tick)));
        // Hotel load at the bottom, propulsion stacked on it.
        fillSeries(frame, route, parts.hotel, rgba(PLOT_COLORS.hotel, ink(0.8)));
        fillSeries(frame, route, total, rgba(PLOT_COLORS.propulsion, ink(0.75)), (k) => frame.y(parts.hotel[k] || 0));
        if (upper) {
          // The fluctuation of the brake power around the total, in the
          // colour of its line.
          fillBand(frame, route, upper, (k) => (lower[k] === null ? 0 : lower[k]));
          strokeSeries(frame, route, upper, cssColor("--fg"), PLOT_THIN, PLOT_DASH);
          strokeSeries(frame, route, lower, cssColor("--fg"), PLOT_THIN, PLOT_DASH);
        }
        strokeSeries(frame, route, total, cssColor("--fg"), PLOT_LINE);
        return frame;
      },
      readout(route, k) {
        const parts = powerParts(route);
        let text = "";
        if (parts.hasPropulsion) text += `${chip(PLOT_COLORS.propulsion)}prop. <b>${formatFixed(parts.propulsion[k], 0)}</b>`;
        if (parts.hasHotel) text += `${chip(PLOT_COLORS.hotel)}hotel <b>${formatFixed(parts.hotel[k], 0)}</b>`;
        if (parts.fluctuation) text += `${chip(cssColor("--fg"), true)}± <b>${formatFixed(parts.fluctuation[k], 0)}</b>`;
        return text + " kW";
      },
    },
    windPlot("tws", "True wind", "tws", "tws_gust"),
    windPlot("aws", "Apparent wind", "aws", "aws_gust"),
    {
      id: "swh", title: "Waves", unit: "m", height: 78,
      available: (route) => !!series(route, "swh"),
      draw(canvas, route) {
        const values = series(route, "swh");
        const range = plotRange([values], 0, null);
        const frame = plotFrame(canvas, route, range);
        drawGrid(frame, range);
        fillSeries(frame, route, values, scaleFill(frame, "waves", range.low, range.high, 0.85, PLOT_COLORS.waves));
        strokeSeries(frame, route, values, cssColor("--fg"), PLOT_LINE);
        return frame;
      },
      readout(route, k) {
        const values = series(route, "swh");
        return `${chip(scaleColor("waves", values[k] || 0) || PLOT_COLORS.waves)}Hs <b>${formatFixed(values[k], 1)}</b> m`;
      },
    },
    {
      id: "pressure", title: "Pressure", unit: "hPa", height: 78,
      available: (route) => !!series(route, "pressure"),
      draw(canvas, route) {
        const values = series(route, "pressure");
        const range = plotRange([values], null, null);
        const frame = plotFrame(canvas, route, range);
        drawGrid(frame, range);
        fillSeries(frame, route, values, scaleFill(frame, "pressure", range.low, range.high, 0.55, PLOT_COLORS.pressure));
        strokeSeries(frame, route, values, cssColor("--fg"), PLOT_LINE);
        return frame;
      },
      readout(route, k) {
        const value = series(route, "pressure")[k];
        return `${chip(scaleColor("pressure", value || 1013) || PLOT_COLORS.pressure)}<b>${formatFixed(value, 1)}</b> hPa`;
      },
    },
    {
      id: "clouds", title: "Clouds", unit: "km", height: 174,
      available: (route) => !!route.sky,
      draw(canvas, route) {
        const frame = plotFrame(canvas, route, null);
        frame.y = (km) => frame.bottom - (kmToRow(km) / 3) * (frame.bottom - frame.top);
        drawSky(frame, route, route.sky);
        drawGrid(frame, { ticks: [0, 2, 6, 12] });
        return frame;
      },
      readout(route, k) {
        return skyText(route.sky, k);
      },
    },
  ];

  // ---- The sky of the cloud plot ----

  function kmToRow(km) {
    for (let i = 1; i < ROW_KM.length; i++) {
      if (km <= ROW_KM[i]) return i - 1 + (km - ROW_KM[i - 1]) / (ROW_KM[i] - ROW_KM[i - 1]);
    }
    return ROW_KM.length - 1;
  }

  function smoothstep(edge0, edge1, x) {
    const t = Math.max(0, Math.min(1, (x - edge0) / (edge1 - edge0)));
    return t * t * (3 - 2 * t);
  }

  // A smooth noise in [-1, 1] along the route, the same at each drawing.
  function noise(phase, seed, scale) {
    let value = 0;
    [0.7, 1.9, 4.3].forEach((frequency, index) => {
      value += Math.sin((2 * Math.PI * frequency * phase) / scale + 1.7 * seed + 2.3 * index) / frequency;
    });
    return value / 1.9;
  }

  function seeded(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Elevation of the Sun in degrees, within a few tenths: by day or night.
  function sunElevation(t, lat, lon) {
    const days = t / DAY - 10957.5;
    const rad = Math.PI / 180;
    const anomaly = (357.529 + 0.98560028 * days) * rad;
    const ecliptic = (280.459 + 0.98564736 * days + 1.915 * Math.sin(anomaly) + 0.02 * Math.sin(2 * anomaly)) * rad;
    const obliquity = (23.439 - 0.00000036 * days) * rad;
    const ascension = Math.atan2(Math.cos(obliquity) * Math.sin(ecliptic), Math.cos(ecliptic)) / rad;
    const declination = Math.asin(Math.sin(obliquity) * Math.sin(ecliptic));
    const sidereal = (18.697374558 + 24.06570982441908 * days) * 15;
    const hour = (sidereal + lon - ascension) * rad;
    return Math.asin(Math.sin(lat * rad) * Math.sin(declination) + Math.cos(lat * rad) * Math.cos(declination) * Math.cos(hour)) / rad;
  }

  function genusPresent(sky, etage, k) {
    const mask = sky[`${etage}_genera`][k];
    const present = [];
    if (mask === null) return present;
    (scene.cloud_genera || []).forEach((genus, index) => { if ((mask >> index) & 1) present.push(genus.abbreviation); });
    return present;
  }

  function skyText(sky, k) {
    if (sky.oktas[k] === null) return "<b>–</b>";
    const genera = scene.cloud_genera || [];
    const seen = ["low", "middle", "high"].map((etage) => sky[etage][k]).filter((code) => code >= 0).map((code) => genera[code].abbreviation);
    const oktas = sky.oktas[k] === 9 ? "fog" : `${sky.oktas[k]}/8`;
    const base = sky.base[k] !== null && seen.length ? ` · base ${Math.round(sky.base[k] / 100) * 100} m` : "";
    const rain = sky.prate[k] >= RAIN_RATE ? ` · ${sky.t2m[k] < SNOW_TEMPERATURE ? "snow" : "rain"} ${sky.prate[k].toFixed(1)} mm/h` : "";
    return `<b>${oktas}</b> ${escapeHtml(seen.join(" ") || "clear")}${base}${rain}`;
  }

  // A [1 2 1] blur of a field of W x H values, along both directions,
  // `passes` times: about a Gaussian of half a pixel per pass.
  function blurField(values, W, H, passes) {
    const temporary = new Float32Array(values.length);
    for (let pass = 0; pass < passes; pass++) {
      for (let y = 0; y < H; y++) {
        const row = y * W;
        for (let x = 0; x < W; x++) {
          const left = values[row + Math.max(0, x - 1)], right = values[row + Math.min(W - 1, x + 1)];
          temporary[row + x] = 0.25 * left + 0.5 * values[row + x] + 0.25 * right;
        }
      }
      for (let y = 0; y < H; y++) {
        const above = Math.max(0, y - 1) * W, here = y * W, below = Math.min(H - 1, y + 1) * W;
        for (let x = 0; x < W; x++) values[here + x] = 0.25 * temporary[above + x] + 0.5 * temporary[here + x] + 0.25 * temporary[below + x];
      }
    }
    return values;
  }

  // A moving mean of `radius` values on each side.
  function smoothLine(values, radius) {
    if (radius < 1) return values;
    const out = new Float32Array(values.length);
    for (let i = 0; i < values.length; i++) {
      let sum = 0, n = 0;
      for (let d = -radius; d <= radius; d++) {
        const j = i + d;
        if (j >= 0 && j < values.length) { sum += values[j]; n++; }
      }
      out[i] = sum / n;
    }
    return out;
  }

  // The sky along the route, painted pixel by pixel then smoothed, as the
  // smooth style of plot_utils.plot_sky: the sky by day or night,
  // stratiform layers with ragged edges, Cu as domes, Cb as towers with an
  // anvil, Ci as hooked strokes, then rain, snow, lightning and fog.
  function drawSky(frame, route, sky) {
    const ratio = printing ? 2 : window.devicePixelRatio || 1;
    const daySky = printing ? PRINT_SKY.day : DAY_SKY, nightSky = printing ? PRINT_SKY.night : NIGHT_SKY;
    const cloudLit = printing ? PRINT_SKY.lit : CLOUD_LIT, cloudShade = printing ? PRINT_SKY.shade : CLOUD_SHADE;
    const left = frame.left, width = frame.right - frame.left;
    const top = frame.top, height = frame.bottom - frame.top;
    const W = Math.max(60, Math.min(1600, Math.round(width * ratio))), H = Math.max(40, Math.round(height * ratio));
    const count = route.ctim.length;
    const nodes = route.tim;
    // Each pixel column: its segment, its position in segments, its light.
    const column = new Int32Array(W), phase = new Float32Array(W);
    let daylight = new Float32Array(W);
    for (let px = 0, k = 0; px < W; px++) {
      const t = frame.t0 + ((px + 0.5) / W) * (frame.t1 - frame.t0);
      while (k < count - 1 && t > nodes[k + 1]) k++;
      const f = Math.max(0, Math.min(1, (t - nodes[k]) / (nodes[k + 1] - nodes[k])));
      column[px] = k;
      phase[px] = k + f;
      const lat = route.lat[k] + f * (route.lat[k + 1] - route.lat[k]);
      const lon = route.lon[k] + f * (route.lon[k + 1] - route.lon[k]);
      daylight[px] = smoothstep(TWILIGHT[0], TWILIGHT[1], sunElevation(t, lat, lon));
    }
    const perColumn = W / count;
    daylight = smoothLine(daylight, Math.round(0.1 * perColumn));
    const rowOf = (py) => 3 * (1 - (py + 0.5) / H);
    const shade = new Float32Array(W * H), weightSum = new Float32Array(W * H), transmitted = new Float32Array(W * H).fill(1);
    const over = (index, opacity, darkness) => {
      if (opacity <= 0.002) return;
      shade[index] += opacity * darkness;
      weightSum[index] += opacity;
      transmitted[index] *= 1 - Math.min(1, opacity);
    };
    const genera = scene.cloud_genera || [];
    const etageOf = {};
    genera.forEach((genus) => { etageOf[genus.abbreviation] = genus.etage; });
    const covers = { low: sky.lcc, middle: sky.mcc, high: sky.hcc };
    const present = { low: [], middle: [], high: [] };
    for (let k = 0; k < count; k++) ["low", "middle", "high"].forEach((etage) => present[etage].push(genusPresent(sky, etage, k)));
    const baseKm = sky.base.map((value) => Math.max(0.05, Math.min(2.5, value === null ? 0.6 : value / 1000)));
    const random = seeded(7);
    const strokes = [];
    // One heaped cloud: flat base, rounded top of three lobes, darker under.
    const dome = (center, half, base, summit, opacity, darkness) => {
      const depth = Math.max(summit - base, 1e-3);
      for (let px = 0; px < W; px++) {
        const dx = (phase[px] - center) / half;
        if (Math.abs(dx) > 1.4) continue;
        for (let py = 0; py < H; py++) {
          const rel = (rowOf(py) - base) / depth;
          if (rel < -0.05 || rel > 1.3) continue;
          const up = Math.max(rel, 0);
          const distance = Math.min(Math.hypot(dx, up), Math.hypot((dx + 0.55) / 0.6, up / 0.75), Math.hypot((dx - 0.5) / 0.65, up / 0.8));
          const inside = (1 - smoothstep(0.88, 1, distance)) * smoothstep(-0.02, 0.01, rel);
          over(py * W + px, opacity * inside, darkness + 0.4 * (1 - Math.min(1, up)));
        }
      }
    };
    let seed = 0;
    Object.entries(SKY_LAYERS).forEach(([genus, [bottom, topKm, opacity, darkness, texture]]) => {
      seed++;
      const etage = etageOf[genus];
      if (!etage) return;
      const here = present[etage].map((list) => list.includes(genus));
      if (!here.some(Boolean)) return;
      const cover = (k) => Math.max(0, Math.min(1, genus === "Cb" ? Math.max(covers[etage][k] || 0, 0.6) : covers[etage][k] || 0));
      const bottomOf = (k) => (bottom === "base" ? baseKm[k] : bottom);
      const topOf = (k) => {
        if (topKm === "cape") return bottomOf(k) + Math.max(0.5, Math.min(5, 0.5 + (sky.cape[k] || 0) / 600));
        if (genus === "St" || genus === "Sc") return bottomOf(k) + topKm;
        return topKm;
      };
      if (texture === "puffs") {
        here.forEach((on, k) => {
          if (!on) return;
          for (let n = 0; n < 1 + Math.round(2 * cover(k)); n++) {
            const depth = (topOf(k) - bottomOf(k)) * (0.55 + 0.45 * random());
            dome(k + 0.5 + (random() - 0.5) * 0.8, (0.35 + 0.2 * random()) * (0.75 + 0.5 * cover(k)), kmToRow(bottomOf(k)), kmToRow(bottomOf(k) + depth), opacity, 0.08);
          }
        });
        return;
      }
      if (texture === "tower") {
        here.forEach((on, k) => {
          if (!on) return;
          for (let lobe = 0; lobe < 4; lobe++) dome(k + 0.5 + (random() - 0.5) * 0.3, 0.7 - 0.08 * lobe, kmToRow(bottomOf(k)), kmToRow(9 + 0.4 * lobe), opacity, 0.35);
          // The anvil, spreading downwind at the top of the tower.
          const anvil = kmToRow(10.3), ceiling = kmToRow(11);
          for (let px = 0; px < W; px++) {
            const dx = (phase[px] - (k + 1)) / 1.5;
            if (Math.abs(dx) > 1) continue;
            for (let py = 0; py < H; py++) {
              const row = rowOf(py);
              const inside = (1 - smoothstep(0.85, 1, Math.hypot(dx, (row - anvil) / 0.13))) * (1 - smoothstep(ceiling - 0.02, ceiling, row));
              over(py * W + px, 0.95 * inside, 0.15);
            }
          }
        });
        return;
      }
      if (texture === "fibres") {
        // As many strokes per segment as its width allows.
        const scale = Math.min(1, perColumn / ratio / 14);
        here.forEach((on, k) => {
          if (!on) return;
          const wanted = (1 + 4 * cover(k)) * scale;
          const strokesHere = Math.floor(wanted) + (random() < wanted % 1 ? 1 : 0);
          for (let s = 0; s < strokesHere; s++) {
            const x = k + 0.5 + (random() - 0.5) * 0.8;
            strokes.push({ x, row: kmToRow(bottomOf(k) + (topOf(k) - 0.5 - bottomOf(k)) * random()), light: daylight[Math.min(W - 1, Math.max(0, Math.floor((x / count) * W)))] });
          }
        });
        return;
      }
      // Stratiform layers: weights spread along the route, ragged edges,
      // heights carried over the gaps from the nearest segment with them.
      const nearest = here.map((_, k) => {
        for (let d = 0; d < count; d++) {
          if (here[k - d]) return k - d;
          if (here[k + d]) return k + d;
        }
        return k;
      });
      const raw = new Float32Array(W);
      for (let px = 0; px < W; px++) raw[px] = here[column[px]] ? cover(column[px]) : 0;
      const spread = smoothLine(raw, Math.max(1, Math.round(0.35 * perColumn)));
      const crisp = texture !== "veil";
      const edge = crisp ? 0.02 : 0.12;
      for (let px = 0; px < W; px++) {
        const weight = raw[px];
        const presentHere = smoothstep(0.15, 0.5, spread[px] + 0.15 * noise(phase[px], seed + 30, 2.0));
        if (presentHere <= 0.002) continue;
        const k = nearest[column[px]];
        let low = kmToRow(bottomOf(k)), high = kmToRow(Math.max(topOf(k), bottomOf(k) + 0.2));
        let presence = presentHere;
        if (texture === "rolls") {
          presence *= smoothstep(1 - 1.5 * weight - 0.1, 1 - 1.5 * weight + 0.1, 0.5 + 0.5 * noise(phase[px], seed, 2.5));
          high += 0.035 * noise(phase[px], seed + 10, 1.5);
          low += 0.01 * noise(phase[px], seed + 20, 2.0);
        } else {
          high += (crisp ? 0.025 : 0.01) * noise(phase[px], seed + 10, 2.0);
          low += (genus === "Ns" ? 0.035 : 0.008) * noise(phase[px], seed + 20, 1.0);
        }
        high = low + (high - low) * (0.35 + 0.65 * presentHere);
        const depth = Math.max(high - low, 1e-3);
        for (let py = 0; py < H; py++) {
          const rel = (rowOf(py) - low) / depth;
          if (rel < -0.05 || rel > 1.05) continue;
          const profile = smoothstep(0, edge / depth, rel) * (1 - smoothstep(1 - edge / depth, 1, rel));
          over(py * W + px, opacity * (0.55 + 0.45 * weight) * presence * profile, darkness + 0.3 * (1 - Math.max(0, Math.min(1, rel))));
        }
      }
    });

    // Opacity and darkness smoothed, then the clouds over the sky, lit by
    // day, and the haze of fog rising from the sea.
    const alpha = new Float32Array(W * H), dark = new Float32Array(W * H);
    for (let index = 0; index < W * H; index++) {
      alpha[index] = 1 - transmitted[index];
      dark[index] = (weightSum[index] > 1e-6 ? Math.min(1, shade[index] / weightSum[index]) : 0) * alpha[index];
    }
    const passes = Math.max(1, Math.round(2 * ratio));
    blurField(alpha, W, H, passes);
    blurField(dark, W, H, passes);
    const fog = new Float32Array(W);
    for (let px = 0; px < W; px++) fog[px] = sky.fog[column[px]] ? 1 : 0;
    const haze = smoothLine(fog, Math.round(0.3 * perColumn));
    const image = new ImageData(W, H);
    const pixels = image.data;
    for (let py = 0; py < H; py++) {
      const level = 1 - (py + 0.5) / H;
      const near = 1 - smoothstep(0, 0.25, 3 * level);
      for (let px = 0; px < W; px++) {
        const light = daylight[px], index = py * W + px;
        const a = Math.min(1, alpha[index]);
        const opacity = Math.pow(a, 0.85);
        const darkness = a > 1e-6 ? Math.min(1, dark[index] / a) : 0;
        const mist = 0.85 * haze[px] * near;
        for (let c = 0; c < 3; c++) {
          const day = daySky[0][c] * (1 - level) + daySky[1][c] * level;
          const night = nightSky[0][c] * (1 - level) + nightSky[1][c] * level;
          const background = night * (1 - light) + day * light;
          // On paper, clouds are grey on white, as dark by night as by day.
          const cloud = (cloudLit[c] * (1 - darkness) + cloudShade[c] * darkness) * (printing ? 1 : NIGHT_CLOUD_LIGHT + (1 - NIGHT_CLOUD_LIGHT) * light);
          const value = background * (1 - opacity) + cloud * opacity;
          pixels[4 * index + c] = Math.round(255 * Math.max(0, Math.min(1, value * (1 - mist) + FOG_COLOR[c] * (NIGHT_CLOUD_LIGHT + (1 - NIGHT_CLOUD_LIGHT) * light) * mist)));
        }
        pixels[4 * index + 3] = 255;
      }
    }
    const painted = document.createElement("canvas");
    painted.width = W;
    painted.height = H;
    painted.getContext("2d").putImageData(image, 0, 0);
    const c = frame.context;
    c.save();
    c.beginPath();
    c.rect(left, top, width, height);
    c.clip();
    c.imageSmoothingEnabled = true;
    c.drawImage(painted, left, top, width, height);
    const xAt = (position) => {
      const k = Math.max(0, Math.min(count - 1, Math.floor(position)));
      return frame.x(nodes[k] + (position - k) * (nodes[k + 1] - nodes[k]));
    };
    const yOf = (row) => frame.bottom - (row / 3) * height;
    const segment = width / count;
    // Cirrus: thin slanted filaments ending in a hook.
    c.lineCap = "round";
    c.lineWidth = 0.9;
    strokes.forEach((stroke) => {
      const x0 = xAt(stroke.x - 0.25), y0 = yOf(stroke.row), length = Math.max(5, 0.55 * segment);
      c.strokeStyle = printing ? `rgba(${PRINT_SKY.cirrus}, 0.6)` : `rgba(255, 255, 255, ${(0.5 * (NIGHT_CLOUD_LIGHT + (1 - NIGHT_CLOUD_LIGHT) * stroke.light)).toFixed(2)})`;
      c.beginPath();
      c.moveTo(x0, y0);
      c.quadraticCurveTo(x0 + 0.75 * length, y0 - 1.5, x0 + length, y0 - 4);
      c.stroke();
    });
    // Rain or snow under the clouds, lightning under the Cb.
    const cb = genera.findIndex((genus) => genus.abbreviation === "Cb");
    for (let k = 0; k < count; k++) {
      if (sky.oktas[k] === null) continue;
      const clouded = present.low[k].length || present.middle[k].length || present.high[k].length;
      const base = yOf(kmToRow(Math.max(0.1, baseKm[k])));
      const x0 = xAt(k), x1 = xAt(k + 1);
      if (clouded && sky.prate[k] >= RAIN_RATE) {
        const snow = sky.t2m[k] !== null && sky.t2m[k] < SNOW_TEMPERATURE;
        const drops = Math.min(16, Math.round((1 + 2 * sky.prate[k]) * Math.max(0.5, (x1 - x0) / 6)));
        c.strokeStyle = RAIN_COLOR;
        c.fillStyle = printing ? PRINT_SKY.snow : SNOW_COLOR;
        c.lineWidth = 0.9;
        for (let d = 0; d < drops; d++) {
          const x = x0 + (x1 - x0) * random();
          const y = base + (frame.bottom - base) * (0.05 + 0.85 * random());
          if (snow) { c.beginPath(); c.arc(x, y, 0.9, 0, 2 * Math.PI); c.fill(); }
          else { c.beginPath(); c.moveTo(x, y); c.lineTo(x - 0.8, y + 3); c.stroke(); }
        }
      }
      if (cb >= 0 && sky.low[k] === cb) {
        const x = (x0 + x1) / 2, drop = frame.bottom - base;
        c.strokeStyle = LIGHTNING_COLOR;
        c.lineWidth = 1.3;
        c.beginPath();
        c.moveTo(x + 1, base);
        c.lineTo(x - 2, base + drop * 0.45);
        c.lineTo(x + 1.5, base + drop * 0.55);
        c.lineTo(x - 1, frame.bottom);
        c.stroke();
      }
    }
    c.restore();
  }

  // ---- The panel ----

  let plotCursors = [];
  let plotsKey = null;

  function setPlots(open) {
    state.plotsOpen = open;
    if (open && state.panelOpen && narrow()) setPanel(false);
    $("plots").hidden = !open;
    document.body.classList.toggle("plots-open", open);
    const button = document.querySelector(".plots-control");
    if (button) {
      button.classList.toggle("active", open);
      button.title = open ? "Hide the plots of the route (G)" : "Plots of a route (G)";
    }
    rebuildPlots(true);
    persist();
  }

  function selectPlotRoute(id) {
    state.plotRoute = id;
    rebuildPlots();
    persist();
  }

  // Marks the route of the plots in the list of routes.
  function markPlotRoute() {
    const route = plotRoute();
    document.querySelectorAll(".route-row").forEach((row) => {
      row.classList.toggle("plotted", !!route && row.dataset.route === route.id);
    });
  }

  // Draws the plots again when what they show changes: the route, the
  // theme, the names or the width. The time alone only moves their cursor.
  function rebuildPlots(force) {
    markPlotRoute();
    if (!state.plotsOpen) { plotsKey = null; plotCursors = []; return; }
    const route = plotRoute();
    const routes = shownRoutes().map((item) => `${item.id}:${routeLabel(item)}`).join(",");
    const key = [route && route.id, state.theme, $("plots").clientWidth, routes].join("|");
    if (!force && key === plotsKey) return;
    plotsKey = key;
    buildPlots();
  }

  // Builds the plots of the route: drawn once for a route and a width,
  // the time only moves their cursor and changes their values.
  function buildPlots() {
    const box = $("plots");
    plotCursors = [];
    if (!state.plotsOpen) return;
    const route = plotRoute();
    box.innerHTML = "";
    const head = element("div", "plots-head");
    const routes = shownRoutes().length ? shownRoutes() : includedRoutes();
    if (route) {
      const swatch = element("i", "swatch line");
      swatch.style.background = route.color;
      const select = element("select");
      select.title = "Route of the plots, or click a route on the map";
      routes.forEach((item) => {
        const option = element("option", "", escapeHtml(routeLabel(item)));
        option.value = item.id;
        option.selected = item.id === route.id;
        select.append(option);
      });
      select.addEventListener("change", () => selectPlotRoute(select.value));
      head.append(swatch, select);
      const print = element("button", "text-button small", `${icon("print")}<span>Print report</span>`);
      print.type = "button";
      print.title = "A printable report of this route: its plots and comments, to save as a PDF";
      print.addEventListener("click", () => printReport(route));
      head.append(print);
    } else {
      head.append(element("span", "muted", "No route"));
    }
    const close = element("button", "icon-button small", icon("close"));
    close.type = "button";
    close.title = "Hide the plots (G)";
    close.addEventListener("click", () => setPlots(false));
    head.append(close);
    box.append(head);
    const body = element("div", "plots-body");
    box.append(body);
    if (!route) return;
    const shown = PLOTS.filter((plot) => plot.available(route));
    if (!shown.length) body.append(element("div", "empty", "No values along this route"));
    const drawn = [];
    shown.forEach((plot) => {
      const node = element("div", "plot");
      node.innerHTML = `<div class="plot-head"><span class="plot-title">${escapeHtml(plot.title)}</span><span class="plot-values"></span></div>`;
      const wrap = element("div", "plot-wrap");
      const canvas = element("canvas");
      canvas.style.height = `${plot.height}px`;
      const cursor = element("div", "plot-cursor");
      wrap.append(canvas, cursor);
      node.append(wrap);
      body.append(node);
      drawn.push({ plot, canvas, cursor, values: node.querySelector(".plot-values") });
      scrubbing(canvas, route);
    });
    const axis = element("div", "plots-axis");
    body.append(axis);
    // Drawn once laid out, so that the canvases have their size.
    drawn.forEach((item) => { item.frame = item.plot.draw(item.canvas, route); });
    const frame = drawn.length ? drawn[0].frame : null;
    if (frame) {
      const every = Math.max(1, Math.ceil(56 / ((frame.right - frame.left) / Math.max(1, (frame.t1 - frame.t0) / DAY))));
      let index = 0;
      for (let t = Math.ceil(frame.t0 / DAY) * DAY; t <= frame.t1; t += DAY, index++) {
        if (index % every) continue;
        const date = new Date(t * 1000);
        const label = element("span", "", `${DAYS[date.getUTCDay()]} ${date.getUTCDate()}`);
        label.style.left = `${frame.x(t)}px`;
        axis.append(label);
      }
    }
    plotCursors = drawn.map((item) => ({ ...item, route }));
    updatePlotCursors();
  }

  // Clicking or dragging on a plot moves the time there.
  function scrubbing(canvas, route) {
    let dragging = false;
    const timeAt = (event) => {
      const box = canvas.getBoundingClientRect();
      const fraction = (event.clientX - box.left - PLOT_GUTTER) / Math.max(1, box.width - PLOT_GUTTER - 4);
      const t0 = route.tim[0], t1 = route.tim[route.tim.length - 1];
      return Math.round((t0 + Math.max(0, Math.min(1, fraction)) * (t1 - t0)) / 900) * 900;
    };
    canvas.addEventListener("pointerdown", (event) => {
      dragging = true;
      canvas.setPointerCapture(event.pointerId);
      pause();
      setTime(timeAt(event));
    });
    canvas.addEventListener("pointermove", (event) => { if (dragging) setTime(timeAt(event)); });
    const stop = () => { dragging = false; };
    canvas.addEventListener("pointerup", stop);
    canvas.addEventListener("pointercancel", stop);
  }

  function updatePlotCursors() {
    if (!plotCursors.length) return;
    const route = plotCursors[0].route;
    const k = plotSegment(route);
    plotCursors.forEach((item) => {
      const on = k >= 0 && item.frame;
      item.cursor.hidden = !on;
      if (on) item.cursor.style.left = `${item.frame.x(state.t)}px`;
      item.values.innerHTML = on ? item.plot.readout(route, k) : '<span class="muted">off the route at this time</span>';
    });
  }

  // ---- The printed report ----

  // The mean of a series over the route, weighted by the duration of its
  // segments, and its extremes; null without values.
  function seriesMean(route, values) {
    let sum = 0, weight = 0;
    (values || []).forEach((value, k) => {
      if (value === null || value !== value) return;
      const dt = route.tim[k + 1] - route.tim[k];
      sum += value * dt;
      weight += dt;
    });
    return weight > 0 ? sum / weight : null;
  }

  function seriesExtremes(values) {
    const numbers = (values || []).filter((value) => value !== null && value === value);
    return numbers.length ? [Math.min(...numbers), Math.max(...numbers)] : [null, null];
  }

  function formatDuration(seconds) {
    const hours = Math.round(seconds / HOUR);
    return hours < 48 ? `${hours} h` : `${Math.floor(hours / 24)} d ${hours % 24} h`;
  }

  // The figures at the top of the report: the voyage, then the extremes
  // of the weather and of the vessel along it.
  function reportFacts(route) {
    const summary = route.summary || {};
    const facts = [];
    const add = (label, value) => { if (value !== null && value !== undefined && value !== "") facts.push([label, String(value)]); };
    const fixed = (value, digits, unit) => (value === null || value === undefined ? null : `${value.toFixed(digits)} ${unit}`);
    const max = (name) => seriesExtremes(series(route, name))[1];
    add("Fuel", fixed(summary.fuel, 1, "t"));
    add("Distance", fixed(summary.distance, 0, "nm"));
    add("Mean SOG", fixed(summary.sog, 1, "kt"));
    add("Duration", formatDuration(route.eta - route.etd));
    add("Departure", formatDate(route.etd));
    add("Arrival", formatDate(route.eta));
    add("Vessel", summary.vessel);
    // The member only where the file holds several of them.
    const members = new Set(scene.routes.map((item) => String((item.summary || {}).member)));
    const member = members.size > 1 && summary.member !== null && summary.member !== undefined ? `, member ${summary.member}` : "";
    add("Forecast", summary.model ? `${String(summary.model).toUpperCase()}${member}` : null);
    if (summary.solve !== null && summary.solve !== undefined) {
      add("Route", Number(summary.solve) ? (summary.status === 2 ? "optimized, not converged" : "optimized") : "reference, not optimized");
    }
    add("Mean consumption", fixed(seriesMean(route, series(route, "hourly_consumption")), 0, "L/h"));
    add("Max power", fixed(seriesExtremes(series(route, "bhp") || series(route, "total_power"))[1], 0, "kW"));
    add("Mean sails", fixed(seriesMean(route, series(route, "sails_contribution")), 0, "% of the thrust"));
    const wind = max("tws"), gust = max("tws_gust");
    if (wind !== null) add("Max true wind", `${wind.toFixed(0)} kt${gust !== null ? `, gusts ${gust.toFixed(0)} kt` : ""}`);
    add("Max Hs", fixed(max("swh"), 1, "m"));
    const [low, high] = seriesExtremes(series(route, "pressure"));
    if (low !== null) add("Pressure", `${low.toFixed(0)} to ${high.toFixed(0)} hPa`);
    if (summary.max_z !== null && summary.max_z > 0) add("Warning", "touches land or an exclusion zone");
    return facts;
  }

  // What the colours of a printed plot stand for.
  function reportLegend(plot, route) {
    const key = (color, label, dashed) => `<span class="key"><i class="${dashed ? "dashed" : ""}" style="--key:${color}"></i>${label}</span>`;
    const fg = cssColor("--fg");
    if (plot.id === "speed") {
      return (series(route, "sog") ? key(PLOT_COLORS.sog, "SOG") : "") + (series(route, "stw") ? key(PLOT_COLORS.stw, "STW") : "");
    }
    if (plot.id === "sails") return key(PLOT_COLORS.sails, "share of the thrust");
    if (plot.id === "power") {
      const parts = powerParts(route);
      return (parts.hasPropulsion ? key(PLOT_COLORS.propulsion, "propulsion") : "") + (parts.hasHotel ? key(PLOT_COLORS.hotel, "hotel load") : "") +
        key(fg, "total") + (parts.fluctuation ? key(fg, "fluctuation", true) : "");
    }
    if (plot.id === "tws" || plot.id === "aws") {
      return key(scaleColor("wind", 15) || PLOT_COLORS.wind, "mean") + (series(route, `${plot.id}_gust`) ? key(fg, "gusts", true) : "");
    }
    if (plot.id === "swh") return key(scaleColor("waves", 2) || PLOT_COLORS.waves, "significant height");
    if (plot.id === "pressure") return key(scaleColor("pressure", 1013) || PLOT_COLORS.pressure, "mean sea level");
    return "";
  }

  // The comments on a printed plot: a dashed line at the time of each, its
  // number at the top, labels moved down a row where they would overlap.
  function markComments(frame, route, comments) {
    const c = frame.context;
    c.save();
    c.strokeStyle = PRINT_MARK;
    c.lineWidth = 0.8;
    c.setLineDash([3, 2]);
    comments.forEach((item) => {
      const x = frame.x(route.ctim[item.k]);
      c.beginPath(); c.moveTo(x, frame.top); c.lineTo(x, frame.bottom); c.stroke();
    });
    c.setLineDash([]);
    c.font = "600 8px system-ui, sans-serif";
    c.textAlign = "center";
    c.textBaseline = "middle";
    const rows = [];
    comments.forEach((item, index) => {
      const x = frame.x(route.ctim[item.k]), text = String(index + 1);
      const width = Math.max(11, c.measureText(text).width + 6), height = 11;
      let row = rows.findIndex((right) => x - width / 2 > right + 1);
      if (row < 0) { row = rows.length; rows.push(-Infinity); }
      rows[row] = x + width / 2;
      const y = frame.top + 1 + row * (height + 1);
      c.beginPath();
      c.roundRect(x - width / 2, y, width, height, 3);
      c.fillStyle = "#fff";
      c.fill();
      c.stroke();
      c.fillStyle = PRINT_MARK;
      c.fillText(text, x, y + height / 2 + 0.5);
    });
    c.restore();
  }

  // The plots of a route as images, drawn on white with light fills, in
  // the light theme whatever the page shows, with the comments marked.
  function reportPlots(route, comments) {
    const root = document.documentElement, theme = root.dataset.theme;
    const box = element("div");
    box.style.cssText = `position:fixed;left:${-2 * PRINT_WIDTH}px;top:0;width:${PRINT_WIDTH}px;visibility:hidden`;
    document.body.append(box);
    root.dataset.theme = "light";
    printing = true;
    try {
      return PLOTS.filter((plot) => plot.available(route)).map((plot) => {
        const canvas = element("canvas");
        canvas.style.cssText = `display:block;width:${PRINT_WIDTH}px;height:${plot.height}px`;
        box.append(canvas);
        const frame = plot.draw(canvas, route);
        markComments(frame, route, comments);
        return { plot, frame, legend: reportLegend(plot, route), image: canvas.toDataURL("image/png") };
      });
    } finally {
      printing = false;
      if (theme === undefined) delete root.dataset.theme;
      else root.dataset.theme = theme;
      box.remove();
    }
  }

  const REPORT_STYLE = `
    @page { size: A4; margin: 12mm; }
    * { box-sizing: border-box; }
    html, body { margin: 0; background: #fff; color: #1d2125; }
    body { font: 10pt/1.35 system-ui, -apple-system, "Segoe UI", sans-serif; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .eyebrow { color: #5d6670; font-size: 8.5pt; text-transform: uppercase; letter-spacing: 0.06em; }
    h1 { display: flex; align-items: center; gap: 8px; margin: 2px 0 4px; font-size: 16pt; }
    h1 i { width: 18px; height: 0; border-top: 5px solid var(--route); border-radius: 3px; flex: none; }
    h2 { font-size: 11pt; margin: 14px 0 6px; }
    .description { margin: 0 0 8px; white-space: pre-wrap; }
    .facts { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px 12px; margin: 8px 0 12px; padding: 8px 0; border-top: 1px solid #d5d9dd; border-bottom: 1px solid #d5d9dd; }
    .facts div { min-width: 0; }
    .facts span { display: block; color: #5d6670; font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.04em; }
    .facts b { font-weight: 600; }
    figure { margin: 0 0 6px; break-inside: avoid; }
    figcaption { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; font-size: 8.5pt; margin-bottom: 1px; }
    figcaption .unit { color: #5d6670; }
    .key { display: inline-flex; align-items: center; gap: 4px; color: #5d6670; }
    .key i { width: 12px; height: 0; border-top: 2.5px solid var(--key); }
    .key i.dashed { border-top-style: dashed; border-top-width: 1.5px; }
    img { display: block; width: 100%; }
    .axis { position: relative; height: 14px; font-size: 8pt; color: #5d6670; break-before: avoid; }
    .axis span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
    ol { list-style: none; margin: 0; padding: 0; }
    li { display: grid; grid-template-columns: 22px 1fr; gap: 2px 8px; padding: 5px 0; border-bottom: 1px solid #e6e9ec; break-inside: avoid; }
    .number { grid-row: span 2; align-self: start; display: flex; align-items: center; justify-content: center; height: 16px; border: 1px solid ${PRINT_MARK}; border-radius: 4px; color: ${PRINT_MARK}; font-weight: 600; font-size: 8.5pt; }
    .when { color: #5d6670; font-size: 8.5pt; }
    .text { white-space: pre-wrap; }
    footer { margin-top: 14px; color: #8a929a; font-size: 7.5pt; }
  `;

  // The report of a route as a document to print: its name and figures,
  // its plots with the comments numbered, then the comments themselves.
  function reportDocument(route) {
    const comments = routeComments(route);
    const plots = reportPlots(route, comments);
    const label = routeLabel(route), description = routeDescription(route).trim();
    const facts = reportFacts(route).map(([name, value]) => `<div><span>${escapeHtml(name)}</span><b>${escapeHtml(value)}</b></div>`).join("");
    const figures = plots.map((item) =>
      `<figure><figcaption><b>${escapeHtml(item.plot.title)}</b><span class="unit">${escapeHtml(item.plot.unit)}</span>${item.legend}</figcaption>` +
      `<img src="${item.image}" alt="${escapeHtml(item.plot.title)}"></figure>`).join("");
    let axis = "";
    if (plots.length) {
      const frame = plots[0].frame;
      for (let t = Math.ceil(frame.t0 / DAY) * DAY; t <= frame.t1; t += DAY) {
        const date = new Date(t * 1000);
        axis += `<span style="left:${((100 * frame.x(t)) / PRINT_WIDTH).toFixed(2)}%">${DAYS[date.getUTCDay()]} ${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}</span>`;
      }
    }
    const notes = comments.map((item, index) =>
      `<li><span class="number">${index + 1}</span><span class="when">${escapeHtml(formatTime(route.ctim[item.k]))} · ${escapeHtml(formatPosition(route.clat[item.k], route.clon[item.k]))}</span>` +
      `<span class="text">${escapeHtml(item.text)}</span></li>`).join("");
    const title = (scene.title || "").trim();
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${escapeHtml(label)} report</title><style>${REPORT_STYLE}</style></head><body>` +
      `<header><div class="eyebrow">${title ? `${escapeHtml(title)} · ` : ""}Route report</div>` +
      `<h1 style="--route:${route.color}"><i></i>${escapeHtml(label)}</h1>` +
      (description ? `<p class="description">${escapeHtml(description)}</p>` : "") +
      `<div class="facts">${facts}</div></header>` +
      (figures ? `<section>${figures}<div class="axis">${axis}</div></section>` : "<p>No values along this route.</p>") +
      (notes ? `<section><h2>Comments</h2><ol>${notes}</ol></section>` : "") +
      `<footer>Times in UTC · printed ${escapeHtml(formatDate(Date.now() / 1000))} · Architeuthis</footer></body></html>`;
  }

  // Opens the print dialog on the report of a route, from which it can be
  // saved as a PDF; the frame holding it goes once printed.
  function printReport(route) {
    const previous = document.getElementById("print-frame");
    if (previous) previous.remove();
    const frame = element("iframe");
    frame.id = "print-frame";
    frame.title = "Route report";
    frame.setAttribute("aria-hidden", "true");
    frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
    frame.addEventListener("load", () => {
      const view = frame.contentWindow;
      view.addEventListener("afterprint", () => setTimeout(() => frame.remove(), 0));
      view.focus();
      view.print();
    }, { once: true });
    frame.srcdoc = reportDocument(route);
    document.body.append(frame);
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

  // Icons of the weather fields, drawn with lines in the colour of the
  // text on a 24 x 24 grid.
  const CLOUD = "M7 18a4 4 0 0 1-.4-7.98 5.5 5.5 0 0 1 10.6-1.4A4.7 4.7 0 0 1 17 18z";
  // The cloud smaller, lower or higher above a horizon.
  const smallCloud = (y) => `<path d="M2 21.5h20"/><path d="${CLOUD}" transform="translate(4.5 ${y}) scale(0.62)" vector-effect="non-scaling-stroke"/>`;
  const FIELD_ICONS = {
    wind: '<path d="M3 8h10a2.5 2.5 0 1 0-2.5-2.5M3 12h15a2.5 2.5 0 1 1-2.5 2.5M3 16h7"/>',
    gust: '<path d="M5 21V3M5 5l14 2.5v5L5 15M10 6v8M15 7v6"/>',
    waves: '<path d="M2 9q2.5-3 5 0t5 0 5 0 5 0M2 15q2.5-3 5 0t5 0 5 0 5 0"/>',
    current: '<path d="M3 17q2.5-3 5 0t5 0 5 0 5 0M4 9h14m-4-4 4 4-4 4"/>',
    pressure: '<circle cx="12" cy="12" r="9"/><path d="M12 12l4.5-4.5M7 12h1M12 7v1M16 12h1"/><circle cx="12" cy="12" r="1" fill="currentColor"/>',
    period: '<circle cx="12" cy="13.5" r="7.5"/><path d="M12 13.5V9.5M10 2.5h4M18.5 6.5l1.5-1.5"/>',
    slope: '<path d="M2 20h20M3 20c4-1 6-5 8-10 1.5-3.5 5-4.5 7-2.5 1.5 1.5.5 4-1.5 3.5"/>',
    temperature: '<path d="M14 14.5V5a2 2 0 0 0-4 0v9.5a4 4 0 1 0 4 0z"/><path d="M12 11v6"/>',
    dew: '<path d="M12 3s6 6.6 6 11a6 6 0 0 1-12 0c0-4.4 6-11 6-11z"/>',
    cape: '<path d="M13 2 4.5 13.5H11L10 22l8.5-11.5H12z"/>',
    precipitation: `<path d="${CLOUD}"/><path d="M8 20.5l-.7 1.5M12 20.5l-.7 1.5M16 20.5l-.7 1.5" transform="translate(0 -1)"/>`,
    ptype: '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9M10 4.5l2 2 2-2M10 19.5l2-2 2 2"/>',
    cloud: `<path d="${CLOUD}"/>`,
    clouds: `<path d="${CLOUD}"/><path d="M8 20.5l-.7 1.5M12 20.5l-.7 1.5M16 20.5l-.7 1.5" transform="translate(0 -1)"/>`,
    "cloud-low": smallCloud(8.8),
    "cloud-middle": smallCloud(3.8),
    "cloud-high": smallCloud(-1.2),
    none: '<circle cx="12" cy="12" r="8"/><path d="M6.5 17.5l11-11"/>',
    // Any other field: a mesh, as the data mode of an object in Blender.
    data: '<path d="M12 4.5 4.5 18.5h15z"/><circle cx="12" cy="4.5" r="2" fill="currentColor"/><circle cx="4.5" cy="18.5" r="2" fill="currentColor"/><circle cx="19.5" cy="18.5" r="2" fill="currentColor"/>',
  };
  // Names of forecast variables with the icon of a field.
  const FIELD_ICON_NAMES = {
    u10: "wind", v10: "wind", si10: "wind", i10fg: "gust", fg10: "gust", swh: "waves", mwp: "period", pp1d: "period",
    msl: "pressure", prmsl: "pressure", sp: "pressure", t2m: "temperature", sst: "temperature", thetao: "temperature",
    d2m: "dew", r: "dew", rh: "dew", r2: "dew", mucape: "cape", tprate: "precipitation", prate: "precipitation",
    tp: "precipitation", tcc: "cloud", lcc: "cloud-low", mcc: "cloud-middle", hcc: "cloud-high", uo: "current", vo: "current",
  };

  // The icon of a field: its own, that of its quantity, or a mesh.
  function fieldIcon(layer) {
    const info = scene.layers[layer] || {};
    const name = [layer, info.quantity].map((key) => (FIELD_ICONS[key] ? key : FIELD_ICON_NAMES[key])).find(Boolean) || (layer ? "data" : "none");
    return `<svg class="field-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${FIELD_ICONS[name]}</svg>`;
  }

  // The fields of a source, then none, in the order of the list.
  function layerChoices(source) {
    return includedLayers(source).concat([""]);
  }

  // Shows the field above (-1) or below (+1) the current one in the list.
  function stepLayer(direction) {
    const source = currentSource();
    if (!source) return;
    const choices = layerChoices(source);
    const index = choices.indexOf(state.layer || "");
    const next = Math.max(0, Math.min(choices.length - 1, (index < 0 ? 0 : index) + direction));
    if (choices[next] === (state.layer || "")) return;
    state.layer = choices[next];
    state.arrowKind = null;
    onFieldsChanged();
  }

  // The fields of the source, one per row as a list of Blender: an icon
  // of the field, its name and its unit, the field shown highlighted.
  function layerList(source) {
    const list = element("div", "uilist");
    list.setAttribute("role", "listbox");
    list.title = "Field shown: click, or ↑ and ↓";
    layerChoices(source).forEach((layer) => {
      const info = scene.layers[layer];
      const active = layer === (state.layer || "");
      const row = element("button", "uilist-row" + (active ? " active" : "") + (layer ? "" : " none"));
      row.type = "button";
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", active ? "true" : "false");
      row.innerHTML = layer
        ? `${fieldIcon(layer)}<span>${escapeHtml(info.label)}</span><span class="unit">${escapeHtml(info.unit || "")}</span>`
        : `${fieldIcon("")}<span>None</span>`;
      row.addEventListener("click", () => { state.layer = layer; state.arrowKind = null; onFieldsChanged(); });
      list.append(row);
    });
    return list;
  }

  // The other choices of the weather, a label on the left of each row.
  function weatherProperties(source) {
    const grid = element("div", "props");
    const row = (label, ...controls) => {
      grid.append(element("span", "prop-label", escapeHtml(label)));
      const cell = element("div", "prop-value");
      cell.append(...controls);
      grid.append(cell);
      return cell;
    };
    const kinds = availableArrows(source);
    if (kinds.length) {
      const arrows = segmented(kinds.map((kind) => [kind, ARROW_LABELS[kind]]).concat([["", "Off"]]), currentArrows(source) || "", (kind) => { state.arrowKind = kind; onFieldsChanged(); });
      arrows.classList.add("joined");
      row("Arrows", arrows);
    }
    if (source.quantities.pressure && includedLayers(source).includes("pressure")) {
      const steps = segmented(ISOBAR_STEPS.map((step) => [step, `${step} hPa`]), state.isobarStep, (step) => { state.isobarStep = step; onFieldsChanged(); });
      steps.classList.add("joined");
      if (!state.isobars) steps.classList.add("disabled");
      row("Isobars", checkbox("", state.isobars, (on) => { state.isobars = on; onFieldsChanged(); }), steps).classList.add("inline");
      const off = { disabled: !state.isobars };
      row("", checkbox("Pressure labels", state.isobarLabels, (on) => { state.isobarLabels = on; onFieldsChanged(); }, off));
      row("", checkbox("Highs and lows", state.centres, (on) => { state.centres = on; onFieldsChanged(); }, off));
    }
    const slider = element("input");
    slider.type = "range";
    slider.min = "0.1";
    slider.max = "1";
    slider.step = "0.05";
    slider.value = String(state.opacity);
    const shown = element("span", "prop-number", `${Math.round(100 * state.opacity)} %`);
    slider.addEventListener("input", () => {
      state.opacity = Number(slider.value);
      shown.textContent = `${Math.round(100 * state.opacity)} %`;
      map.setPaintProperty("field", "raster-opacity", state.opacity);
      persist();
    });
    row("Opacity", slider, shown).classList.add("inline");
    return grid;
  }

  function buildPanel() {
    const panel = $("panel");
    // Rebuilt at each choice: the panel stays where it was scrolled.
    const scroll = panel.scrollTop;
    panel.innerHTML = "";
    const source = currentSource();

    if (source) {
      const weather = section("Weather");
      const sources = includedSources();
      if (sources.length > 1) {
        const models = segmented(sources.map((s) => [s.id, s.label]), source.id, (id) => {
          state.source = id;
          state.layer = null;
          ensureSelection();
          onFieldsChanged();
        });
        models.classList.add("joined");
        weather.append(models);
      }
      weather.append(layerList(source));
      weather.append(weatherProperties(source));
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
      row.dataset.route = route.id;
      // A route clicked in the list is the route of the plots.
      row.addEventListener("click", (event) => { if (event.target !== input) selectPlotRoute(route.id); });
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
    markPlotRoute();

    if (scene.zones.length) {
      const zones = section("Exclusion zones");
      scene.zones.forEach((zone) => {
        const empty = zone.outline.length < 2;
        zones.append(checkbox(empty ? `${zone.label} (unavailable)` : zone.label, !empty && state.zones[zone.id], (on) => {
          state.zones[zone.id] = on;
          sendZones();
          persist();
          updateZones();
        }, { color: zone.color, line: true, disabled: empty }));
      });
      panel.append(zones);
    }

    const base = section("Map");
    if (OSM_ENABLED) base.append(segmented([["offline", "Offline map"], ["osm", "OpenStreetMap"]], state.basemap, (value) => {
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
        sendOverlays();
        persist();
      }));
    });
    panel.append(base);
    panel.scrollTop = scroll;
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
    // On a phone, the panel and the plots take the same place.
    if (open && state.plotsOpen && narrow()) setPlots(false);
    persist();
  }

  function narrow() { return window.innerWidth <= 720; }

  // --------------------------------------------------------------------
  // Widths of the panels, dragged by their inner edge
  // --------------------------------------------------------------------

  const PANEL_WIDTHS = { panel: [240, 640], plots: [260, 800] };

  function clampWidth(kind, width) {
    const [low, high] = PANEL_WIDTHS[kind];
    const room = kind === "panel" ? window.innerWidth - 120 : window.innerWidth * 0.7;
    return Math.round(Math.max(low, Math.min(high, room, width)));
  }

  // The widths chosen, through variables that the stylesheet falls back
  // from, so that a phone keeps its own.
  function applyWidths() {
    const root = document.documentElement.style;
    ["panel", "plots"].forEach((kind) => {
      const width = state[kind + "Width"];
      if (width) root.setProperty(`--${kind}-width-user`, `${clampWidth(kind, width)}px`);
      else root.removeProperty(`--${kind}-width-user`);
    });
    placePanelHandle();
  }

  // The handle of the left panel follows its edge, below the header and
  // the note.
  function placePanelHandle() {
    const handle = document.querySelector(".panel-handle");
    if (!handle) return;
    const panel = $("panel");
    handle.style.top = `${panel.offsetTop}px`;
    handle.style.height = `${panel.offsetHeight}px`;
    handle.style.left = `${panel.offsetLeft + panel.offsetWidth - 4}px`;
  }

  function setupResizers() {
    const panelHandle = element("div", "resize-handle panel-handle");
    const plotsHandle = element("div", "resize-handle plots-handle");
    panelHandle.title = "Drag to resize the panel, double-click for its first width";
    plotsHandle.title = "Drag to resize the plots, double-click for their first width";
    $("left").append(panelHandle);
    document.body.append(plotsHandle);
    resizer(panelHandle, "panel", (x) => x - $("panel").getBoundingClientRect().left);
    resizer(plotsHandle, "plots", (x) => $("plots").getBoundingClientRect().right - x);
    if (window.ResizeObserver) {
      const observer = new ResizeObserver(placePanelHandle);
      observer.observe($("panel"));
      observer.observe($("left"));
    }
    window.addEventListener("resize", applyWidths);
    applyWidths();
  }

  // Drags the width of a panel. The plots are stretched meanwhile and
  // drawn again once it is released.
  function resizer(handle, kind, measure) {
    let frame = null;
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      document.body.classList.add("resizing");
    });
    handle.addEventListener("pointermove", (event) => {
      if (!handle.hasPointerCapture(event.pointerId)) return;
      const width = measure(event.clientX);
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        state[kind + "Width"] = clampWidth(kind, width);
        applyWidths();
      });
    });
    handle.addEventListener("lostpointercapture", () => {
      document.body.classList.remove("resizing");
      rebuildPlots();
      persist();
    });
    handle.addEventListener("dblclick", () => {
      state[kind + "Width"] = null;
      applyWidths();
      persist();
    });
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
          sendOverlays();
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
    updatePlotCursors();
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
    rebuildPlots();
    scheduleRender(true);
    persist();
  }

  function onRoutesChanged() {
    buildPanel();
    buildTimeline();
    updateRoutes();
    showPopup();
    rebuildPlots();
    persist();
  }

  function refresh() {
    computeRange();
    state.t = Math.max(state.t0, Math.min(state.t1, state.t));
    ensureSelection();
    updateHeader();
    buildPanel();
    buildTimeline();
    rebuildPlots();
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
    const before = includedOverlays().filter((overlay) => state.overlays[overlay.id]);
    ["routes", "sources", "overlays", "hover", "fields"].forEach((key) => { if (key in settings) state.settings[key] = settings[key]; });
    if (settings.overlaysShown) Object.assign(state.overlays, settings.overlaysShown);
    if ("title" in settings) state.title = settings.title || scene.title;
    if ("note" in settings) state.note = settings.note || "";
    if ("editable" in settings) state.editable = !!settings.editable;
    if (settings.labels) state.labels = Object.assign({}, settings.labels);
    if (settings.descriptions) state.descriptions = Object.assign({}, settings.descriptions);
    if (settings.comments) state.comments = JSON.parse(JSON.stringify(settings.comments));
    if (settings.theme === "light" || settings.theme === "dark") applyTheme(settings.theme);
    refresh();
    // A chart the analyst has just shown is shown at its time.
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
      map.setPaintProperty("graticule", "line-color", colors.graticule);
      ["", DETAIL].forEach((suffix) => {
        map.setPaintProperty("land" + suffix, "fill-color", colors.land);
        COAST_LAYERS.forEach(([id]) => {
          map.setPaintProperty(id + suffix, "line-color", colors.coast);
          if (id !== "coast") map.setPaintProperty(id + suffix, "line-opacity", colors.coastShade);
        });
      });
    }
    rebuildPlots();
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

  function landData(level) {
    const quantum = level.quantum;
    return {
      type: "FeatureCollection",
      features: level.polygons.map((rings) => ({
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

  // Reads the finer land when the browser is idle, then draws the coarse
  // one only below DETAIL_ZOOM.
  function loadLandDetail() {
    if (!scene.land.detail) return;
    const idle = window.requestIdleCallback || ((callback) => setTimeout(callback, 200));
    idle(() => {
      const land = landData(scene.land.detail);
      map.getSource("land-detail").setData(land);
      map.getSource("coast-detail").setData(coastData(land));
      LAND_LAYERS.forEach((id) => map.setLayerZoomRange(id, 0, DETAIL_ZOOM));
    });
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
    const land = landData(scene.land);
    const sources = {
      land: geojson(land),
      coast: geojson(coastData(land)),
      "land-detail": geojson(),
      "coast-detail": geojson(),
      graticule: geojson(graticuleData()),
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        maxzoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
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
    SEAMARK_LEVELS.forEach(([zoom, size]) => {
      sources[`seamarks-${zoom}`] = {
        type: "raster",
        tiles: ["https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"],
        tileSize: size,
        minzoom: SEAMARK_ZOOM,
        maxzoom: 18,
        attribution: '© <a href="https://www.openseamap.org">OpenSeaMap</a> contributors',
      };
    });
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
    // Each land layer and its twin of the finer level, empty until it is read.
    const twins = (layer) => [layer, Object.assign({}, layer, { id: layer.id + DETAIL, source: layer.source + DETAIL, minzoom: DETAIL_ZOOM })];
    const line = (id, width, opacity, offset) => twins({
      id,
      type: "line",
      source: "coast",
      layout: round,
      paint: { "line-color": theme.coast, "line-width": zoomed(width), "line-opacity": opacity, "line-offset": zoomed(offset) },
    });
    COAST_LAYERS.forEach(([id, width]) => { if (id !== "coast") layers.push(...line(id, width, theme.coastShade, width / 2)); });
    layers.push(
      ...twins({ id: "land", type: "fill", source: "land", paint: { "fill-color": theme.land } }),
      ...line("coast", 0.5, COAST_OPACITY, 0)
    );
    layers.push({ id: "graticule", type: "line", source: "graticule", paint: { "line-color": theme.graticule, "line-width": GRATICULE_WIDTH } });
    SEAMARK_LEVELS.forEach(([zoom], index) => {
      const layer = { id: `seamarks-${zoom}`, type: "raster", source: `seamarks-${zoom}`, layout: hidden, minzoom: zoom, paint: { "raster-fade-duration": 0 } };
      if (index > 0) layer.maxzoom = zoom + 1;
      layers.push(layer);
    });
    scene.overlays.forEach((overlay) => {
      layers.push({ id: `overlay-${overlay.id}`, type: "raster", source: `overlay-${overlay.id}`, layout: hidden, paint: { "raster-opacity": overlay.opacity, "raster-fade-duration": 0 } });
    });
    layers.push(
      { id: "isobars", type: "line", source: "isobars", paint: { "line-color": ISOBAR_COLOR, "line-width": 0.9, "line-opacity": 0.7 } },
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
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 0.8 * ROUTE_POINT_SCALE, 5, 2 * ROUTE_POINT_SCALE, 8, 3.5 * ROUTE_POINT_SCALE],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 4, 0, 6, 0.9 * ROUTE_POINT_SCALE],
        },
      },
      { id: "route-hit", type: "circle", source: "route-points", paint: { "circle-radius": Math.max(9, 4 * ROUTE_POINT_SCALE), "circle-opacity": 0 } },
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
    setupResizers();
    setPlots(state.plotsOpen);
    if (window.ResizeObserver) {
      new ResizeObserver(() => { if (!document.body.classList.contains("resizing")) rebuildPlots(); }).observe($("plots"));
    }

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
        const plots = element("button", "plots-control" + (state.plotsOpen ? " active" : ""), icon("plots"));
        plots.type = "button";
        plots.title = state.plotsOpen ? "Hide the plots of the route (G)" : "Plots of a route (G)";
        plots.setAttribute("aria-label", "Plots of a route");
        plots.addEventListener("click", () => setPlots(!state.plotsOpen));
        this.box.append(button, plots);
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
          rebuildPlots();
          scheduleRender(true);
        })
        .catch((error) => fail(`The forecast could not be read: ${error && error.message ? error.message : error}`));
      if (!scene.sources.length) $("loading").hidden = true;
      scheduleRender(true);
      map.once("idle", loadLandDetail);
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
      else if (event.key === "ArrowUp" || event.key === "ArrowDown") { stepLayer(event.key === "ArrowUp" ? -1 : 1); event.preventDefault(); }
      else if (event.key === "l" || event.key === "L") setPanel(!state.panelOpen);
      else if (event.key === "p" || event.key === "P") togglePicker();
      else if (event.key === "g" || event.key === "G") setPlots(!state.plotsOpen);
      else if (event.key === "t" || event.key === "T") toggleTheme();
      else if (event.key === "Escape") { state.popup = null; showPopup(); closeEditor(); if (window.innerWidth <= 720) { setPanel(false); if (state.plotsOpen) setPlots(false); } }
    });

    // For the browser console and automated checks.
    window.architeuthisViewer = { map, state, scene, setTime, applySettings, applyTheme, setPicker, reportDocument, printReport };

    window.addEventListener("message", (event) => {
      const data = event.data;
      if (data && data.type === "architeuthis:settings" && data.settings) applySettings(data.settings);
    });
    if (window.parent !== window) {
      try { window.parent.postMessage({ type: "architeuthis:ready" }, "*"); } catch (error) { /* not embedded */ }
      sendZones();
    }
  }

  start();
})();
