// Squint for Mac: a window around the local Squint server.
//
// The app bundles a relocatable Python with the server (Contents/Resources/python) and runs
// `python -I -B -m squint.desktop --port N --resources Contents/Resources`, which first shows a
// setup page that downloads the models, then the normal web UI. This file only starts and stops
// that process and shows http://127.0.0.1:N/ in a WKWebView. Build: mac/build.sh.

import Cocoa
import WebKit

let logURL = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Logs/Squint/squint.log")

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var port = 0
    var quitting = false

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        let bundle = Bundle.main.bundleURL
        // An unsigned app opened straight from Downloads runs from a read-only random path.
        if bundle.path.contains("/AppTranslocation/") {
            fail("Move Squint to your Applications folder",
                 "Drag Squint from Downloads into Applications, then open it from there.")
            return
        }
        clearQuarantine(bundle)
        makeWindow()
        do {
            try startServer()
        } catch {
            fail("Squint couldn’t start", error.localizedDescription)
            return
        }
        waitForServer(attempt: 0)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ note: Notification) {
        quitting = true
        guard let p = server, p.isRunning else { return }
        p.terminate()  // SIGTERM: uvicorn shuts down; a download keeps its .part to resume
        let deadline = Date().addingTimeInterval(5)
        while p.isRunning && Date() < deadline { usleep(50_000) }
        if p.isRunning { kill(p.processIdentifier, SIGKILL) }
    }

    // MARK: - server

    /// After "Open Anyway" the app itself may run, but the Python inside still carries the
    /// download's quarantine flag. The bundle sits in Applications by now, so clear it.
    func clearQuarantine(_ bundle: URL) {
        let python = bundle.appendingPathComponent("Contents/Resources/python/bin/python3.12").path
        guard getxattr(python, "com.apple.quarantine", nil, 0, 0, XATTR_NOFOLLOW) >= 0 else { return }
        let x = Process()
        x.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
        x.arguments = ["-dr", "com.apple.quarantine", bundle.path]
        try? x.run()
        x.waitUntilExit()
    }

    func freePort() -> Int {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        defer { close(fd) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        addr.sin_port = 0
        var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        _ = withUnsafeMutablePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(fd, $0, len) }
        }
        _ = withUnsafeMutablePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &len) }
        }
        return Int(UInt16(bigEndian: addr.sin_port))
    }

    func startServer() throws {
        let res = Bundle.main.resourceURL!
        port = freePort()
        try FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        let log = try FileHandle(forWritingTo: logURL)
        let p = Process()
        p.executableURL = res.appendingPathComponent("python/bin/python3.12")
        p.arguments = ["-I", "-B", "-m", "squint.desktop", "--port", String(port), "--resources", res.path]
        p.standardOutput = log
        p.standardError = log
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                guard let self, !self.quitting else { return }
                self.fail("Squint stopped unexpectedly",
                          "Details are in \(logURL.path). Open Squint again to restart it.")
            }
        }
        try p.run()
        server = p
    }

    func waitForServer(attempt: Int) {
        let url = URL(string: "http://127.0.0.1:\(port)/")!
        var req = URLRequest(url: url)
        req.timeoutInterval = 1
        URLSession.shared.dataTask(with: req) { _, res, _ in
            DispatchQueue.main.async {
                if (res as? HTTPURLResponse)?.statusCode == 200 {
                    self.web.load(URLRequest(url: url))
                } else if attempt < 600, self.server?.isRunning == true {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.waitForServer(attempt: attempt + 1) }
                } else if self.server?.isRunning == true {
                    self.fail("Squint didn’t start", "Details are in \(logURL.path).")
                }
            }
        }.resume()
    }

    // MARK: - window

    func makeWindow() {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .nonPersistent()  // nothing pasted outlives the window
        web = WKWebView(frame: .zero, configuration: cfg)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        let html = """
            <html><body style="margin:0;height:100vh;display:grid;place-items:center;
            font:16px -apple-system,system-ui;color:#5f666e;background:transparent">
            <p>Opening Squint…</p></body></html>
            """
        web.loadHTMLString(html, baseURL: nil)

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Squint"
        window.minSize = NSSize(width: 720, height: 560)
        window.contentView = web
        window.center()
        window.setFrameAutosaveName("SquintMain")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func fail(_ title: String, _ detail: String) {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = detail
        a.alertStyle = .warning
        a.addButton(withTitle: "Quit")
        a.runModal()
        NSApp.terminate(nil)
    }

    func isLocal(_ url: URL?) -> Bool {
        guard let url else { return true }
        return url.scheme == "about" || url.scheme == "data" || url.host == "127.0.0.1"
    }

    // Links out of the app (GitHub, the website) open in the browser.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if isLocal(action.request.url) {
            decisionHandler(.allow)
        } else {
            NSWorkspace.shared.open(action.request.url!)
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, createWebViewWith cfg: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url {
            if isLocal(url) { webView.load(action.request) } else { NSWorkspace.shared.open(url) }
        }
        return nil
    }

    // "Upload a file"
    func webView(_ webView: WKWebView, runOpenPanelWith params: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = params.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.urls : nil) }
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert()
        a.messageText = message
        a.beginSheetModal(for: window) { _ in completionHandler() }
    }

    // MARK: - menus (the Edit menu is what makes copy and paste work in the web view)

    func buildMenu() {
        let main = NSMenu()
        func add(_ title: String, _ items: [NSMenuItem]) {
            let item = NSMenuItem()
            let menu = NSMenu(title: title)
            items.forEach(menu.addItem)
            item.submenu = menu
            main.addItem(item)
        }
        func item(_ title: String, _ action: Selector?, _ key: String, _ mods: NSEvent.ModifierFlags = .command) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
            i.keyEquivalentModifierMask = mods
            return i
        }
        add("Squint", [
            item("About Squint", #selector(NSApplication.orderFrontStandardAboutPanel(_:)), ""),
            .separator(),
            item("Hide Squint", #selector(NSApplication.hide(_:)), "h"),
            item("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
            item("Show All", #selector(NSApplication.unhideAllApplications(_:)), ""),
            .separator(),
            item("Quit Squint", #selector(NSApplication.terminate(_:)), "q"),
        ])
        add("Edit", [
            item("Undo", Selector(("undo:")), "z"),
            item("Redo", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("Cut", #selector(NSText.cut(_:)), "x"),
            item("Copy", #selector(NSText.copy(_:)), "c"),
            item("Paste", #selector(NSText.paste(_:)), "v"),
            item("Select All", #selector(NSText.selectAll(_:)), "a"),
        ])
        add("View", [
            item("Reload", #selector(WKWebView.reload(_:)), "r"),
            item("Actual Size", #selector(zoomReset), "0"),
            item("Zoom In", #selector(zoomIn), "+"),
            item("Zoom Out", #selector(zoomOut), "-"),
            .separator(),
            item("Enter Full Screen", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control]),
        ])
        add("Window", [
            item("Minimize", #selector(NSWindow.miniaturize(_:)), "m"),
            item("Zoom", #selector(NSWindow.zoom(_:)), ""),
            item("Close", #selector(NSWindow.performClose(_:)), "w"),
        ])
        NSApp.mainMenu = main
        NSApp.windowsMenu = main.items.last?.submenu
    }

    @objc func zoomIn() { web.pageZoom = min(web.pageZoom + 0.1, 2) }
    @objc func zoomOut() { web.pageZoom = max(web.pageZoom - 0.1, 0.6) }
    @objc func zoomReset() { web.pageZoom = 1 }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
