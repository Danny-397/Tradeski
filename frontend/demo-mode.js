/* ---------------------------------------------------------------------------
 * Tradeski — offline demo mode
 *
 * The dashboard is a pure client that reads everything from the API host. When
 * that host is unreachable (the free-tier backend is paused, a cold start times
 * out, a network blip), every panel used to render its own raw failure text and
 * the whole page read as broken.
 *
 * This installs a fetch wrapper in front of the API origin. Live backend wins,
 * always. Only when a GET genuinely fails do we fall back to a recorded
 * snapshot of real responses (demo-snapshot.js, loaded lazily so the normal
 * path pays nothing for it) and show a banner saying exactly that.
 *
 * Rules that keep this honest:
 *   - reads only. A failed POST/DELETE is never faked — writes surface the error.
 *   - a real answer always wins, including 4xx (a logged-out 401 is real).
 *   - the banner is unmissable and dates the snapshot.
 *
 * Must load before dashboard.js.
 * ------------------------------------------------------------------------- */
(function () {
    "use strict";

    var API_ORIGIN   = "https://tradeski.onrender.com";
    var SNAPSHOT_URL = "demo-snapshot.js";

    var snapshotPromise = null;
    var demoActive      = false;

    /* ---- lazy snapshot load ---------------------------------------------- */
    function loadSnapshot() {
        if (snapshotPromise) return snapshotPromise;
        snapshotPromise = new Promise(function (resolve, reject) {
            if (window.TRADESKI_SNAPSHOT) { resolve(window.TRADESKI_SNAPSHOT); return; }
            var s = document.createElement("script");
            s.src = SNAPSHOT_URL;
            s.onload  = function () {
                window.TRADESKI_SNAPSHOT ? resolve(window.TRADESKI_SNAPSHOT)
                                         : reject(new Error("snapshot empty"));
            };
            s.onerror = function () { reject(new Error("snapshot unavailable")); };
            document.head.appendChild(s);
        });
        return snapshotPromise;
    }

    /* ---- resolve a request path against the snapshot ---------------------- */
    function param(path, name) {
        var m = path.match(new RegExp("[?&]" + name + "=([^&]*)"));
        return m ? decodeURIComponent(m[1]) : null;
    }

    function lookup(snap, path) {
        var eps = snap.endpoints || {};
        if (eps[path]) return eps[path];

        var route = path.split("?")[0];

        /* price_history: fall back along symbol, then timeframe */
        if (route === "/price_history") {
            var sym = param(path, "symbol") || snap.defaultSymbol;
            var tf  = param(path, "tf") || "1D";
            var tries = [
                "/price_history?symbol=" + sym + "&tf=" + tf,
                "/price_history?symbol=" + sym + "&tf=1D",
                "/price_history?symbol=" + snap.defaultSymbol + "&tf=" + tf,
                "/price_history?symbol=" + snap.defaultSymbol + "&tf=1D"
            ];
            for (var i = 0; i < tries.length; i++) if (eps[tries[i]]) return eps[tries[i]];
            return null;
        }

        /* stats / news: fall back to the default symbol */
        if (route === "/stats" || route === "/news") {
            var s2 = route + "?symbol=" + snap.defaultSymbol;
            if (eps[s2]) return eps[s2];
        }
        return null;
    }

    /* ---- the banner ------------------------------------------------------ */
    function showBanner(snap) {
        if (document.getElementById("demo-banner")) return;

        var when = "a recent session";
        try {
            when = new Date(snap.capturedAt).toLocaleDateString(undefined, {
                year: "numeric", month: "long", day: "numeric"
            });
        } catch (e) { /* keep the fallback wording */ }

        var bar = document.createElement("div");
        bar.id = "demo-banner";
        bar.setAttribute("role", "status");
        bar.innerHTML =
            '<span class="demo-dot" aria-hidden="true"></span>' +
            '<span class="demo-text">' +
              '<strong>Offline demo.</strong> The live data backend is paused, so this dashboard is ' +
              'replaying a snapshot of <strong>real market data captured ' + when + '</strong>. ' +
              'Charts, indicators, the screener and the macro strip are genuine values from that moment. ' +
              'Live streaming, news and account features need the backend.' +
            '</span>' +
            '<a class="demo-link" href="https://github.com/Danny-397/Tradeski" ' +
               'target="_blank" rel="noopener">Source &amp; technical report &nearr;</a>';
        document.body.insertBefore(bar, document.body.firstChild);
        document.body.classList.add("demo-mode");
    }

    function enterDemoMode(snap) {
        if (demoActive) return;
        demoActive = true;
        window.TRADESKI_DEMO_MODE = true;
        if (document.body) showBanner(snap);
        else document.addEventListener("DOMContentLoaded", function () { showBanner(snap); });
    }

    /* ---- fetch wrapper --------------------------------------------------- */
    var nativeFetch = window.fetch.bind(window);

    window.fetch = function (input, init) {
        var url = typeof input === "string" ? input
                : (input && input.url) ? input.url : String(input);

        if (url.indexOf(API_ORIGIN) !== 0) return nativeFetch(input, init);

        var method = ((init && init.method) ||
                      (input && input.method) || "GET").toUpperCase();
        var path = url.slice(API_ORIGIN.length) || "/";

        return nativeFetch(input, init).then(function (res) {
            /* Any real answer wins — including 401/404/429, which are real state. */
            if (res.status < 500) return res;

            /* A 5xx is ambiguous: it can be this app reporting a problem it
               knows about (missing FRED key -> 503 {"error": ...}), or the host
               itself being down (Render serves an HTML 503 when a service is
               paused). Only the latter means "backend unreachable" — an app
               error should reach the panel that asked for it, so that panel can
               show its own message instead of the whole page claiming outage. */
            return res.clone().text().then(function (body) {
                try {
                    var j = JSON.parse(body);
                    if (j && typeof j === "object" && "error" in j) return res;
                } catch (e) { /* not our JSON -> treat as host-level failure */ }
                throw new Error("HTTP " + res.status);
            });
        }).catch(function (err) {
            if (method !== "GET") throw err;   /* never fake a write */

            return loadSnapshot().then(function (snap) {
                var body = lookup(snap, path);
                if (body === null || body === undefined) throw err;
                enterDemoMode(snap);
                return new Response(JSON.stringify(body), {
                    status: 200,
                    headers: { "Content-Type": "application/json" }
                });
            }).catch(function () { throw err; });
        });
    };

    /* Socket.IO streaming has no offline equivalent; stop it from retrying
       forever and spamming the console once we know the backend is down. */
    document.addEventListener("DOMContentLoaded", function () {
        setTimeout(function () {
            if (demoActive && window.io && window.__tradeskiSocket &&
                typeof window.__tradeskiSocket.close === "function") {
                try { window.__tradeskiSocket.close(); } catch (e) { /* noop */ }
            }
        }, 8000);
    });
})();
