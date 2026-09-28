import Cocoa
import Darwin
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow?
    var webView: WKWebView?
    var statusItem: NSStatusItem?
    var healthTimer: Timer?
    var healthFails = 0
    var healthArmed = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        startBackend()
        let view = WKWebView(frame: NSRect(x: 0, y: 0, width: 500, height: 520))
        view.setValue(false, forKey: "drawsBackground")
        webView = view

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 500, height: 520),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Jarvis"
        window.isReleasedWhenClosed = false
        window.contentView = view
        window.minSize = NSSize(width: 400, height: 480)
        window.center()
        window.makeKeyAndOrderFront(nil)
        window.delegate = self
        self.window = window
        setupStatusItem()
        loadVisualizer()
        startHealthTimer()
        NSApp.activate(ignoringOtherApps: true)
    }

    func bundledRoot() -> String? {
        guard let resources = Bundle.main.resourcePath else { return nil }
        let root = (resources as NSString).appendingPathComponent("app")
        if FileManager.default.fileExists(atPath: root) {
            return root
        }
        return nil
    }

    func supportDir() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")
        let dir = base.appendingPathComponent("Jarvis")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    func startBackend() {
        guard let script = Bundle.main.path(forResource: "launch_backend", ofType: "sh") else {
            return
        }
        guard let root = bundledRoot() else { return }
        let python = ((Bundle.main.resourcePath ?? "") as NSString).appendingPathComponent("venv/bin/python3")
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/bash")
        task.arguments = [script]
        var env = ProcessInfo.processInfo.environment
        env["HOME"] = home
        env["JARVIS_ROOT"] = root
        env["JARVIS_HOME"] = supportDir().path
        env["JARVIS_PYTHON"] = python
        env["PATH"] = "\(home)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        env["TMPDIR"] = supportDir().appendingPathComponent(".run/tmp").path
        task.environment = env
        let log = supportDir().appendingPathComponent(".run/app.log")
        try? FileManager.default.createDirectory(at: log.deletingLastPathComponent(), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: log.path, contents: nil)
        if let handle = try? FileHandle(forWritingTo: log) {
            handle.seekToEndOfFile()
            task.standardOutput = handle
            task.standardError = handle
        }
        do {
            try task.run()
            task.waitUntilExit()
        } catch {
            return
        }
    }

    func loadVisualizer() {
        if let url = URL(string: "http://127.0.0.1:8777/") {
            webView?.load(URLRequest(url: url))
        }
    }

    func setupStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = item.button {
            if let image = NSImage(systemSymbolName: "circle.hexagongrid.fill", accessibilityDescription: "Jarvis") {
                image.isTemplate = true
                button.image = image
            } else {
                button.title = "J"
            }
            button.toolTip = "Jarvis"
        }
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Fenster zeigen", action: #selector(showJarvisWindow), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "Pause", action: #selector(pauseJarvis), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "Zuhören", action: #selector(listenJarvis), keyEquivalent: ""))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Beenden", action: #selector(quitJarvis), keyEquivalent: "q"))
        item.menu = menu
        statusItem = item
    }

    func busURL() -> URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("voice-line")
    }

    func startHealthTimer() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) { [weak self] in
            self?.healthArmed = true
        }
        healthTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            self?.checkBackend()
        }
    }

    func pidFileURLs() -> [URL] {
        let bus = busURL()
        let run = supportDir().appendingPathComponent(".run")
        return [
            bus.appendingPathComponent(".jarvis.pids"),
            bus.appendingPathComponent(".voice.pid"),
            bus.appendingPathComponent(".visualizer.pid"),
            run.appendingPathComponent("visualizer.pid"),
            run.appendingPathComponent("voice.pid"),
        ]
    }

    func listedPids() -> [pid_t] {
        var seen = Set<pid_t>()
        var pids: [pid_t] = []
        for url in pidFileURLs() {
            guard let text = try? String(contentsOf: url, encoding: .utf8) else { continue }
            for part in text.split(whereSeparator: { $0.isNewline || $0.isWhitespace }) {
                guard let value = Int32(part), value > 1 else { continue }
                let pid = pid_t(value)
                if seen.insert(pid).inserted {
                    pids.append(pid)
                }
            }
        }
        return pids
    }

    func backendAlive() -> Bool {
        let pids = listedPids()
        if pids.isEmpty {
            return false
        }
        for pid in pids {
            if kill(pid, 0) != 0 {
                return false
            }
        }
        return true
    }

    func noteBackend(ok: Bool) {
        if ok {
            healthFails = 0
            return
        }
        healthFails += 1
        if healthFails >= 3 {
            NSApp.terminate(nil)
        }
    }

    func checkBackend() {
        guard healthArmed else { return }
        if backendAlive() {
            noteBackend(ok: true)
            return
        }
        guard let url = URL(string: "http://127.0.0.1:8777/state") else { return }
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.5
        URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            let httpOk = (response as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async {
                self?.noteBackend(ok: httpOk)
            }
        }.resume()
    }

    func stopBackend() {
        for pid in listedPids() {
            kill(pid, SIGTERM)
        }
        let bus = busURL()
        for name in [".jarvis.pids", ".voice.pid", ".visualizer.pid"] {
            try? FileManager.default.removeItem(at: bus.appendingPathComponent(name))
        }
        let run = supportDir().appendingPathComponent(".run")
        for name in ["visualizer.pid", "voice.pid"] {
            try? FileManager.default.removeItem(at: run.appendingPathComponent(name))
        }
    }

    @objc func showJarvisWindow() {
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc func pauseJarvis() {
        let dir = busURL()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try? "1".write(to: dir.appendingPathComponent(".voice_pause"), atomically: true, encoding: .utf8)
    }

    @objc func listenJarvis() {
        try? FileManager.default.removeItem(at: busURL().appendingPathComponent(".voice_pause"))
        showJarvisWindow()
    }

    @objc func quitJarvis() {
        NSApp.terminate(nil)
    }

    func applicationWillTerminate(_ notification: Notification) {
        healthTimer?.invalidate()
        stopBackend()
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        return false
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showJarvisWindow()
        return true
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.setActivationPolicy(.regular)
app.delegate = delegate
app.run()
