/* ============================================================
   Conductor — Bakı Avtobus Köməkçisi
   Frontend Application
   ============================================================ */

(() => {
    "use strict";

    // ── State ────────────────────────────────────────────────
    const state = {
        sessionId: null,
        hasLocation: false,
        latitude: null,
        longitude: null,
        nearestStops: [],
        isSending: false,
        mapVisible: true,
    };

    // ── DOM ──────────────────────────────────────────────────
    const $ = (s) => document.querySelector(s);
    const chatMessages = $("#chat-messages");
    const chatInput = $("#chat-input");
    const chatForm = $("#chat-form");
    const btnSend = $("#btn-send");
    const typingIndicator = $("#typing-indicator");
    const locationModal = $("#location-modal");
    const btnAllowLocation = $("#btn-allow-location");
    const btnSkipLocation = $("#btn-skip-location");
    const btnToggleMap = $("#btn-toggle-map");
    const btnMyLocation = $("#btn-my-location");
    const appContainer = $("#app");
    const mapPanel = $("#map-panel");
    const contentArea = $(".content-area");

    // ── Map ──────────────────────────────────────────────────
    let map = null;
    let userMarker = null;
    let stopMarkers = [];

    function initMap() {
        map = L.map("map", {
            center: [40.4093, 49.8671],
            zoom: 13,
            zoomControl: true,
        });

        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            attribution: "&copy; OpenStreetMap",
            maxZoom: 19,
        }).addTo(map);
    }

    function setUserLocation(lat, lng) {
        if (userMarker) map.removeLayer(userMarker);

        userMarker = L.circleMarker([lat, lng], {
            radius: 10,
            fillColor: "#4285f4",
            color: "#ffffff",
            weight: 3,
            fillOpacity: 1,
        })
            .addTo(map)
            .bindPopup("<b>Siz buradasınız</b>");

        map.setView([lat, lng], 15);
    }

    // All-stops layer (persistent, loaded once)
    let clusterGroup = null;

    function loadAllStops() {
        API.getAllStops().then((stops) => {
            if (!stops || stops.length === 0) return;

            clusterGroup = L.markerClusterGroup({
                maxClusterRadius: 40,
                spiderfyOnMaxZoom: true,
                showCoverageOnHover: false,
                disableClusteringAtZoom: 16,
                iconCreateFunction: function (cluster) {
                    const count = cluster.getChildCount();
                    let size = "small";
                    if (count > 50) size = "large";
                    else if (count > 20) size = "medium";
                    return L.divIcon({
                        html: `<div class="cluster-icon cluster-icon--${size}"><span>${count}</span></div>`,
                        className: "stop-cluster",
                        iconSize: [40, 40],
                    });
                },
            });

            const defaultIcon = L.divIcon({
                className: "stop-marker",
                html: '<div class="stop-dot"></div>',
                iconSize: [18, 18],
                iconAnchor: [9, 9],
            });

            const hubIcon = L.divIcon({
                className: "stop-marker",
                html: '<div class="stop-dot stop-dot--hub"></div>',
                iconSize: [22, 22],
                iconAnchor: [11, 11],
            });

            stops.forEach((stop) => {
                if (!stop.latitude || !stop.longitude) return;
                const icon = stop.isTransportHub ? hubIcon : defaultIcon;
                const marker = L.marker([stop.latitude, stop.longitude], { icon });

                // Lazy-load bus list on popup open
                marker.bindPopup(() => buildStopPopup(stop), { minWidth: 180, maxWidth: 280 });

                clusterGroup.addLayer(marker);
            });

            map.addLayer(clusterGroup);
        });
    }

    function buildStopPopup(stop) {
        const container = document.createElement("div");
        container.className = "stop-popup";
        container.innerHTML =
            `<div class="stop-popup__name">${escHtml(stop.name || "Dayanacaq")}</div>` +
            (stop.code ? `<div class="stop-popup__code">Kod: ${escHtml(stop.code)}</div>` : "") +
            `<div class="stop-popup__buses" id="popup-buses-${stop.id}">Yüklənir...</div>`;

        // Fetch buses asynchronously
        API.getBusesAtStop(stop.id).then((buses) => {
            const el = container.querySelector(`#popup-buses-${stop.id}`);
            if (!el) return;
            if (buses.length === 0) {
                el.textContent = "Avtobus tapılmadı";
                return;
            }
            el.innerHTML = buses
                .map((b) =>
                    `<span class="stop-popup__bus" data-bus="${b.number}">#${escHtml(b.number)}</span>`
                )
                .join(" ");

            // Make bus chips clickable
            el.querySelectorAll(".stop-popup__bus").forEach((chip) => {
                chip.addEventListener("click", () => {
                    const num = chip.dataset.bus;
                    chatInput.value = `${num} nömrəli avtobus`;
                    sendMessage(chatInput.value);
                    map.closePopup();
                });
            });
        });

        return container;
    }

    function showStopsOnMap(stops, fitBounds = true) {
        stopMarkers.forEach((m) => map.removeLayer(m));
        stopMarkers = [];

        if (!stops || stops.length === 0) return;

        const highlightIcon = L.divIcon({
            className: "stop-marker",
            html: '<div class="stop-dot stop-dot--highlight"></div>',
            iconSize: [22, 22],
            iconAnchor: [11, 11],
        });

        stops.forEach((stop) => {
            if (!stop.latitude || !stop.longitude) return;
            const marker = L.marker([stop.latitude, stop.longitude], { icon: highlightIcon })
                .addTo(map)
                .bindPopup(
                    `<b>${escHtml(stop.name || "Dayanacaq")}</b>` +
                    (stop.distanceMeters ? `<br>${Math.round(stop.distanceMeters)}m` : "")
                );
            stopMarkers.push(marker);
        });

        if (fitBounds) {
            const points = stops
                .filter((s) => s.latitude && s.longitude)
                .map((s) => [s.latitude, s.longitude]);
            if (state.latitude) points.push([state.latitude, state.longitude]);
            if (points.length > 0) {
                map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 16 });
            }
        }
    }

    function resizeMap() {
        if (map) setTimeout(() => map.invalidateSize(), 120);
    }

    // ── API ──────────────────────────────────────────────────
    const API = {
        async startSession(lat, lng) {
            const body = {};
            if (lat != null && lng != null) {
                body.latitude = lat;
                body.longitude = lng;
            }
            const res = await fetch("/api/session/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            if (!res.ok) throw new Error(`Session start failed: ${res.status}`);
            return res.json();
        },

        async chat(sessionId, message) {
            const res = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: sessionId, message }),
            });
            if (res.status === 404) return { expired: true };
            if (!res.ok) throw new Error(`Chat failed: ${res.status}`);
            return res.json();
        },

        async updateLocation(sessionId, lat, lng) {
            const res = await fetch("/api/session/location", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: sessionId, latitude: lat, longitude: lng }),
            });
            if (!res.ok) throw new Error(`Location update failed: ${res.status}`);
            return res.json();
        },

        async getBusInfo(number) {
            const res = await fetch(`/api/bus/${encodeURIComponent(number)}`);
            if (!res.ok) return null;
            return res.json();
        },

        async getAllStops() {
            const res = await fetch("/api/stops");
            if (!res.ok) return [];
            const data = await res.json();
            return data.stops || [];
        },

        async getBusesAtStop(stopId) {
            const res = await fetch(`/api/stops/${stopId}/buses`);
            if (!res.ok) return [];
            const data = await res.json();
            return data.buses || [];
        },
    };

    // ── Chat UI ──────────────────────────────────────────────
    function addMessage(text, sender = "bot") {
        const msgDiv = document.createElement("div");
        msgDiv.className = `message message--${sender}`;

        if (sender === "bot") {
            const avatar = document.createElement("div");
            avatar.className = "message__avatar";
            avatar.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M4 16c0 .88.39 1.67 1 2.22V20c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h8v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1.78c.61-.55 1-1.34 1-2.22V6c0-3.5-3.58-4-8-4s-8 .5-8 4v10zm3.5 1c-.83 0-1.5-.67-1.5-1.5S6.67 14 7.5 14s1.5.67 1.5 1.5S8.33 17 7.5 17zm9 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm1.5-6H6V6h12v5z"/></svg>`;
            msgDiv.appendChild(avatar);
        }

        const bubble = document.createElement("div");
        bubble.className = "message__bubble";
        bubble.innerHTML = formatMessage(text);

        msgDiv.appendChild(bubble);
        chatMessages.appendChild(msgDiv);
        scrollToBottom();
    }

    function addErrorMessage(text) {
        const msgDiv = document.createElement("div");
        msgDiv.className = "message message--bot message--error";

        const avatar = document.createElement("div");
        avatar.className = "message__avatar";
        avatar.style.background = "#fce8e6";
        avatar.style.color = "#ea4335";
        avatar.textContent = "!";
        msgDiv.appendChild(avatar);

        const bubble = document.createElement("div");
        bubble.className = "message__bubble";
        bubble.textContent = text;
        msgDiv.appendChild(bubble);

        chatMessages.appendChild(msgDiv);
        scrollToBottom();
    }

    function addSuggestions(items) {
        const wrap = document.createElement("div");
        wrap.className = "suggestions";
        items.forEach((text) => {
            const chip = document.createElement("button");
            chip.className = "suggestion-chip";
            chip.textContent = text;
            chip.addEventListener("click", () => {
                wrap.remove();
                chatInput.value = text;
                sendMessage(text);
            });
            wrap.appendChild(chip);
        });
        chatMessages.appendChild(wrap);
        scrollToBottom();
    }

    function formatMessage(text) {
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
            .replace(/\*(.*?)\*/g, "<em>$1</em>")
            .replace(/\n/g, "<br>")
            .replace(/#(\d+[A-Za-z]?)\b/g, '<span class="bus-link" data-bus="$1">#$1</span>');
    }

    function escHtml(str) {
        const d = document.createElement("div");
        d.textContent = str;
        return d.innerHTML;
    }

    function scrollToBottom() {
        requestAnimationFrame(() => {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        });
    }

    function showTyping() {
        typingIndicator.classList.remove("hidden");
        scrollToBottom();
    }

    function hideTyping() {
        typingIndicator.classList.add("hidden");
    }

    function setInputEnabled(enabled) {
        chatInput.disabled = !enabled;
        btnSend.disabled = !enabled;
        state.isSending = !enabled;
    }

    // ── Geolocation ──────────────────────────────────────────
    function requestGeolocation() {
        return new Promise((resolve) => {
            if (!navigator.geolocation) {
                resolve(null);
                return;
            }
            navigator.geolocation.getCurrentPosition(
                (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
                () => resolve(null),
                { enableHighAccuracy: true, timeout: 10000, maximumAge: 300000 }
            );
        });
    }

    // ── Session ──────────────────────────────────────────────
    async function startSession(lat, lng) {
        try {
            const data = await API.startSession(lat, lng);
            state.sessionId = data.session_id;
            state.nearestStops = data.nearest_stops || [];

            addMessage(data.greeting, "bot");

            if (state.nearestStops.length > 0) {
                showStopsOnMap(state.nearestStops);
            }

            // Show suggestion chips after greeting
            addSuggestions([
                "Yaxınlıqda dayanacaq var?",
                "65 nömrəli avtobus",
                "28 Maya necə gedim?",
            ]);
        } catch (err) {
            addErrorMessage("Xəta baş verdi. Zəhmət olmasa səhifəni yeniləyin.");
            console.error("Session start error:", err);
        }
    }

    async function handleSessionExpired() {
        addErrorMessage("Sessiya bitdi. Yeni sessiya yaradılır...");
        await startSession(state.latitude, state.longitude);
    }

    // ── Send Message ─────────────────────────────────────────
    async function sendMessage(message) {
        const trimmed = message.trim();
        if (!trimmed || state.isSending) return;

        addMessage(trimmed, "user");
        chatInput.value = "";
        setInputEnabled(false);
        showTyping();

        try {
            const data = await API.chat(state.sessionId, trimmed);

            if (data.expired) {
                hideTyping();
                await handleSessionExpired();
                const retryData = await API.chat(state.sessionId, trimmed);
                hideTyping();
                addMessage(retryData.reply, "bot");
                handleRouteData(retryData);
            } else {
                hideTyping();
                addMessage(data.reply, "bot");
                handleRouteData(data);
            }
        } catch (err) {
            hideTyping();
            addErrorMessage("Bağlantı xətası. İnternet bağlantınızı yoxlayın.");
            console.error("Chat error:", err);
        } finally {
            setInputEnabled(true);
            chatInput.focus();
        }
    }

    function handleRouteData(data) {
        if (!data.routes || data.routes.length === 0) return;

        // Extract any stop coordinates from route data for map display
        const mapPoints = [];
        data.routes.forEach((route) => {
            // For bus info responses
            if (route.latitude && route.longitude) {
                mapPoints.push(route);
            }
        });
        if (mapPoints.length > 0) {
            showStopsOnMap(mapPoints);
        }

        // For route_find results, try to fetch bus stops for map display
        const firstRoute = data.routes[0];
        const busNumber = firstRoute.busNumber || firstRoute.bus1Number;
        if (busNumber && data.intent === "route_find") {
            API.getBusInfo(busNumber).then((info) => {
                if (info && info.stops) {
                    showStopsOnMap(
                        info.stops.map((s) => ({
                            latitude: s.latitude,
                            longitude: s.longitude,
                            name: s.stopName,
                        }))
                    );
                }
            });
        }
    }

    // ── Event Listeners ──────────────────────────────────────
    document.addEventListener("DOMContentLoaded", () => {
        initMap();
        loadAllStops();

        // Location modal — Allow
        btnAllowLocation.addEventListener("click", async () => {
            btnAllowLocation.textContent = "Gözləyin...";
            btnAllowLocation.disabled = true;

            const loc = await requestGeolocation();
            locationModal.classList.add("hidden");
            appContainer.classList.remove("hidden");
            resizeMap();

            if (loc) {
                state.hasLocation = true;
                state.latitude = loc.lat;
                state.longitude = loc.lng;
                setUserLocation(loc.lat, loc.lng);
                await startSession(loc.lat, loc.lng);
            } else {
                addErrorMessage("Yer məlumatını əldə edə bilmədik. Əl ilə daxil edə bilərsiniz.");
                await startSession(null, null);
            }
        });

        // Location modal — Skip
        btnSkipLocation.addEventListener("click", async () => {
            locationModal.classList.add("hidden");
            appContainer.classList.remove("hidden");
            resizeMap();
            await startSession(null, null);
        });

        // Chat form submit
        chatForm.addEventListener("submit", (e) => {
            e.preventDefault();
            sendMessage(chatInput.value);
        });

        // Map toggle (mobile)
        btnToggleMap.addEventListener("click", () => {
            state.mapVisible = !state.mapVisible;
            if (state.mapVisible) {
                contentArea.classList.remove("map-hidden");
            } else {
                contentArea.classList.add("map-hidden");
            }
            resizeMap();
        });

        // My location button
        btnMyLocation.addEventListener("click", async () => {
            const loc = await requestGeolocation();
            if (loc) {
                state.hasLocation = true;
                state.latitude = loc.lat;
                state.longitude = loc.lng;
                setUserLocation(loc.lat, loc.lng);
                if (state.sessionId) {
                    try {
                        const data = await API.updateLocation(state.sessionId, loc.lat, loc.lng);
                        state.nearestStops = data.nearest_stops || [];
                        showStopsOnMap(state.nearestStops);
                        addMessage("Yeriniz yeniləndi.", "bot");
                    } catch (err) {
                        console.error("Location update error:", err);
                    }
                }
            } else {
                addErrorMessage("Yer məlumatını əldə edə bilmədik.");
            }
        });

        // Bus link clicks (event delegation)
        chatMessages.addEventListener("click", (e) => {
            const busLink = e.target.closest(".bus-link");
            if (busLink) {
                const busNumber = busLink.dataset.bus;
                chatInput.value = `${busNumber} nömrəli avtobus haqqında məlumat`;
                sendMessage(chatInput.value);
            }
        });

        // Enter key
        chatInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                chatForm.dispatchEvent(new Event("submit"));
            }
        });

        // Mobile: hide map when keyboard opens, restore when it closes
        if (window.innerWidth <= 768) {
            chatInput.addEventListener("focus", () => {
                contentArea.classList.add("keyboard-open");
                resizeMap();
                scrollToBottom();
            });
            chatInput.addEventListener("blur", () => {
                contentArea.classList.remove("keyboard-open");
                resizeMap();
            });

            // Also handle visualViewport resize (more reliable keyboard detection)
            if (window.visualViewport) {
                window.visualViewport.addEventListener("resize", () => {
                    scrollToBottom();
                });
            }
        }
    });
})();
