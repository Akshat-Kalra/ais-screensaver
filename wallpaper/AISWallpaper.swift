import AppKit
import WebKit

// AIS E-Ink as a live desktop wallpaper: one borderless window per display, parked just above
// the system wallpaper and below the desktop icons, each showing the web UI in wallpaper mode.

private let paper = NSColor(srgbRed: 0xE9 / 255, green: 0xE7 / 255, blue: 0xE0 / 255, alpha: 1)
private let baseURL = "http://127.0.0.1:47823/"
private let retryInterval: TimeInterval = 20

private final class WallpaperWindow: NSWindow {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

/// One display's window and web view.
@MainActor
private final class Pane: NSObject, WKNavigationDelegate {
    let window: WallpaperWindow
    private let webView: WKWebView
    private var url: URL?
    private var retryTimer: Timer?
    private var showingOffline = false

    init(screen: NSScreen) {
        window = WallpaperWindow(contentRect: screen.frame, styleMask: .borderless, backing: .buffered, defer: false)
        // Desktop icons sit 20 levels above the wallpaper; one above it keeps us under them.
        window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopWindow)) + 1)
        window.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle, .fullScreenNone]
        window.ignoresMouseEvents = true
        window.isReleasedWhenClosed = false
        window.hasShadow = false
        window.backgroundColor = paper

        // Occlusion detection stays on (unlike the screensaver): when windows cover the
        // desktop, WebKit throttles the page and the map stops drawing.
        webView = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        webView.setValue(false, forKey: "drawsBackground") // no white flash before load
        webView.underPageBackgroundColor = paper
        super.init()
        webView.navigationDelegate = self
        window.contentView = webView
        place(on: screen)
        window.orderFront(nil)
    }

    /// Fit the window to the display and leave room for the menu bar and Dock.
    func place(on screen: NSScreen) {
        window.setFrame(screen.frame, display: true)
        let f = screen.frame, v = screen.visibleFrame
        let inset = [f.maxY - v.maxY, f.maxX - v.maxX, v.minY - f.minY, v.minX - f.minX]
            .map { String(Int($0.rounded())) }.joined(separator: ",")
        // Extra query options, e.g. `defaults write com.akshatkalra.AISWallpaper params "dwell=60&region=tokyo"`.
        let extra = UserDefaults.standard.string(forKey: "params").map { "&\($0)" } ?? ""
        let target = URL(string: "\(baseURL)?saver=1&wallpaper=1&inset=\(inset)\(extra)")
        if target != url {
            url = target
            load()
        }
    }

    func close() {
        retryTimer?.invalidate()
        webView.navigationDelegate = nil
        webView.stopLoading()
        window.orderOut(nil)
    }

    private func load() {
        guard let url else { return }
        webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10))
    }

    // MARK: offline handling

    private func showOffline() {
        if !showingOffline {
            showingOffline = true
            webView.loadHTMLString(offlineHTML, baseURL: nil)
        }
        if retryTimer != nil { return }
        let t = Timer(timeInterval: retryInterval, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, self.showingOffline else { return }
                self.load()
            }
        }
        RunLoop.main.add(t, forMode: .common)
        retryTimer = t
    }

    private func handleFailure(_ error: Error) {
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled { return }
        if ns.domain == "WebKitErrorDomain" && ns.code == 102 { return } // our own interrupted load
        showOffline()
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        handleFailure(error)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        handleFailure(error)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard webView.url?.scheme != "about" else { return } // the offline page
        showingOffline = false
        retryTimer?.invalidate()
        retryTimer = nil
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        showingOffline = false
        load()
    }
}

private let offlineHTML = """
<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#E9E7E0;color:#1B1B1A;overflow:hidden}
body{display:flex;flex-direction:column;align-items:center;justify-content:center;
     font-family:"SF Mono",Menlo,monospace;text-align:center}
h1{font-size:3vmin;font-weight:600;letter-spacing:.08em;margin:0 0 1.5vmin;text-transform:uppercase}
p{font-size:1.8vmin;margin:0;opacity:.7}
</style></head><body><h1>Collector offline</h1><p>run scripts/install-agent.sh</p></body></html>
"""

@main
@MainActor
final class WallpaperApp: NSObject, NSApplicationDelegate {
    private var panes: [CGDirectDisplayID: Pane] = [:]

    static func main() {
        let app = NSApplication.shared
        let delegate = WallpaperApp()
        app.delegate = delegate
        app.setActivationPolicy(.accessory) // no Dock icon, no menu bar
        app.run()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        syncScreens()
        // Displays plugged in or removed, resolution changes, Dock moved.
        NotificationCenter.default.addObserver(
            forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.syncScreens() }
        }
    }

    private func syncScreens() {
        var seen = Set<CGDirectDisplayID>()
        for screen in NSScreen.screens {
            guard let id = (screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.uint32Value
            else { continue }
            seen.insert(id)
            if let pane = panes[id] {
                pane.place(on: screen)
            } else {
                panes[id] = Pane(screen: screen)
            }
        }
        for (id, pane) in panes where !seen.contains(id) {
            pane.close()
            panes[id] = nil
        }
    }
}
