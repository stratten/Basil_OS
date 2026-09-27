import AppKit
import Darwin

switch BasilRuntimeProfile.bootstrap(arguments: CommandLine.arguments) {
case .failure(let message):
    FileHandle.standardError.write(Data("\(message)\n".utf8))
    exit(64)
case .success(let profile):
    BasilRuntimeProfile.install(profile)
    // Create delegate first, then assign it before app init completes
    let delegate = AppDelegate()
    let app = NSApplication.shared
    app.delegate = delegate
    app.run()
}