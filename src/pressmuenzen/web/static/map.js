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
    if (cfg.botUsername) {
      html += '<div class="popup-correct"><a href="#" class="correct-link" data-id="' +
        p.id + '">Standort korrigieren</a></div>';
    }
    return html;
  }

  // --- Coordinate correction: click-to-pick + address-search mode -----------

  // Encode lat/lon as integers (x1e6) for a Telegram deep-link start payload.
  // Negative values get an "n" prefix; hyphens adjacent to underscores interact
  // poorly with some Telegram clients so we avoid them.
  function encodeCoord(v) {
    var i = Math.round(v * 1e6);
    return i < 0 ? "n" + (-i) : String(i);
  }

  // Payload format: fix_<id>_<lat6>_<lon6>  (max ~31 chars, well under the 64-char limit)
  function deepLinkPayload(machineId, lat, lon) {
    return "fix_" + machineId + "_" + encodeCoord(lat) + "_" + encodeCoord(lon);
  }

  var editState = null; // null | { machineId, pendingMarker }

  var pickHint = (function () {
    var el = document.createElement("div");
    el.id = "pick-hint";
    el.innerHTML =
      '<div class="pick-hint-row">' +
        'Klicke auf die korrekte Position' +
        ' &nbsp;<button id="pick-cancel">Abbrechen</button>' +
      '</div>' +
      '<div class="pick-hint-row">' +
        '<span class="pick-or">oder</span>' +
        '<input id="addr-input" class="addr-input" type="text"' +
          ' placeholder="Adresse eingeben…" autocomplete="off" />' +
        '<button id="addr-search" class="addr-btn">Suchen</button>' +
      '</div>' +
      '<div id="addr-error" class="addr-error"></div>';
    document.body.appendChild(el);
    el.style.display = "none";
    document.getElementById("pick-cancel").addEventListener("click", cancelEdit);
    document.getElementById("addr-search").addEventListener("click", searchAddress);
    document.getElementById("addr-input").addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); searchAddress(); }
    });
    return el;
  }());

  var confirmOverlay = (function () {
    var el = document.createElement("div");
    el.id = "confirm-overlay";
    el.innerHTML =
      '<div id="confirm-box">' +
        '<div id="confirm-title">Korrigierte Position</div>' +
        '<div id="confirm-coords"></div>' +
        '<a id="confirm-link" href="#" target="_blank" rel="noopener">In Telegram bestätigen</a>' +
        '<button id="confirm-cancel">Abbrechen</button>' +
      '</div>';
    document.body.appendChild(el);
    el.style.display = "none";
    document.getElementById("confirm-cancel").addEventListener("click", cancelEdit);
    return el;
  }());

  function enterEditMode(machineId) {
    if (editState) cancelEdit();
    editState = { machineId: machineId, pendingMarker: null };
    map.closePopup();
    map.getContainer().classList.add("picking");
    pickHint.style.display = "block";
  }

  function cancelEdit() {
    if (!editState) return;
    if (editState.pendingMarker) map.removeLayer(editState.pendingMarker);
    editState = null;
    map.getContainer().classList.remove("picking");
    pickHint.style.display = "none";
    confirmOverlay.style.display = "none";
    document.getElementById("addr-input").value = "";
    document.getElementById("addr-error").textContent = "";
  }

  function placePickMarker(lat, lon) {
    if (editState.pendingMarker) map.removeLayer(editState.pendingMarker);
    editState.pendingMarker = L.marker([lat, lon], {
      icon: colorIcon("#e67e00"),
    }).addTo(map);
    map.panTo([lat, lon]);

    var payload = deepLinkPayload(editState.machineId, lat, lon);
    var href = "https://t.me/" + cfg.botUsername + "?start=" + payload;

    document.getElementById("confirm-coords").textContent =
      lat.toFixed(5) + ", " + lon.toFixed(5);
    document.getElementById("confirm-link").href = href;

    pickHint.style.display = "none";
    confirmOverlay.style.display = "flex";
  }

  map.on("click", function (e) {
    if (!editState) return;
    placePickMarker(e.latlng.lat, e.latlng.lng);
  });

  function searchAddress() {
    if (!editState) return;
    var q = document.getElementById("addr-input").value.trim();
    if (!q) return;
    var errEl = document.getElementById("addr-error");
    errEl.textContent = "";

    fetch("/api/geocode?" + new URLSearchParams({ q: q }))
      .then(function (r) {
        if (r.status === 404) throw new Error("not_found");
        if (!r.ok) throw new Error("error");
        return r.json();
      })
      .then(function (data) {
        placePickMarker(data.lat, data.lon);
      })
      .catch(function (e) {
        errEl.textContent = e.message === "not_found"
          ? "Adresse nicht gefunden."
          : "Fehler bei der Suche.";
      });
  }

  // Wire "Standort korrigieren" clicks via event delegation.
  document.addEventListener("click", function (e) {
    var el = e.target;
    if (!el.classList || !el.classList.contains("correct-link")) return;
    e.preventDefault();
    var machineId = el.getAttribute("data-id");
    if (machineId) enterEditMode(machineId);
  });

  // --- Render GeoJSON features -----------------------------------------------

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
}());
