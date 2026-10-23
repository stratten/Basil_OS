import Foundation

// MARK: - Command Approval Models

/// Represents a command that needs user approval before execution
struct ExecutionApprovalRequest: Codable {
    let needsApproval: Bool
    let reason: String
    let riskLevel: RiskLevel
    let isBlocked: Bool
    let blockReason: String?
    let matchedPatternId: String?
    
    enum CodingKeys: String, CodingKey {
        case needsApproval = "needs_approval"
        case reason
        case riskLevel = "risk_level"
        case isBlocked = "is_blocked"
        case blockReason = "block_reason"
        case matchedPatternId = "matched_pattern_id"
    }
    
    enum RiskLevel: String, Codable {
        case low
        case medium
        case high
        case critical
        
        var color: String {
            switch self {
            case .low: return "green"
            case .medium: return "yellow"
            case .high: return "orange"
            case .critical: return "red"
            }
        }
        
        var displayName: String {
            switch self {
            case .low: return "Low Risk"
            case .medium: return "Medium Risk"
            case .high: return "High Risk"
            case .critical: return "Critical Risk"
            }
        }
    }
}

/// User's decision on command approval
struct ExecutionApprovalDecision: Codable {
    let approvalId: String
    let command: String
    let approved: Bool
    let rememberChoice: Bool
    let patternType: String
    let description: String?
    
    enum CodingKeys: String, CodingKey {
        case approvalId = "approval_id"
        case command
        case approved
        case rememberChoice = "remember_choice"
        case patternType = "pattern_type"
        case description
    }
    
    init(approvalId: String = "", command: String, approved: Bool, rememberChoice: Bool = false, patternType: String = "exact", description: String? = nil) {
        self.approvalId = approvalId
        self.command = command
        self.approved = approved
        self.rememberChoice = rememberChoice
        self.patternType = patternType
        self.description = description
    }
}

/// Response from approval decision
struct ExecutionApprovalDecisionResponse: Codable {
    let success: Bool
    let message: String
    let patternId: String?
    
    enum CodingKeys: String, CodingKey {
        case success
        case message
        case patternId = "pattern_id"
    }
}

/// Command approval settings
struct ExecutionApprovalSettings: Codable {
    let approvalMode: ApprovalMode
    let showFullCommandInPrompt: Bool
    let rememberChoiceOption: Bool
    let autoApproveReadOnly: Bool
    let blockDangerousPatterns: Bool
    let whitelistedCount: Int
    let safeExecutionMode: Bool
    let approvalTimeoutSeconds: Int
    let timeoutBehavior: TimeoutBehavior
    
    enum CodingKeys: String, CodingKey {
        case approvalMode = "approval_mode"
        case showFullCommandInPrompt = "show_full_command_in_prompt"
        case rememberChoiceOption = "remember_choice_option"
        case autoApproveReadOnly = "auto_approve_read_only"
        case blockDangerousPatterns = "block_dangerous_patterns"
        case whitelistedCount = "whitelisted_count"
        case safeExecutionMode = "safe_execution_mode"
        case approvalTimeoutSeconds = "approval_timeout_seconds"
        case timeoutBehavior = "timeout_behavior"
    }
    
    enum ApprovalMode: String, Codable {
        case alwaysApprove = "always_approve"
        case whitelistOnly = "whitelist_only"
        case alwaysPrompt = "always_prompt"
        
        var displayName: String {
            switch self {
            case .alwaysApprove: return "Always Approve (Risky)"
            case .whitelistOnly: return "Whitelist Only (Recommended)"
            case .alwaysPrompt: return "Always Prompt (Safest)"
            }
        }
    }
    
    enum TimeoutBehavior: String, Codable {
        case waitForever = "wait_forever"
        case denyOnTimeout = "deny_on_timeout"
        case retryAlternative = "retry_alternative"
        
        var displayName: String {
            switch self {
            case .waitForever: return "Always wait for my response"
            case .denyOnTimeout: return "Deny after timeout"
            case .retryAlternative: return "Deny after timeout and attempt alternative"
            }
        }
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        approvalMode = try container.decode(ApprovalMode.self, forKey: .approvalMode)
        showFullCommandInPrompt = try container.decode(Bool.self, forKey: .showFullCommandInPrompt)
        rememberChoiceOption = try container.decode(Bool.self, forKey: .rememberChoiceOption)
        autoApproveReadOnly = try container.decode(Bool.self, forKey: .autoApproveReadOnly)
        blockDangerousPatterns = try container.decode(Bool.self, forKey: .blockDangerousPatterns)
        whitelistedCount = try container.decode(Int.self, forKey: .whitelistedCount)
        safeExecutionMode = try container.decodeIfPresent(Bool.self, forKey: .safeExecutionMode) ?? false
        approvalTimeoutSeconds = try container.decodeIfPresent(Int.self, forKey: .approvalTimeoutSeconds) ?? 120
        timeoutBehavior = try container.decodeIfPresent(TimeoutBehavior.self, forKey: .timeoutBehavior) ?? .waitForever
    }
    
    init(approvalMode: ApprovalMode, showFullCommandInPrompt: Bool, rememberChoiceOption: Bool, autoApproveReadOnly: Bool, blockDangerousPatterns: Bool, whitelistedCount: Int, safeExecutionMode: Bool = false, approvalTimeoutSeconds: Int = 120, timeoutBehavior: TimeoutBehavior = .waitForever) {
        self.approvalMode = approvalMode
        self.showFullCommandInPrompt = showFullCommandInPrompt
        self.rememberChoiceOption = rememberChoiceOption
        self.autoApproveReadOnly = autoApproveReadOnly
        self.blockDangerousPatterns = blockDangerousPatterns
        self.whitelistedCount = whitelistedCount
        self.safeExecutionMode = safeExecutionMode
        self.approvalTimeoutSeconds = approvalTimeoutSeconds
        self.timeoutBehavior = timeoutBehavior
    }
}

/// Whitelist pattern model
struct WhitelistPattern: Codable, Identifiable {
    let id: String
    let pattern: String
    let patternType: String
    let description: String
    let addedDate: Date?
    let lastUsed: Date?
    let useCount: Int
    let riskLevel: String
    
    enum CodingKeys: String, CodingKey {
        case id
        case pattern
        case patternType = "pattern_type"
        case description
        case addedDate = "added_date"
        case lastUsed = "last_used"
        case useCount = "use_count"
        case riskLevel = "risk_level"
    }
}

/// Response containing whitelist patterns
struct WhitelistResponse: Codable {
    let patterns: [WhitelistPattern]
    let totalCount: Int
    
    enum CodingKeys: String, CodingKey {
        case patterns
        case totalCount = "total_count"
    }
}

/// Request to add a pattern to whitelist
struct AddWhitelistRequest: Codable {
    let pattern: String
    let patternType: String
    let description: String
    let riskLevel: String
    
    enum CodingKeys: String, CodingKey {
        case pattern
        case patternType = "pattern_type"
        case description
        case riskLevel = "risk_level"
    }
    
    init(pattern: String, patternType: String = "exact", description: String = "", riskLevel: String = "low") {
        self.pattern = pattern
        self.patternType = patternType
        self.description = description
        self.riskLevel = riskLevel
    }
}

/// Request to update an existing whitelist pattern
struct UpdateWhitelistRequest: Codable {
    let pattern: String
    let patternType: String
    let description: String
    
    enum CodingKeys: String, CodingKey {
        case pattern
        case patternType = "pattern_type"
        case description
    }
    
    init(pattern: String, patternType: String, description: String) {
        self.pattern = pattern
        self.patternType = patternType
        self.description = description
    }
}

/// Request to update command approval settings
struct UpdateApprovalSettingsRequest: Codable {
    let approvalMode: String?
    let showFullCommandInPrompt: Bool?
    let rememberChoiceOption: Bool?
    let autoApproveReadOnly: Bool?
    let blockDangerousPatterns: Bool?
    let safeExecutionMode: Bool?
    let approvalTimeoutSeconds: Int?
    let timeoutBehavior: String?
    
    enum CodingKeys: String, CodingKey {
        case approvalMode = "approval_mode"
        case showFullCommandInPrompt = "show_full_command_in_prompt"
        case rememberChoiceOption = "remember_choice_option"
        case autoApproveReadOnly = "auto_approve_read_only"
        case blockDangerousPatterns = "block_dangerous_patterns"
        case safeExecutionMode = "safe_execution_mode"
        case approvalTimeoutSeconds = "approval_timeout_seconds"
        case timeoutBehavior = "timeout_behavior"
    }
    
    init(
        approvalMode: String? = nil,
        showFullCommandInPrompt: Bool? = nil,
        rememberChoiceOption: Bool? = nil,
        autoApproveReadOnly: Bool? = nil,
        blockDangerousPatterns: Bool? = nil,
        safeExecutionMode: Bool? = nil,
        approvalTimeoutSeconds: Int? = nil,
        timeoutBehavior: String? = nil
    ) {
        self.approvalMode = approvalMode
        self.showFullCommandInPrompt = showFullCommandInPrompt
        self.rememberChoiceOption = rememberChoiceOption
        self.autoApproveReadOnly = autoApproveReadOnly
        self.blockDangerousPatterns = blockDangerousPatterns
        self.safeExecutionMode = safeExecutionMode
        self.approvalTimeoutSeconds = approvalTimeoutSeconds
        self.timeoutBehavior = timeoutBehavior
    }
}

