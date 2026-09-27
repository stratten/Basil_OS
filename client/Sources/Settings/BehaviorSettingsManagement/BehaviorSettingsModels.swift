struct BehaviorSettings: Codable {
    // Known required fields
    var startOnStartup: Bool
    var showNotifications: Bool
    var minimizeToTray: Bool
    var holdEnabled: Bool
    var holdDuration: Double
    var enableMonitoringAtStartup: Bool
    var enableVoiceListenerAtStartup: Bool
    var allowMacContactsForGeneration: Bool
    // Dynamic additional fields storage
    private var additionalFields: [String: Any] = [:]
    
    enum CodingKeys: String, CodingKey, CaseIterable {
        case startOnStartup = "start_on_startup"
        case showNotifications = "show_notifications"
        case minimizeToTray = "minimize_to_tray"
        case holdEnabled = "hold_enabled"
        case holdDuration = "hold_duration"
        case enableMonitoringAtStartup = "enable_monitoring_at_startup"
        case enableVoiceListenerAtStartup = "enable_voice_listener_at_startup"
        case allowMacContactsForGeneration = "allow_mac_contacts_for_generation"
    }
    
    // Regular initializer
    init(startOnStartup: Bool, showNotifications: Bool, minimizeToTray: Bool, holdEnabled: Bool, holdDuration: Double, enableMonitoringAtStartup: Bool, enableVoiceListenerAtStartup: Bool = false, allowMacContactsForGeneration: Bool = false) {
        self.startOnStartup = startOnStartup
        self.showNotifications = showNotifications
        self.minimizeToTray = minimizeToTray
        self.holdEnabled = holdEnabled
        self.holdDuration = holdDuration
        self.enableMonitoringAtStartup = enableMonitoringAtStartup
        self.enableVoiceListenerAtStartup = enableVoiceListenerAtStartup
        self.allowMacContactsForGeneration = allowMacContactsForGeneration
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        
        #if DEBUG
        // Get all keys from the container for debugging
        let availableKeys = container.allKeys.map { $0.stringValue }
        DevLogger.shared.info("🔍 DECODE: Available keys in decoder container: \(availableKeys.joined(separator: ", "))", context: "BehaviorSettings")
        
        // Try to print the coding path to see where we are in the JSON structure
        if let codingPath = availableKeys.first.flatMap({ _ in container.codingPath.map { $0.stringValue } }) {
            DevLogger.shared.info("🔍 DECODE: Current coding path: \(codingPath.joined(separator: "."))", context: "BehaviorSettings")
        }
        #endif
        
        // Standard decoding for most fields
        startOnStartup = try container.decodeIfPresent(Bool.self, forKey: .startOnStartup) ?? false
        showNotifications = try container.decodeIfPresent(Bool.self, forKey: .showNotifications) ?? true
        minimizeToTray = try container.decodeIfPresent(Bool.self, forKey: .minimizeToTray) ?? true
        holdEnabled = try container.decodeIfPresent(Bool.self, forKey: .holdEnabled) ?? false
        holdDuration = try container.decodeIfPresent(Double.self, forKey: .holdDuration) ?? 0.5
        
        // ** CRITICAL FIX **
        // Ensure we check for both the original snake_case key and the converted camelCase key
        let snakeCaseKey = "enable_monitoring_at_startup" 
        let camelCaseKey = "enableMonitoringAtStartup"
        let rawContainer = try decoder.container(keyedBy: RawCodingKeys.self)
        
        #if DEBUG
        DevLogger.shared.info("🔍 DECODE: Checking for both \(snakeCaseKey) and \(camelCaseKey)", context: "BehaviorSettings")
        #endif
        
        // Try snake_case key first (original JSON format)
        if let rawKey = RawCodingKeys(stringValue: snakeCaseKey), rawContainer.contains(rawKey) {
            enableMonitoringAtStartup = try rawContainer.decode(Bool.self, forKey: rawKey)
            #if DEBUG
            DevLogger.shared.info("✅ DECODE: Found with snake_case key: enableMonitoringAtStartup = \(enableMonitoringAtStartup)", context: "BehaviorSettings")
            #endif
        }
        // Then try camelCase key (after key conversion strategy)
        else if let rawKey = RawCodingKeys(stringValue: camelCaseKey), rawContainer.contains(rawKey) {
            enableMonitoringAtStartup = try rawContainer.decode(Bool.self, forKey: rawKey)
            #if DEBUG
            DevLogger.shared.info("✅ DECODE: Found with camelCase key: enableMonitoringAtStartup = \(enableMonitoringAtStartup)", context: "BehaviorSettings")
            #endif
        }
        // Then try standard container
        else if container.contains(.enableMonitoringAtStartup) {
            enableMonitoringAtStartup = try container.decode(Bool.self, forKey: .enableMonitoringAtStartup)
            #if DEBUG
            DevLogger.shared.info("✅ DECODE: Found with CodingKeys: enableMonitoringAtStartup = \(enableMonitoringAtStartup)", context: "BehaviorSettings")
            #endif
        }
        // Default as last resort
        else {
            enableMonitoringAtStartup = false
            #if DEBUG
            DevLogger.shared.warning("⚠️ DECODE: enable_monitoring_at_startup was missing in response, defaulting to false", context: "BehaviorSettings")
            #endif
        }
        
        // Decode the new property with the same robust logic as enableMonitoringAtStartup
        let voiceSnakeCaseKey = "enable_voice_listener_at_startup"
        let voiceCamelCaseKey = "enableVoiceListenerAtStartup"
        
        #if DEBUG
        DevLogger.shared.info("🔍 DECODE: Checking for both \(voiceSnakeCaseKey) and \(voiceCamelCaseKey)", context: "BehaviorSettings")
        #endif
        
        // Try snake_case key first (original JSON format)
        if let rawKey = RawCodingKeys(stringValue: voiceSnakeCaseKey), rawContainer.contains(rawKey) {
            enableVoiceListenerAtStartup = try rawContainer.decode(Bool.self, forKey: rawKey)
            #if DEBUG
            DevLogger.shared.info("✅ DECODE: Found with snake_case key: enableVoiceListenerAtStartup = \(enableVoiceListenerAtStartup)", context: "BehaviorSettings")
            #endif
        }
        // Then try camelCase key (after key conversion strategy)
        else if let rawKey = RawCodingKeys(stringValue: voiceCamelCaseKey), rawContainer.contains(rawKey) {
            enableVoiceListenerAtStartup = try rawContainer.decode(Bool.self, forKey: rawKey)
            #if DEBUG
            DevLogger.shared.info("✅ DECODE: Found with camelCase key: enableVoiceListenerAtStartup = \(enableVoiceListenerAtStartup)", context: "BehaviorSettings")
            #endif
        }
        // Then try standard container
        else if container.contains(.enableVoiceListenerAtStartup) {
            enableVoiceListenerAtStartup = try container.decode(Bool.self, forKey: .enableVoiceListenerAtStartup)
            #if DEBUG
            DevLogger.shared.info("✅ DECODE: Found with CodingKeys: enableVoiceListenerAtStartup = \(enableVoiceListenerAtStartup)", context: "BehaviorSettings")
            #endif
        }
        // Default as last resort
        else {
            enableVoiceListenerAtStartup = false
            #if DEBUG
            DevLogger.shared.warning("⚠️ DECODE: enable_voice_listener_at_startup was missing in response, defaulting to false", context: "BehaviorSettings")
            #endif
        }
        
        allowMacContactsForGeneration = try container.decodeIfPresent(Bool.self, forKey: .allowMacContactsForGeneration) ?? false
        
        // Store any additional fields for forward compatibility
        let extraContainer = try decoder.container(keyedBy: RawCodingKeys.self)
        for key in extraContainer.allKeys {
            // Skip keys we already processed
            guard !CodingKeys.allCases.map({ $0.stringValue }).contains(key.stringValue) else {
                continue
            }
            
            // Try decoding as different types
            if let value = try? extraContainer.decode(String.self, forKey: key) {
                additionalFields[key.stringValue] = value
            } else if let value = try? extraContainer.decode(Bool.self, forKey: key) {
                additionalFields[key.stringValue] = value
            } else if let value = try? extraContainer.decode(Double.self, forKey: key) {
                additionalFields[key.stringValue] = value
            } else if let value = try? extraContainer.decode(Int.self, forKey: key) {
                additionalFields[key.stringValue] = value
            }
            // Can't directly decode [String: Any] with standard Codable
        }
    }
    
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        
        // Encode known fields
        try container.encode(startOnStartup, forKey: .startOnStartup)
        try container.encode(showNotifications, forKey: .showNotifications)
        try container.encode(minimizeToTray, forKey: .minimizeToTray)
        try container.encode(holdEnabled, forKey: .holdEnabled)
        try container.encode(holdDuration, forKey: .holdDuration)
        try container.encode(enableMonitoringAtStartup, forKey: .enableMonitoringAtStartup)
        try container.encode(enableVoiceListenerAtStartup, forKey: .enableVoiceListenerAtStartup)
        try container.encode(allowMacContactsForGeneration, forKey: .allowMacContactsForGeneration)
        
        // Skip encoding additional fields for now, as we're not modifying them
    }
    
    // RawCodingKeys allows access to keys by string
    private struct RawCodingKeys: CodingKey {
        var stringValue: String
        var intValue: Int?
        
        init?(stringValue: String) {
            self.stringValue = stringValue
            self.intValue = nil
        }
        
        init?(intValue: Int) {
            self.stringValue = "\(intValue)"
            self.intValue = intValue
        }
    }
}

// API response wrapper
struct BehaviorSettingsResponse: Codable {
    let status: String
    let settings: BehaviorSettings
}
