import Foundation

// MARK: - Backend Management
extension AppDelegate {
    
    @MainActor
    func startBackendProcess() async {
        #if DEBUG
        DevLogger.shared.info("Entering startBackendProcess function", context: "Backend")
        #endif
        NSLog("🚀 BASIL: Entering startBackendProcess function")

        // Get Writable Application Support Path
        let fileManager = FileManager.default
        guard let appSupportBaseURL = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
            #if DEBUG
            DevLogger.shared.error("Could not find Application Support directory URL.", context: "Backend")
            #endif
            NSLog("❌ BASIL: Could not find Application Support directory URL.")
            return
        }
        guard let bundleID = Bundle.main.bundleIdentifier else {
            #if DEBUG
            DevLogger.shared.error("Could not get bundle identifier to create app-specific support path.", context: "Backend")
            #endif
            NSLog("❌ BASIL: Could not get bundle identifier to create app-specific support path.")
            return
        }
        let writableAppSupportURL = appSupportBaseURL.appendingPathComponent(bundleID)
        let writableAppSupportPath = writableAppSupportURL.path

        do {
            try fileManager.createDirectory(at: writableAppSupportURL, withIntermediateDirectories: true, attributes: nil)
            #if DEBUG
            DevLogger.shared.info("Ensured writable Application Support directory exists at: \(writableAppSupportPath)", context: "Backend")
            #endif
            NSLog("✅ BASIL: Ensured writable Application Support directory exists at: %@", writableAppSupportPath)
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to create writable Application Support directory at \(writableAppSupportPath): \(error.localizedDescription)", context: "Backend")
            #endif
            NSLog("❌ BASIL: Failed to create writable Application Support directory at %@: %@", writableAppSupportPath, error.localizedDescription)
            return
        }

        // Get App Bundle Resources Path
        guard let bundleResourcePath = Bundle.main.resourcePath else {
            #if DEBUG
            DevLogger.shared.error("Failed to get bundle resource path.", context: "Backend")
            #endif
            NSLog("❌ BASIL: Failed to get bundle resource path.")
            return
        }
        #if DEBUG
        DevLogger.shared.info("bundleResourcePath = \(bundleResourcePath)", context: "Backend")
        #endif
        NSLog("🗺️ BASIL: bundleResourcePath = %@", bundleResourcePath)

        let scriptNameInBundle = "backend/start_backend.sh" 
        #if DEBUG
        DevLogger.shared.info("scriptNameInBundle = \(scriptNameInBundle)", context: "Backend")
        #endif
        NSLog("📜 BASIL: scriptNameInBundle = %@", scriptNameInBundle)
        
        let fullScriptPathInBundle = "\(bundleResourcePath)/\(scriptNameInBundle)"

        // Try without the initial cd, just execute the script with /bin/bash and full paths
        let shellCommandToExecute = "/bin/bash \"\(fullScriptPathInBundle)\" \"\(writableAppSupportPath)\" \"\(bundleResourcePath)\""
        
        #if DEBUG
        DevLogger.shared.info("shellCommandToExecute = \(shellCommandToExecute)", context: "Backend")
        #endif
        NSLog("🔩 BASIL: shellCommandToExecute construction complete. (Full command logged in DEBUG mode)")

        // Re-ensure this guard is present
        guard fileManager.fileExists(atPath: fullScriptPathInBundle) else {
            #if DEBUG
            DevLogger.shared.error("Backend script NOT FOUND at derived fullScriptPathInBundle: \(fullScriptPathInBundle)", context: "Backend")
            #endif
            NSLog("❌ BASIL: Backend script NOT FOUND at derived fullScriptPathInBundle: %@", fullScriptPathInBundle)
            return
        }
        #if DEBUG
        DevLogger.shared.info("Backend script confirmed to exist at: \(fullScriptPathInBundle)", context: "Backend")
        #endif
        NSLog("👍 BASIL: Backend script confirmed to exist at: %@", fullScriptPathInBundle)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = ["-c", shellCommandToExecute]

        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.standardOutput = outputPipe
        process.standardError = errorPipe
        
        #if DEBUG
        DevLogger.shared.info("About to call Process.run() for: /bin/bash -c \"\(shellCommandToExecute)\"", context: "Backend")
        #endif
        NSLog("⚙️ BASIL: About to call Process.run() for bash -c command.")
        
        do {
            try process.run()
            #if DEBUG
            DevLogger.shared.info("Swift Process.run() completed for bash -c command.", context: "Backend")
            #endif
            NSLog("✅ BASIL: Swift Process.run() completed for bash -c command.")

            let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
            if let outputString = String(data: outputData, encoding: .utf8), !outputString.isEmpty {
                #if DEBUG
                DevLogger.shared.info("Backend STDOUT: \(outputString)", context: "Backend")
                #endif
                NSLog("📜 BASIL Backend STDOUT: %@", outputString)
            } else {
                #if DEBUG
                DevLogger.shared.info("Backend STDOUT: (empty)", context: "Backend")
                #endif
                NSLog("💨 BASIL Backend STDOUT: (empty)")
            }

            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
            if let errorString = String(data: errorData, encoding: .utf8), !errorString.isEmpty {
                #if DEBUG
                DevLogger.shared.error("Backend STDERR: \(errorString)", context: "Backend")
                #endif
                NSLog("‼️ BASIL Backend STDERR: %@", errorString)
            } else {
                #if DEBUG
                DevLogger.shared.info("Backend STDERR: (empty)", context: "Backend")
                #endif
                NSLog("👍 BASIL Backend STDERR: (empty)")
            }
            
            process.waitUntilExit()
            #if DEBUG
            DevLogger.shared.info("Backend script process exited with status: \(process.terminationStatus)", context: "Backend")
            #endif
            NSLog("🏁 BASIL: Backend script process exited with status: %d", process.terminationStatus)

        } catch {
            #if DEBUG
            DevLogger.shared.error("Swift failed to run backend process: \(error.localizedDescription)", context: "Backend")
            #endif
            NSLog("❌ BASIL: Swift failed to run backend process: %@", error.localizedDescription)
            return
        }
        
        if process.terminationStatus == 0 {
             await waitForBackendReady(appSupportPath: writableAppSupportPath)
        } else {
            #if DEBUG
            DevLogger.shared.error("Backend script failed (exit code \(process.terminationStatus)), not attempting to wait for readiness.", context: "Backend")
            #endif
            NSLog("💔 BASIL: Backend script failed (exit code %d), not attempting to wait for readiness.", process.terminationStatus)
        }
    }
    
    // Lightweight helper with 1s timeout
    private func isBackendHealthy(port: Int) async -> Bool {
        guard let url = URL(string: "http://127.0.0.1:\(port)/health") else { return false }
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.0
        do {
            let (_, resp) = try await URLSession.shared.data(for: request)
            if let http = resp as? HTTPURLResponse, http.statusCode == 200 { return true }
        } catch { }
        return false
    }
    
    @MainActor
    private func waitForBackendReady(appSupportPath: String) async {
        #if DEBUG
        DevLogger.shared.info("waitForBackendReady checking for port file at: \(appSupportPath)/server_port", context: "Backend")
        #endif
        NSLog("⏳ BASIL: waitForBackendReady checking for port file at: %@/server_port", appSupportPath)
        
        let serverPortPath = "\(appSupportPath)/server_port"
        var backendPort: Int?
        
        // First, wait for port file to appear and parse
        for i in 0..<90 { // up to ~45s with 0.5s steps before health polling
            if FileManager.default.fileExists(atPath: serverPortPath) {
                do {
                    let portString = try String(contentsOfFile: serverPortPath).trimmingCharacters(in: .whitespacesAndNewlines)
                    if let port = Int(portString) {
                        backendPort = port
                        #if DEBUG
                        DevLogger.shared.info("Found backend port file after \(Double(i) * 0.5) seconds: port \(port) at \(serverPortPath)", context: "Backend")
                        #endif
                        NSLog("Found backend port file after \(Double(i) * 0.5) seconds: port \(port) at \(serverPortPath)")
                        break
                    }
                } catch {
                    #if DEBUG
                    DevLogger.shared.warning("Port file exists at \(serverPortPath) but couldn't read it: \(error)", context: "Backend")
                    #endif
                    NSLog("Port file exists at \(serverPortPath) but couldn't read it: %@", error.localizedDescription)
                }
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        
        guard let port = backendPort else {
            #if DEBUG
            DevLogger.shared.error("Backend failed to write port file to \(serverPortPath) within 45 seconds", context: "Backend")
            #endif
            NSLog("Backend failed to write port file to \(serverPortPath) within 45 seconds")
            return
        }
        
        #if DEBUG
        DevLogger.shared.info("Port file found (port \(port)), now polling health at localhost:\(port)", context: "Backend")
        #endif
        NSLog("Port file found (port \(port)), now polling health at localhost:\(port)")
        
        // Poll /health with exponential backoff: 200ms -> 1s
        var backoffMs = 200
        for _ in 0..<90 { // up to ~45s
            if await isBackendHealthy(port: port) {
                #if DEBUG
                DevLogger.shared.info("✅ Backend healthy.", context: "Backend")
                #endif
                NSLog("✅ BASIL Backend healthy.")
                return
            }
            try? await Task.sleep(nanoseconds: UInt64(backoffMs) * 1_000_000)
            backoffMs = min(backoffMs + 200, 1000)
        }
        #if DEBUG
        DevLogger.shared.error("❌ Backend failed to become healthy within 45 seconds on port \(port)", context: "Backend")
        #endif
        NSLog("❌ BASIL Backend failed to become healthy within 45 seconds on port \(port)")
    }
} 