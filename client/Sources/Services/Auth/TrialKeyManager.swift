import Foundation
import Security

/// Manages trial key generation and storage for unauthenticated API access.
/// Trial keys allow up to $1 of API usage without requiring account creation.
final class TrialKeyManager {
    // MARK: - Singleton
    static let shared = TrialKeyManager()
    
    // MARK: - Properties
    private let fileName = "trial_key"
    private var cachedKey: String?
    
    private var trialKeyURL: URL {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let bundleId = Bundle.main.bundleIdentifier ?? "com.stratten.basil"
        let basilDir = appSupport.appendingPathComponent(bundleId, isDirectory: true)
        return basilDir.appendingPathComponent(fileName)
    }
    
    // MARK: - Initialization
    private init() {}
    
    // MARK: - Public Methods
    
    /// Get existing trial key or generate a new one.
    /// The key is cached in memory after first access for performance.
    func getOrCreateTrialKey() -> String {
        // Return cached key if available
        if let cached = cachedKey {
            return cached
        }
        
        // Try to read existing key from file
        if let existing = try? String(contentsOf: trialKeyURL, encoding: .utf8) {
            let key = existing.trimmingCharacters(in: .whitespacesAndNewlines)
            if !key.isEmpty && isValidTrialKeyFormat(key) {
                cachedKey = key
                #if DEBUG
                DevLogger.shared.info("🎫 Loaded existing trial key from file", context: "TrialKeyManager")
                #endif
                return key
            }
        }
        
        // Generate new key
        let key = generateTrialKey()
        
        // Ensure directory exists
        let directory = trialKeyURL.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        
        // Write to file
        do {
            try key.write(to: trialKeyURL, atomically: true, encoding: .utf8)
            #if DEBUG
            DevLogger.shared.info("🎫 Generated and saved new trial key", context: "TrialKeyManager")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("🎫 Failed to save trial key: \(error.localizedDescription)", context: "TrialKeyManager")
            #endif
        }
        
        cachedKey = key
        return key
    }
    
    /// Check if a trial key exists (without generating one).
    func hasTrialKey() -> Bool {
        if cachedKey != nil {
            return true
        }
        return FileManager.default.fileExists(atPath: trialKeyURL.path)
    }
    
    /// Clear the cached trial key (forces re-read from file on next access).
    func clearCache() {
        cachedKey = nil
    }
    
    // MARK: - Private Methods
    
    /// Generate a new trial key with embedded version and timestamp metadata.
    /// Format: basil_trial_v{version}_{unix_timestamp}_{random_64_hex_chars}
    private func generateTrialKey() -> String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.0.0"
        let timestamp = Int(Date().timeIntervalSince1970)
        
        // Generate 64 random hex characters (32 bytes) using SecRandomCopyBytes
        var randomBytes = [UInt8](repeating: 0, count: 32)
        let status = SecRandomCopyBytes(kSecRandomDefault, randomBytes.count, &randomBytes)
        
        let randomHex: String
        if status == errSecSuccess {
            randomHex = randomBytes.map { String(format: "%02x", $0) }.joined()
        } else {
            // Fallback to UUID-based generation if SecRandomCopyBytes fails
            randomHex = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
                + UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        }
        
        return "basil_trial_v\(version)_\(timestamp)_\(randomHex)"
    }
    
    /// Validate that a key matches the expected trial key format.
    private func isValidTrialKeyFormat(_ key: String) -> Bool {
        // Expected format: basil_trial_v{version}_{timestamp}_{64_hex_chars}
        // Example: basil_trial_v1.2.0_1706659200_a4f8c2e91b3d5f7a...
        let pattern = #"^basil_trial_v[\d.]+_\d+_[a-f0-9]{64}$"#
        return key.range(of: pattern, options: .regularExpression) != nil
    }
}
