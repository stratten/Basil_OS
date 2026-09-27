import Foundation
import AppKit

/// Service for capturing user-selected screen regions using macOS's built-in interactive capture
/// Uses `screencapture -i -s` which provides native crosshair cursor, selection UI, and proper event blocking
@MainActor
class ScreenRegionCaptureService: ObservableObject {
    static let shared = ScreenRegionCaptureService()
    
    // MARK: - Result Types
    
    /// Reuse the same CaptureResult type as WindowCaptureService for compatibility
    typealias CaptureResult = WindowCaptureService.CaptureResult
    
    // MARK: - Private Properties
    
    private var isCapturing = false
    
    private init() {}
    
    // MARK: - Public Interface
    
    /// Present the native macOS region selection UI and capture the selected region
    /// Uses `screencapture -i -s` which provides:
    /// - Crosshair cursor
    /// - Click-drag selection with visual feedback
    /// - Proper event blocking (background apps don't receive clicks)
    /// - Escape to cancel
    /// Returns a CaptureResult with the captured image path or error
    func captureSelectedRegion() async -> CaptureResult {
        guard !isCapturing else {
            #if DEBUG
            DevLogger.shared.warning("Region capture already in progress", context: "ScreenRegionCaptureService")
            #endif
            return CaptureResult.failure(appName: "Unknown", windowTitle: "Unknown", error: "Capture already in progress")
        }
        
        isCapturing = true
        defer { isCapturing = false }
        
        #if DEBUG
        DevLogger.shared.info("Starting native region selection with screencapture -i -s", context: "ScreenRegionCaptureService")
        #endif
        
        // Generate temp file path
        let timestamp = Int(Date().timeIntervalSince1970 * 1000)
        let tempDir = NSHomeDirectory() + "/.basil/data/temp/"
        
        // Ensure directory exists
        do {
            try FileManager.default.createDirectory(atPath: tempDir, withIntermediateDirectories: true, attributes: nil)
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to create temp directory: \(error)", context: "ScreenRegionCaptureService")
            #endif
            return CaptureResult.failure(
                appName: "Unknown",
                windowTitle: "Unknown",
                error: "Failed to create temp directory: \(error.localizedDescription)"
            )
        }
        
        let capturePath = "\(tempDir)region_capture_\(timestamp).png"
        
        #if DEBUG
        DevLogger.shared.info("Capture path: \(capturePath)", context: "ScreenRegionCaptureService")
        #endif
        
        // Use macOS's built-in interactive screenshot tool
        // -i: Interactive mode (click-drag to select region)
        // -s: Selection mode only (no window selection)
        // -x: No sound
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        task.arguments = ["-i", "-s", "-x", capturePath]
        
        do {
            try task.run()
            
            // Wait for the interactive capture to complete
            // This blocks until the user finishes selecting or presses Escape
            task.waitUntilExit()
            
            #if DEBUG
            DevLogger.shared.info("screencapture exited with status: \(task.terminationStatus)", context: "ScreenRegionCaptureService")
            #endif
            
            // Check if capture was successful
            // Exit code 0 = success, non-zero = cancelled or error
            if task.terminationStatus == 0 && FileManager.default.fileExists(atPath: capturePath) {
                // Verify file size
                do {
                    let attributes = try FileManager.default.attributesOfItem(atPath: capturePath)
                    let fileSize = attributes[.size] as? Int ?? 0
                    
                    #if DEBUG
                    DevLogger.shared.info("Region capture successful: \(fileSize) bytes", context: "ScreenRegionCaptureService")
                    #endif
                    
                    if fileSize < 100 {
                        #if DEBUG
                        DevLogger.shared.warning("Capture file suspiciously small: \(fileSize) bytes", context: "ScreenRegionCaptureService")
                        #endif
                        return CaptureResult.failure(
                            appName: "Unknown",
                            windowTitle: "Unknown",
                            error: "Capture file too small - possible permission issue"
                        )
                    }
                    
                    return CaptureResult.success(
                        imagePath: capturePath,
                        appName: "Screen Region",
                        windowTitle: "Selected Region",
                        bundleIdentifier: nil
                    )
                } catch {
                    #if DEBUG
                    DevLogger.shared.error("Failed to verify capture file: \(error)", context: "ScreenRegionCaptureService")
                    #endif
                    // File exists but couldn't get attributes - still try to use it
                    return CaptureResult.success(
                        imagePath: capturePath,
                        appName: "Screen Region",
                        windowTitle: "Selected Region",
                        bundleIdentifier: nil
                    )
                }
            } else {
                // User cancelled (pressed Escape) or capture failed
                #if DEBUG
                DevLogger.shared.info("Region capture cancelled or failed", context: "ScreenRegionCaptureService")
                #endif
                
                // Clean up any partial file
                try? FileManager.default.removeItem(atPath: capturePath)
                
                return CaptureResult.failure(
                    appName: "Unknown",
                    windowTitle: "Unknown",
                    error: "Region selection cancelled by user"
                )
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to run screencapture: \(error)", context: "ScreenRegionCaptureService")
            #endif
            return CaptureResult.failure(
                appName: "Unknown",
                windowTitle: "Unknown",
                error: "Failed to execute screen capture: \(error.localizedDescription)"
            )
        }
    }
}
