// assets/marker-tooltip.js
// Note: depends on dash-leaflet creating Leaflet marker layers (it does).
// This code finds the marker with a particular lat/lon on init and attaches a listener.
// You may adapt selection logic to your app (e.g. search by icon, text, or layer order).

document.addEventListener('DOMContentLoaded', function() {
  // wait a little for dash-leaflet to initialise map/layers
  setTimeout(() => {
    // Find the Leaflet map object(s) created by dash-leaflet
    // dash-leaflet keeps maps in document.querySelectorAll('.leaflet-container')
    const mapEl = document.querySelector('.leaflet-container');
    if (!mapEl) return;

    // Access the global Leaflet map instance: react-leaflet/dash-leaflet
    // attaches the map to the DOM element as _leaflet_map (private, but stable in practice)
    const map = mapEl._leaflet_map;
    if (!map) return;

    // find a marker layer (this example assumes your marker is the first marker layer)
    let theMarker = null;
    map.eachLayer(layer => {
      if (!theMarker && layer instanceof L.Marker) {
        // heuristics: you can refine to match initial position or icon
        theMarker = layer;
      }
    });
    if (!theMarker) return;

    // Ensure the marker has a tooltip bound (if not, bind one)
    if (!theMarker.getTooltip()) {
      theMarker.bindTooltip("loading...", {permanent: false, direction: "top"});
    }

    // Update tooltip content while dragging (move event) and when drag ends
    function updateTooltipContent(ev) {
      const latlng = ev.latlng || theMarker.getLatLng();
      // optionally, format / compute locally; or request via fetch to your server
      const html = `<b>Lat</b> ${latlng.lat.toFixed(3)}<br><b>Lon</b> ${latlng.lng.toFixed(3)}`;
      // fastest direct API call:
      theMarker.getTooltip().setContent(html);
      // If you prefer popup:
      // if (theMarker.getPopup()) theMarker.getPopup().setContent(html);
    }

    theMarker.on('move', updateTooltipContent);   // continuous while dragging
    theMarker.on('dragend', updateTooltipContent); // ensure final value after drop
  }, 300);
});
