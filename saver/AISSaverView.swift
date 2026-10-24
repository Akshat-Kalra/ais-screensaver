import AppKit
import ScreenSaver
import WebKit

/// Web view that never takes part in event handling, so the screen saver host
/// still sees every mouse/key event and dismisses the saver.
private final class PassiveWebView: WKWebView {
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    override var acceptsFirstResponder: Bool { false }
    override func becomeFirstResponder() -> Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { false }
}

@objc(AISSaverView)
@MainActor
final class AISSaverView: ScreenSaverView, WKNavigationDelegate {

    private static let paper = NSColor(srgbRed: 0xE9 / 255, green: 0xE7 / 255, blue: 0xE0 / 255, alpha: 1)
    private static let retryInterval: TimeInterval = 20
    private static let defaultURL = "http://127.0.0.1:47823/"

    private var webView: WKWebView?
    private var retryTimer: Timer?
    nonisolated(unsafe) private var willStopObserver: NSObjectProtocol?
    private var showingOffline = false
    private var tornDown = false

    // MARK: - Init

    override init?(frame: NSRect, isPreview: Bool) {
        super.init(frame: frame, isPreview: isPreview)
        commonInit()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        commonInit()
    }

    private func commonInit() {
        // Nothing is animated natively; the web page does all the drawing.
        animationTimeInterval = 3600
        wantsLayer = true
        layer?.backgroundColor = Self.paper.cgColor

        // WORKAROUND (macOS 14+ legacyScreenSaver): stopAnimation() is not reliably called
        // (on Sonoma+ it is effectively only used for the System Settings preview) and
        // instances are never deallocated; a new instance is created on every activation
        // while old ones keep running (FB13094564-class / FB19204084 reports, Apple forums
        // threads 738547 and 787444). The only dependable "saver is going away" signal is
        // the distributed notification com.apple.screensaver.willstop, so we tear down
        // everything (web content process, timers) on it.
        willStopObserver = DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("com.apple.screensaver.willstop"),
            object: nil,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.tearDown() }
        }
    }

    deinit {
        // Rarely runs on Sonoma+ (instances linger), but be tidy when it does.
        if let o = willStopObserver { DistributedNotificationCenter.default().removeObserver(o) }
    }

    override var hasConfigureSheet: Bool { false }
    override var configureSheet: NSWindow? { nil }

    // MARK: - Lifecycle

    override func startAnimation() {
        super.startAnimation()
        // WORKAROUND: a lingering instance may be restarted after willstop tore it down,
        // so (re)create the web view here, but never stack a second one.
        tornDown = false
        ensureWebView()
    }

    override func stopAnimation() {
        super.stopAnimation()
        tearDown()
    }

    override func animateOneFrame() {
        // Intentionally empty.
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        // The preview in System Settings may never call startAnimation reliably.
        if window != nil, isPreview, !tornDown { ensureWebView() }
    }

    override func resize(withOldSuperviewSize oldSize: NSSize) {
        super.resize(withOldSuperviewSize: oldSize)
        webView?.frame = bounds
    }

    // MARK: - Web view management

    private func targetURL() -> URL? {
        var base = Self.defaultURL + "?saver=1"
        // Override for testing: env var (harness) or ScreenSaverDefaults key "url".
        if let env = ProcessInfo.processInfo.environment["AIS_SAVER_URL"], !env.isEmpty {
            return URL(string: env)
        }
        if let id = Bundle(for: AISSaverView.self).bundleIdentifier,
           let defaults = ScreenSaverDefaults(forModuleWithName: id),
           let override = defaults.string(forKey: "url"), !override.isEmpty {
            return URL(string: override)
        }
        if isPreview { base += "&preview=1" }
        // Match the menu bar clock: the page can't see the "24-hour time" setting itself.
        let hourFormat = DateFormatter.dateFormat(fromTemplate: "j", options: 0, locale: .current) ?? ""
        base += hourFormat.contains("H") || hourFormat.contains("k") ? "&hours=24" : "&hours=12"
        return URL(string: base)
    }

    private func ensureWebView() {
        if webView != nil { return } // never stack duplicates
        // Defensive: remove any stray web views left from earlier incarnations.
        for sub in subviews where sub is WKWebView { sub.removeFromSuperview() }

        let config = WKWebViewConfiguration()
        let wv = PassiveWebView(frame: bounds, configuration: config)
        wv.autoresizingMask = [.width, .height]
        wv.navigationDelegate = self
        wv.underPageBackgroundColor = Self.paper
        wv.setValue(false, forKey: "drawsBackground") // no white flash before load
        wv.wantsLayer = true
        wv.layer?.backgroundColor = Self.paper.cgColor
        // WORKAROUND: the saver's view lives in a window WebKit may consider occluded (it's
        // hosted remotely by System Settings / the screen saver engine). Occluded pages get
        // requestAnimationFrame paused, which stalls MapLibre forever. This WebKit SPI turns
        // occlusion detection off; it is skipped if a future WebKit drops it.
        let occlusion = NSSelectorFromString("_setWindowOcclusionDetectionEnabled:")
        if wv.responds(to: occlusion) {
            typealias SetBool = @convention(c) (AnyObject, Selector, Bool) -> Void
            unsafeBitCast(wv.method(for: occlusion), to: SetBool.self)(wv, occlusion, false)
        }
        addSubview(wv)
        webView = wv
        showingOffline = false
        loadRealURL()
    }

    private func loadRealURL() {
        guard let wv = webView, let url = targetURL() else { return }
        wv.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10))
    }

    private func tearDown() {
        tornDown = true
        retryTimer?.invalidate()
        retryTimer = nil
        if let wv = webView {
            wv.navigationDelegate = nil
            wv.stopLoading()
            // Loading about:blank stops page JS/timers/rAF in the web content process.
            wv.load(URLRequest(url: URL(string: "about:blank")!))
            wv.removeFromSuperview()
        }
        webView = nil
        showingOffline = false
    }

    // MARK: - Offline handling

    private func showOffline() {
        guard let wv = webView else { return }
        if !showingOffline {
            showingOffline = true
            wv.loadHTMLString(Self.offlineHTML, baseURL: nil)
        }
        scheduleRetry()
    }

    private func scheduleRetry() {
        if retryTimer != nil { return }
        let t = Timer(timeInterval: Self.retryInterval, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, !self.tornDown, self.showingOffline else { return }
                self.loadRealURL()
            }
        }
        RunLoop.main.add(t, forMode: .common)
        retryTimer = t
    }

    private func isOfflinePage(_ url: URL?) -> Bool {
        // loadHTMLString with nil baseURL commits as about:blank
        guard let url else { return true }
        return url.scheme == "about"
    }

    private func handleFailure(_ error: Error) {
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled { return }
        // WebKit error 102 = "frame load interrupted" (e.g. our own about:blank/loadHTML).
        if ns.domain == "WebKitErrorDomain" && ns.code == 102 { return }
        showOffline()
    }

    // MARK: - WKNavigationDelegate

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        handleFailure(error)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        handleFailure(error)
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
                 decisionHandler: @escaping @MainActor @Sendable (WKNavigationResponsePolicy) -> Void) {
        if let http = navigationResponse.response as? HTTPURLResponse, http.statusCode >= 500 {
            decisionHandler(.cancel)
            showOffline()
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if !isOfflinePage(webView.url) {
            // Real page is up: stop retrying.
            showingOffline = false
            retryTimer?.invalidate()
            retryTimer = nil
        }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        showingOffline = false
        loadRealURL()
    }

    // MARK: - Bundled offline page

    private static let offlineHTML: String = {
        // Pixel ship: 11x9 grid, each '#' becomes an SVG rect.
        let rows = [
            "....#......",
            "...###.....",
            "..#####....",
            "..#####....",
            ".#######...",
            ".#.###.#...",
            "#..###..#..",
            "...#.#.....",
            "..#...#....",
        ]
        var rects = ""
        for (y, row) in rows.enumerated() {
            for (x, c) in row.enumerated() where c == "#" {
                rects += "<rect x=\"\(x)\" y=\"\(y)\" width=\"1\" height=\"1\"/>"
            }
        }
        return """
        <!doctype html><html><head><meta charset="utf-8">
        <style>
        html,body{margin:0;height:100%;background:#E9E7E0;color:#1B1B1A;overflow:hidden}
        body{display:flex;flex-direction:column;align-items:center;justify-content:center;
             font-family:"SF Mono",Menlo,monospace;text-align:center}
        svg{width:12vmin;height:auto;fill:#1B1B1A;shape-rendering:crispEdges;margin-bottom:5vmin}
        h1{font-size:4vmin;font-weight:600;letter-spacing:.08em;margin:0 0 2vmin;text-transform:uppercase}
        p{font-size:2.2vmin;margin:0;opacity:.7}
        </style></head><body>
        <svg viewBox="0 0 11 9" xmlns="http://www.w3.org/2000/svg">\(rects)</svg>
        <h1>Collector offline</h1>
        <p>run scripts/install-agent.sh</p>
        </body></html>
        """
    }()
}
