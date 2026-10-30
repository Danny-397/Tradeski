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

    /* ---- the "waking up" toast --------------------------------------------
       The free Render host sleeps when idle and takes ~30s to answer the first
       request. Without this the dashboard just sits on skeletons. If an API
       call is still pending after WAKE_DELAY_MS and nothing has answered yet,
       say what is happening; the first real answer (or demo mode) clears it. */
    var WAKE_DELAY_MS = 2500;
    var WAKE_EXPECT_S = 40;
    var gotAnswer = false;
    var wakeTimer = null;
    var wakeTick  = null;

    function showWake() {
        if (gotAnswer || demoActive || document.getElementById("wake-toast")) return;
        var t = document.createElement("div");
        t.id = "wake-toast";
        t.setAttribute("role", "status");
        t.innerHTML =
            '<span class="wake-spinner" aria-hidden="true"></span>' +
            '<span class="wake-copy">' +
              '<strong>Waking up the server&hellip;</strong>' +
              '<span>Free hosting sleeps when idle. This usually takes 20&ndash;40 seconds.</span>' +
            '</span>' +
            '<span class="wake-time" aria-hidden="true">0s</span>' +
            '<span class="wake-bar" aria-hidden="true"><i></i></span>';
        document.body.appendChild(t);
        var started = Date.now();
        var fill = t.querySelector(".wake-bar i");
        var time = t.querySelector(".wake-time");
        wakeTick = setInterval(function () {
            var s = (Date.now() - started) / 1000;
            time.textContent = Math.round(s) + "s";
            /* Eases toward 95% so it never claims to be done before it is. */
            fill.style.width = (95 * (1 - Math.exp(-s / (WAKE_EXPECT_S / 2.5)))).toFixed(1) + "%";
        }, 250);
    }

    function hideWake(ready) {
        clearTimeout(wakeTimer); wakeTimer = null;
        clearInterval(wakeTick); wakeTick = null;
        var t = document.getElementById("wake-toast");
        if (!t) return;
        if (ready) {
            t.classList.add("is-ready");
            t.querySelector(".wake-copy").innerHTML = "<strong>Connected.</strong><span>Live data is loading.</span>";
            t.querySelector(".wake-bar i").style.width = "100%";
            setTimeout(function () { t.remove(); }, 1400);
        } else {
            t.remove();
        }
    }

    function noteRequestStart() {
        if (gotAnswer || wakeTimer) return;
        wakeTimer = setTimeout(function () {
            wakeTimer = null;
            if (document.body) showWake();
        }, WAKE_DELAY_MS);
    }

    function noteAnswer() {
        if (gotAnswer) return;
        gotAnswer = true;
        hideWake(true);
    }

    function enterDemoMode(snap) {
        if (demoActive) return;
        demoActive = true;
        hideWake(false);
        window.TRADESKI_DEMO_MODE = true;
        if (document.body) showBanner(snap);
        else document.addEventListener("DOMContentLoaded", function () { showBanner(snap); });
    }

    /* ---- crawlers and automated browsers --------------------------------
       Each request that reaches the free Render backend wakes it for at least
       15 of the 750 instance-hours a month that every project backend shares,
       and running out suspends all of them (it happened 2026-10-28). A crawler
       rendering this page should not spend them, so automated visitors get the
       snapshot directly. TRADESKI_OFFLINE also stops dashboard.js opening its
       socket. ?live=1 opts back in, for testing with a headless browser. */
    var AUTOMATED = !/[?&]live=1\b/.test(location.search) && (navigator.webdriver ||
        /bot|crawl|spider|slurp|facebookexternalhit|preview|lighthouse|headless/i.test(navigator.userAgent));
    if (AUTOMATED) window.TRADESKI_OFFLINE = true;

    /* ---- fetch wrapper --------------------------------------------------- */
    var nativeFetch = window.fetch.bind(window);

    window.fetch = function (input, init) {
        var url = typeof input === "string" ? input
                : (input && input.url) ? input.url : String(input);

        if (url.indexOf(API_ORIGIN) !== 0) return nativeFetch(input, init);

        var method = ((init && init.method) ||
                      (input && input.method) || "GET").toUpperCase();
        var path = url.slice(API_ORIGIN.length) || "/";

        noteRequestStart();
        var request = AUTOMATED
            ? Promise.reject(new Error("automated visitor: serving the snapshot"))
            : nativeFetch(input, init);
        return request.then(function (res) {
            /* Any real answer wins — including 401/404/429, which are real state. */
            if (res.status < 500) { noteAnswer(); return res; }

            /* A 5xx is ambiguous: it can be this app reporting a problem it
               knows about (missing FRED key -> 503 {"error": ...}), or the host
               itself being down (Render serves an HTML 503 when a service is
               paused). Only the latter means "backend unreachable" — an app
               error should reach the panel that asked for it, so that panel can
               show its own message instead of the whole page claiming outage. */
            return res.clone().text().then(function (body) {
                try {
                    var j = JSON.parse(body);
                    if (j && typeof j === "object" && "error" in j) { noteAnswer(); return res; }
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
