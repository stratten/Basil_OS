import Foundation

// MARK: - Analysis Mode Enum

enum AnalysisMode: String, CaseIterable, Codable {
    case actionItems = "action_items"
    case suggestedActions = "suggested_actions"
    case summary = "summary"
    case decisions = "decisions"
    case questions = "questions"
    case sentiment = "sentiment"
    case custom = "custom"
    
    var displayName: String {
        switch self {
        case .actionItems:
            return "Action Items"
        case .suggestedActions:
            return "To-Do Candidates"
        case .summary:
            return "Summary"
        case .decisions:
            return "Key Decisions"
        case .questions:
            return "Questions & Answers"
        case .sentiment:
            return "Sentiment Analysis"
        case .custom:
            return "Custom Analysis"
        }
    }
    
    var iconName: String {
        switch self {
        case .actionItems:
            return "checklist"
        case .suggestedActions:
            return "sparkles"
        case .summary:
            return "doc.text"
        case .decisions:
            return "checkmark.circle"
        case .questions:
            return "questionmark.circle"
        case .sentiment:
            return "chart.line.uptrend.xyaxis"
        case .custom:
            return "wand.and.stars"
        }
    }
    
    var description: String {
        switch self {
        case .actionItems:
            return "Extract tasks and action items"
        case .suggestedActions:
            return "Identify action items Basil can help execute"
        case .summary:
            return "Generate meeting summary"
        case .decisions:
            return "Identify key decisions"
        case .questions:
            return "Extract Q&A pairs"
        case .sentiment:
            return "Analyze tone and engagement"
        case .custom:
            return "Custom analysis"
        }
    }
}

// MARK: - Meeting Action Proposal

struct MeetingActionProposal: Codable, Identifiable {
    let id: String
    let sourceActionItemIndex: Int?
    let sourceActionItemIndexes: [Int]?
    let sourceTask: String
    let sourceContext: String?
    let sourceTimestamp: Double?
    let sourceSpeaker: String?
    let suggestedAgentTask: String
    let capabilityType: String
    let confidence: Double
    let whyBasilCanHelp: String
    let missingInformation: [String]
    let requiresUserConfirmation: Bool
    let executionMode: String?
    let workspaceSource: String
    var executionStatus: String
    var submittedAgentTaskId: String?
    var todoId: String?

    init(
        id: String,
        sourceActionItemIndex: Int?,
        sourceActionItemIndexes: [Int]? = nil,
        sourceTask: String,
        sourceContext: String?,
        sourceTimestamp: Double?,
        sourceSpeaker: String?,
        suggestedAgentTask: String,
        capabilityType: String,
        confidence: Double,
        whyBasilCanHelp: String,
        missingInformation: [String],
        requiresUserConfirmation: Bool,
        executionMode: String? = nil,
        workspaceSource: String,
        executionStatus: String,
        submittedAgentTaskId: String?,
        todoId: String?
    ) {
        self.id = id
        self.sourceActionItemIndex = sourceActionItemIndex
        self.sourceActionItemIndexes = sourceActionItemIndexes
        self.sourceTask = sourceTask
        self.sourceContext = sourceContext
        self.sourceTimestamp = sourceTimestamp
        self.sourceSpeaker = sourceSpeaker
        self.suggestedAgentTask = suggestedAgentTask
        self.capabilityType = capabilityType
        self.confidence = confidence
        self.whyBasilCanHelp = whyBasilCanHelp
        self.missingInformation = missingInformation
        self.requiresUserConfirmation = requiresUserConfirmation
        self.executionMode = executionMode
        self.workspaceSource = workspaceSource
        self.executionStatus = executionStatus
        self.submittedAgentTaskId = submittedAgentTaskId
        self.todoId = todoId
    }
    
    enum CodingKeys: String, CodingKey {
        case id
        case sourceActionItemIndex = "source_action_item_index"
        case sourceActionItemIndexes = "source_action_item_indexes"
        case sourceTask = "source_task"
        case sourceContext = "source_context"
        case sourceTimestamp = "source_timestamp"
        case sourceSpeaker = "source_speaker"
        case suggestedAgentTask = "suggested_agent_task"
        case capabilityType = "capability_type"
        case confidence
        case whyBasilCanHelp = "why_basil_can_help"
        case missingInformation = "missing_information"
        case requiresUserConfirmation = "requires_user_confirmation"
        case executionMode = "execution_mode"
        case workspaceSource = "workspace_source"
        case executionStatus = "execution_status"
        case submittedAgentTaskId = "submitted_agent_task_id"
        case todoId = "todo_id"
    }
}

// MARK: - Action Item

struct ActionItem: Codable, Identifiable {
    let id = UUID()
    let task: String
    let assignedTo: String?
    let deadline: String?
    let priority: String?
    let context: String
    let timestamp: Double
    let speaker: String?
    
    enum CodingKeys: String, CodingKey {
        case task
        case assignedTo = "assigned_to"
        case deadline
        case priority
        case context
        case timestamp
        case speaker
    }
}

// MARK: - Decision

struct Decision: Codable, Identifiable {
    let id = UUID()
    let decision: String
    let rationale: String?
    let decidedBy: String?
    let timestamp: Double
    let context: String
    let impact: String?
    
    enum CodingKeys: String, CodingKey {
        case decision
        case rationale
        case decidedBy = "decided_by"
        case timestamp
        case context
        case impact
    }
}

// MARK: - Question Answer

struct QuestionAnswer: Codable, Identifiable {
    let id = UUID()
    let question: String
    let answer: String
    let asker: String?
    let responder: String?
    let timestamp: Double
    let context: String
    let resolved: Bool
    
    enum CodingKeys: String, CodingKey {
        case question
        case answer
        case asker
        case responder
        case timestamp
        case context
        case resolved
    }
}

// MARK: - Sentiment Analysis

struct SentimentAnalysis: Codable {
    let overallSentiment: String
    let sentimentScore: Double
    let engagementLevel: String
    let speakerSentiments: [String: SpeakerSentiment]?
    let positiveMoments: [SentimentMoment]?
    let negativeMoments: [SentimentMoment]?
    let toneIndicators: [String]?
    
    enum CodingKeys: String, CodingKey {
        case overallSentiment = "overall_sentiment"
        case sentimentScore = "sentiment_score"
        case engagementLevel = "engagement_level"
        case speakerSentiments = "speaker_sentiments"
        case positiveMoments = "positive_moments"
        case negativeMoments = "negative_moments"
        case toneIndicators = "tone_indicators"
    }
}

struct SpeakerSentiment: Codable {
    let sentiment: String
    let engagement: String
    let keyContributions: String
    
    enum CodingKeys: String, CodingKey {
        case sentiment
        case engagement
        case keyContributions = "key_contributions"
    }
}

struct SentimentMoment: Codable, Identifiable {
    let id = UUID()
    let timestamp: Double
    let description: String
    let context: String
    
    enum CodingKeys: String, CodingKey {
        case timestamp
        case description
        case context
    }
}

// MARK: - Analysis Mode Failure

struct AnalysisSafetyOmission: Codable, Identifiable {
    let mode: String
    let startTimestamp: Double
    let endTimestamp: Double
    let segmentCount: Int
    let provider: String
    let refusalCategory: String?
    let refusalExplanation: String?
    let recovery: String

    var id: String {
        "\(mode)-\(startTimestamp)-\(endTimestamp)-\(recovery)"
    }

    enum CodingKeys: String, CodingKey {
        case mode
        case startTimestamp = "start_timestamp"
        case endTimestamp = "end_timestamp"
        case segmentCount = "segment_count"
        case provider
        case refusalCategory = "refusal_category"
        case refusalExplanation = "refusal_explanation"
        case recovery
    }
}

struct AnalysisModeFailure: Codable, Identifiable {
    let mode: String
    let category: String
    let message: String
    let retryable: Bool
    let refusalCategory: String?
    let refusalExplanation: String?

    var id: String { mode }
    var analysisMode: AnalysisMode? { AnalysisMode(rawValue: mode) }

    enum CodingKeys: String, CodingKey {
        case mode
        case category
        case message
        case retryable
        case refusalCategory = "refusal_category"
        case refusalExplanation = "refusal_explanation"
    }
}

// MARK: - Meeting Analysis Result

struct MeetingAnalysisResult: Codable {
    let meetingId: String?
    let analyzedAt: String
    let modelUsed: String
    let requestedModes: [String]?
    let modesAnalyzed: [String]
    let failedModes: [AnalysisModeFailure]?
    let safetyOmissions: [AnalysisSafetyOmission]?
    let customInstructions: String?

    // Mode-specific results
    let actionItems: [ActionItem]?
    let suggestedActions: [MeetingActionProposal]?
    let summary: String?
    let decisions: [Decision]?
    let questionsAnswers: [QuestionAnswer]?
    let sentimentAnalysis: SentimentAnalysis?
    let customAnalysis: String?
    
    // Metadata
    let transcriptDuration: Double
    let speakerCount: Int
    let processingTime: Double
    let meetingName: String?
    let meetingPurpose: String?
    let participants: [String]?

    enum CodingKeys: String, CodingKey {
        case meetingId = "meeting_id"
        case analyzedAt = "analyzed_at"
        case modelUsed = "model_used"
        case requestedModes = "requested_modes"
        case modesAnalyzed = "modes_analyzed"
        case failedModes = "failed_modes"
        case safetyOmissions = "safety_omissions"
        case customInstructions = "custom_instructions"
        case actionItems = "action_items"
        case suggestedActions = "suggested_actions"
        case summary
        case decisions
        case questionsAnswers = "questions_answers"
        case sentimentAnalysis = "sentiment_analysis"
        case customAnalysis = "custom_analysis"
        case transcriptDuration = "transcript_duration"
        case speakerCount = "speaker_count"
        case processingTime = "processing_time"
        case meetingName = "meeting_name"
        case meetingPurpose = "meeting_purpose"
        case participants
    }

    var analysisFailures: [AnalysisModeFailure] {
        failedModes ?? []
    }

    var completedModes: [AnalysisMode] {
        var modes: [AnalysisMode] = []
        if actionItems != nil { modes.append(.actionItems) }
        if suggestedActions != nil { modes.append(.suggestedActions) }
        if summary != nil { modes.append(.summary) }
        if decisions != nil { modes.append(.decisions) }
        if questionsAnswers != nil { modes.append(.questions) }
        if sentimentAnalysis != nil { modes.append(.sentiment) }
        if customAnalysis != nil { modes.append(.custom) }
        return modes
    }
    
    var formattedDuration: String {
        let mins = Int(transcriptDuration) / 60
        let secs = Int(transcriptDuration) % 60
        return "\(mins)m \(secs)s"
    }
    
    var formattedProcessingTime: String {
        if processingTime < 60 {
            return String(format: "%.1fs", processingTime)
        } else {
            let mins = Int(processingTime) / 60
            let secs = Int(processingTime) % 60
            return "\(mins)m \(secs)s"
        }
    }
}

// MARK: - Analysis Progress

struct AnalysisProgress: Codable {
    let stage: String
    let stageProgress: Double
    let overallProgress: Double
    let currentMode: String?
    let completedModes: [String]
    let totalModes: Int
    let message: String
    let etaSeconds: Double
    
    enum CodingKeys: String, CodingKey {
        case stage
        case stageProgress = "stage_progress"
        case overallProgress = "overall_progress"
        case currentMode = "current_mode"
        case completedModes = "completed_modes"
        case totalModes = "total_modes"
        case message
        case etaSeconds = "eta_seconds"
    }
    
    var currentModeDisplay: String? {
        guard let mode = currentMode else { return nil }
        return AnalysisMode(rawValue: mode)?.displayName
    }
    
    var progressDescription: String {
        let completed = completedModes.count
        if completed == 0 {
            return message
        } else if completed == totalModes {
            return "Analysis complete"
        } else {
            return "\(completed) of \(totalModes) completed"
        }
    }
}

// MARK: - Analysis Configuration

struct MeetingAnalysisConfig: Codable {
    let modelId: String?
    let analysisModes: [String]
    let customInstructions: String?
    
    enum CodingKeys: String, CodingKey {
        case modelId = "model_id"
        case analysisModes = "analysis_modes"
        case customInstructions = "custom_instructions"
    }
}

