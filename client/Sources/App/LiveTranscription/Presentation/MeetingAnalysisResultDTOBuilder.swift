import Foundation

/// Pure mapping from the backend-decoded `MeetingAnalysisResult` (and its
/// nested action/decision/QA/sentiment/proposal models) to the version-1
/// bridge DTOs. Contains no backend calls, no persistence, and no proposal
/// outcome logic -- `MeetingActionProposalStore` (bound by
/// `MeetingBridgePublisher.publishAnalysisResult`) remains the sole owner of
/// proposal outcome state.
enum MeetingAnalysisResultDTOBuilder {
    static func build(
        _ result: MeetingAnalysisResult,
        filename: String?,
        transcript: [TranscriptLineDTO] = []
    ) -> MeetingAnalysisResultDTO {
        MeetingAnalysisResultDTO(
            meetingId: result.meetingId,
            filename: filename,
            analyzedAt: result.analyzedAt,
            modelUsed: result.modelUsed,
            requestedModes: result.requestedModes,
            modesAnalyzed: result.modesAnalyzed,
            failedModes: result.failedModes?.map {
                AnalysisModeFailureDTO(
                    mode: $0.mode,
                    category: $0.category,
                    message: $0.message,
                    retryable: $0.retryable,
                    refusalCategory: $0.refusalCategory,
                    refusalExplanation: $0.refusalExplanation
                )
            },
            safetyOmissions: result.safetyOmissions?.map {
                AnalysisSafetyOmissionDTO(
                    mode: $0.mode,
                    startTimestamp: $0.startTimestamp,
                    endTimestamp: $0.endTimestamp,
                    segmentCount: $0.segmentCount,
                    provider: $0.provider,
                    refusalCategory: $0.refusalCategory,
                    refusalExplanation: $0.refusalExplanation,
                    recovery: $0.recovery
                )
            },
            customInstructions: result.customInstructions,
            actionItems: result.actionItems?.map {
                ActionItemDTO(
                    id: $0.id.uuidString,
                    task: $0.task,
                    assignedTo: $0.assignedTo,
                    deadline: $0.deadline,
                    priority: $0.priority,
                    context: $0.context,
                    timestamp: $0.timestamp,
                    speaker: $0.speaker
                )
            },
            suggestedActions: result.suggestedActions?.map(proposalDTO),
            summary: result.summary,
            decisions: result.decisions?.map {
                DecisionDTO(
                    id: $0.id.uuidString,
                    decision: $0.decision,
                    rationale: $0.rationale,
                    decidedBy: $0.decidedBy,
                    timestamp: $0.timestamp,
                    context: $0.context,
                    impact: $0.impact
                )
            },
            questionsAnswers: result.questionsAnswers?.map {
                QuestionAnswerDTO(
                    id: $0.id.uuidString,
                    question: $0.question,
                    answer: $0.answer,
                    asker: $0.asker,
                    responder: $0.responder,
                    timestamp: $0.timestamp,
                    context: $0.context,
                    resolved: $0.resolved
                )
            },
            sentimentAnalysis: result.sentimentAnalysis.map(sentimentDTO),
            customAnalysis: result.customAnalysis,
            transcriptDuration: result.transcriptDuration,
            speakerCount: result.speakerCount,
            processingTime: result.processingTime,
            meetingName: result.meetingName,
            meetingPurpose: result.meetingPurpose,
            participants: result.participants,
            formattedDuration: result.formattedDuration,
            formattedProcessingTime: result.formattedProcessingTime,
            transcript: transcript.isEmpty ? nil : transcript
        )
    }

    /// Proposal DTOs built here carry only the persisted/decoded fields
    /// (`executionStatus`, no live/draft/editing state yet); as soon as
    /// `MeetingBridgePublisher.publishAnalysisResult` binds the
    /// `MeetingActionProposalStore`, its own `buildProposals()` supersedes
    /// this initial array on the very next `proposalsDelta`.
    private static func proposalDTO(_ proposal: MeetingActionProposal) -> MeetingActionProposalDTO {
        MeetingActionProposalDTO(
            id: proposal.id,
            sourceActionItemIndex: proposal.sourceActionItemIndex,
            sourceActionItemIndexes: proposal.sourceActionItemIndexes,
            sourceTask: proposal.sourceTask,
            sourceContext: proposal.sourceContext,
            sourceTimestamp: proposal.sourceTimestamp,
            sourceSpeaker: proposal.sourceSpeaker,
            suggestedAgentTask: proposal.suggestedAgentTask,
            capabilityType: proposal.capabilityType,
            confidence: proposal.confidence,
            whyBasilCanHelp: proposal.whyBasilCanHelp,
            missingInformation: proposal.missingInformation,
            requiresUserConfirmation: proposal.requiresUserConfirmation,
            executionMode: proposal.executionMode,
            workspaceSource: proposal.workspaceSource,
            executionStatus: proposal.executionStatus,
            submittedAgentTaskId: proposal.submittedAgentTaskId,
            todoId: proposal.todoId,
            todoStatus: nil,
            lastError: nil,
            isEditingDraft: false,
            draftPrompt: proposal.suggestedAgentTask,
            liveAgentStatus: nil
        )
    }

    private static func sentimentDTO(_ sentiment: SentimentAnalysis) -> SentimentAnalysisDTO {
        SentimentAnalysisDTO(
            overallSentiment: sentiment.overallSentiment,
            sentimentScore: sentiment.sentimentScore,
            engagementLevel: sentiment.engagementLevel,
            speakerSentiments: sentiment.speakerSentiments?.mapValues {
                SpeakerSentimentDTO(sentiment: $0.sentiment, engagement: $0.engagement, keyContributions: $0.keyContributions)
            },
            positiveMoments: sentiment.positiveMoments?.map {
                SentimentMomentDTO(id: $0.id.uuidString, timestamp: $0.timestamp, description: $0.description, context: $0.context)
            },
            negativeMoments: sentiment.negativeMoments?.map {
                SentimentMomentDTO(id: $0.id.uuidString, timestamp: $0.timestamp, description: $0.description, context: $0.context)
            },
            toneIndicators: sentiment.toneIndicators
        )
    }
}
