const fileInput = document.getElementById("file-input");
const dropZone = document.getElementById("drop-zone");
const preview = document.getElementById("preview");
const analyzeBtn = document.getElementById("analyze-btn");
const statusMsg = document.getElementById("status-msg");

const resultsSection = document.getElementById("results");
const verdictBadge = document.getElementById("verdict-badge");
const filenameDisplay = document.getElementById("filename-display");
const confDisplay = document.getElementById("conf-display");
const statusDisplay = document.getElementById("status-display");

const extractBtn = document.getElementById("extract-btn");
const ocrText = document.getElementById("ocr-text");
const gpsData = document.getElementById("gps-data");
const gpsWarning = document.getElementById("gps-warning");
const gpsSuccess = document.getElementById("gps-success");

// Standard HRMS Coordinates
const STANDARD_LAT = 13.007358;
const STANDARD_LON = 80.206321;

let selectedFile = null;
let map = null;
let actualMarker = null;

// Leaflet Map Initialization
function initMap() {
  if (map) return;
  map = L.map('map').setView([STANDARD_LAT, STANDARD_LON], 16);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; OpenStreetMap &copy; CARTO'
  }).addTo(map);

  // Draw the 100m expected boundary (Blue Circle)
  L.circle([STANDARD_LAT, STANDARD_LON], {
    color: '#3b82f6',
    fillColor: '#3b82f6',
    fillOpacity: 0.15,
    radius: 100 // 100 meters
  }).addTo(map);

  // Standard location marker
  L.circleMarker([STANDARD_LAT, STANDARD_LON], {
    radius: 4, color: '#3b82f6', fillOpacity: 1
  }).addTo(map).bindPopup("Expected Hospital Center");
}

// Calculate distance in meters (Haversine formula)
function getDistanceFromLatLonInM(lat1, lon1, lat2, lon2) {
  var R = 6371; // Radius of the earth in km
  var dLat = deg2rad(lat2 - lat1);
  var dLon = deg2rad(lon2 - lon1);
  var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
          Math.cos(deg2rad(lat1)) * Math.cos(deg2rad(lat2)) *
          Math.sin(dLon / 2) * Math.sin(dLon / 2);
  var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  var d = R * c * 1000; // Distance in meters
  return d;
}
function deg2rad(deg) { return deg * (Math.PI / 180); }

// Handle File Upload
dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault(); dropZone.classList.remove("dragover");
  if (e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    handleFile(fileInput.files[0]);
  }
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) handleFile(fileInput.files[0]);
});

function handleFile(file) {
  if (!file.type.startsWith("image/")) return;
  selectedFile = file;
  preview.src = URL.createObjectURL(file);
  preview.hidden = false;
  analyzeBtn.disabled = false;
  statusMsg.textContent = "";
}

// Step 1: Analyze Forgery
analyzeBtn.addEventListener("click", async () => {
  if (!selectedFile) return;
  analyzeBtn.disabled = true;
  statusMsg.textContent = "Analyzing via AI or Not Cloud API...";
  resultsSection.hidden = true;

  const formData = new FormData();
  formData.append("images", selectedFile); // Backend expects list, 1 item is fine

  try {
    const res = await fetch("/detect", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Detection failed.");
    
    // Parse the single result
    const fileKey = Object.keys(data.results)[0];
    const info = data.results[fileKey];

    filenameDisplay.textContent = fileKey;
    const confPct = (info.cloud_confidence * 100).toFixed(1);
    confDisplay.textContent = `${confPct}%`;
    
    if (info.cloud_confidence > 0.65) {
      verdictBadge.className = "verdict edited";
      verdictBadge.textContent = "FORGED";
      statusDisplay.textContent = "High confidence forgery detected.";
    } else if (info.cloud_confidence >= 0.50) {
      verdictBadge.className = "verdict likely-edited";
      verdictBadge.textContent = "LIKELY EDITED";
      statusDisplay.textContent = "Potential tampering detected.";
    } else {
      verdictBadge.className = "verdict unverified";
      verdictBadge.textContent = "UNVERIFIED";
      statusDisplay.textContent = "Cloud indicates authentic.";
    }

    // Setup Artifacts
    if (info.ela_map_url) {
      document.getElementById("ela-img").src = info.ela_map_url;
      document.getElementById("ela-fig").style.display = "block";
    }
    if (info.edge_map_url) {
      document.getElementById("edge-img").src = info.edge_map_url;
      document.getElementById("edge-fig").style.display = "block";
    }

    resultsSection.hidden = false;
    initMap(); // Init map when results are shown
    
    // Reset OCR states
    ocrText.textContent = "Click 'Extract Text & GPS' to run OCR.";
    gpsData.innerHTML = "";
    gpsWarning.style.display = "none";
    gpsSuccess.style.display = "none";
    if (actualMarker) { map.removeLayer(actualMarker); actualMarker = null; }

  } catch (err) {
    statusMsg.textContent = "Error: " + err.message;
  } finally {
    analyzeBtn.disabled = false;
    statusMsg.textContent = "Done.";
  }
});

// Step 2: Extract OCR & GPS
extractBtn.addEventListener("click", async () => {
  if (!selectedFile) return;
  extractBtn.disabled = true;
  extractBtn.textContent = "Extracting...";
  ocrText.textContent = "Running lightweight OCR...";
  gpsData.innerHTML = "";
  gpsWarning.style.display = "none";
  gpsSuccess.style.display = "none";

  const form = new FormData();
  form.append("image", selectedFile);
  form.append("side", "center");

  try {
    const res = await fetch("/extract-text", { method: "POST", body: form });
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || "OCR failed");
    
    ocrText.textContent = json.text || "No text detected.";
    
    if (json.latitude && json.longitude) {
      const lat = parseFloat(json.latitude);
      const lon = parseFloat(json.longitude);
      
      gpsData.innerHTML = `📍 <strong>Lat:</strong> ${lat} <br>📍 <strong>Long:</strong> ${lon}`;

      // Calculate Distance
      const distance = getDistanceFromLatLonInM(STANDARD_LAT, STANDARD_LON, lat, lon);
      
      // Update Map
      if (map) {
        if (actualMarker) map.removeLayer(actualMarker);
        // Red dot for actual location
        actualMarker = L.circleMarker([lat, lon], {
          radius: 6, color: '#ef4444', fillColor: '#ef4444', fillOpacity: 1
        }).addTo(map).bindPopup(`Actual: ${lat}, ${lon}`).openPopup();
        
        // Fit map to show both dots
        const bounds = L.latLngBounds([[STANDARD_LAT, STANDARD_LON], [lat, lon]]);
        map.fitBounds(bounds, { padding: [30, 30], maxZoom: 18 });
      }

      // Show Alerts based on 100m distance
      if (distance <= 100) {
        gpsSuccess.style.display = "block";
        gpsSuccess.innerHTML = `✅ <strong>Location Verified.</strong> Image taken ${distance.toFixed(1)}m from the hospital.`;
      } else {
        gpsWarning.style.display = "block";
        gpsWarning.innerHTML = `⚠️ <strong>Location Mismatch!</strong> Image taken <strong>${distance.toFixed(1)}m</strong> away from the expected hospital location.`;
      }

    } else {
      gpsData.innerHTML = "❌ No GPS coordinates found in text.";
    }

  } catch (err) {
    ocrText.textContent = "Error: " + err.message;
  } finally {
    extractBtn.disabled = false;
    extractBtn.textContent = "Extract Text & GPS";
  }
});