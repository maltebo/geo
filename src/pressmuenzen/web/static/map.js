/* Lightweight vanilla-JS Leaflet map. No build step, no SPA framework. */
(function () {
  const cfg = window.PM_CONFIG || {};

  // --- Marker appearance (tweak these) ---------------------------------------
  const MARKER_SIZE = 26;   // diameter in px of a machine dot
  const MARKER_BORDER = 3;  // white outline thickness in px
  const ORIGIN_SIZE = 32;   // the red "your location" dot is a bit larger

  const map = L.map("map").setView([51.0, 10.0], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap-Mitwirkende",
  }).addTo(map);

  const cluster = L.markerClusterGroup();
  map.addLayer(cluster);

  function colorIcon(color, size) {
    const d = size || MARKER_SIZE;
    return L.divIcon({
      className: "",
      html:
        '<div style="width:' + d + 'px;height:' + d + 'px;border-radius:50%;border:' +
        MARKER_BORDER + 'px solid #fff;box-shadow:0 0 4px 1px rgba(0,0,0,.6);' +
        'background:' + color + '"></div>',
      iconSize: [d, d],
      iconAnchor: [d / 2, d / 2],
    });
  }

  function escapeHtml(s) {
    return (s || "").replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function popupHtml(p) {
    let html = '<div class="popup-title">' + escapeHtml(p.name) + "</div>";
    if (p.is_limited) {
      html += '<div class="popup-warn">Möglicherweise nur zeitlich begrenzt!</div>';
    }
    html += "<div>ID: " + p.id + "</div>";
    if (p.distance_km != null) html += "<div>Distanz: " + p.distance_km + " km</div>";
    if (p.description) html += "<div>" + escapeHtml(p.description) + "</div>";
    html += '<div><a href="' + p.url + '" target="_blank" rel="noopener">Forum</a> · ';
    html += '<a href="' + p.maps_link + '" target="_blank" rel="noopener">Google Maps</a></div>';
    html += "<div>Quelle: " + escapeHtml(p.gps_source) + "</div>";
    return html;
  }

  function render(geojson) {
    const markers = [];
    geojson.features.forEach(function (f) {
      const c = f.geometry.coordinates; // [lon, lat]
      const p = f.properties;
      const m = L.marker([c[1], c[0]], { icon: colorIcon(p.color) }).bindPopup(popupHtml(p));
      cluster.addLayer(m);
      markers.push([c[1], c[0]]);
    });

    if (geojson.origin) {
      L.marker([geojson.origin.lat, geojson.origin.lon], {
        icon: colorIcon("red", ORIGIN_SIZE),
      }).addTo(map).bindPopup("Dein Standort");
      markers.push([geojson.origin.lat, geojson.origin.lon]);
    }

    if (markers.length) map.fitBounds(markers, { padding: [40, 40] });
  }

  if (cfg.embedded) {
    render(cfg.embedded);
  } else if (cfg.apiUrl) {
    fetch(cfg.apiUrl)
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function (e) { console.error("failed to load machines", e); });
  }
})();
