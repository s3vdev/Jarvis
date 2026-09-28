import Cocoa
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow?
    var webView: WKWebView?
    var statusItem: NSStatusItem?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let view = WKWebView(frame: NSRect(x: 0, y: 0, width: 500, height: 520))
        view.setValue(false, forKey: "drawsBackground")
        if let url = URL(string: "http://127.0.0.1:8777/") {
            view.load(URLRequest(url: url))
        }
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
        NSApp.activate(ignoringOtherApps: true)
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
