import XCTest
@testable import BasilClient

final class MeetingDataModelsTests: XCTestCase {
    
    // MARK: - Meeting Tests
    
    func testMeetingEncoding() throws {
        // Arrange
        let startTime = Date()
        let endTime = startTime.addingTimeInterval(3600) // 1 hour meeting
        let meeting = Meeting(
            id: "meeting-123",
            name: "Weekly Standup",
            purpose: "Team progress update",
            startTime: startTime,
            endTime: endTime,
            participants: ["Alice", "Bob", "Charlie"],
            isActive: false,
            meetingNotes: "Discussed project milestones"
        )
        
        // Act
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let data = try encoder.encode(meeting)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decodedMeeting = try decoder.decode(Meeting.self, from: data)
        
        // Assert
        XCTAssertEqual(decodedMeeting.id, meeting.id)
        XCTAssertEqual(decodedMeeting.name, meeting.name)
        XCTAssertEqual(decodedMeeting.purpose, meeting.purpose)
        XCTAssertEqual(decodedMeeting.participants, meeting.participants)
        XCTAssertEqual(decodedMeeting.isActive, meeting.isActive)
        XCTAssertEqual(decodedMeeting.meetingNotes, meeting.meetingNotes)
        
        // Testing timeIntervalSince with a more relaxed accuracy value for ISO8601 date encoding/decoding
        XCTAssertEqual(
            decodedMeeting.startTime.timeIntervalSince1970,
            meeting.startTime.timeIntervalSince1970,
            accuracy: 1.0 // Allow up to 1 second difference due to precision loss in ISO8601
        )
        
        // Handle optional endTime separately
        XCTAssertNotNil(decodedMeeting.endTime)
        XCTAssertNotNil(meeting.endTime)
        
        if let decodedEndTime = decodedMeeting.endTime, let originalEndTime = meeting.endTime {
            XCTAssertEqual(
                decodedEndTime.timeIntervalSince1970,
                originalEndTime.timeIntervalSince1970,
                accuracy: 1.0 // Allow up to 1 second difference due to precision loss in ISO8601
            )
        }
    }
    
    func testMeetingComputedProperties() {
        // Arrange
        let startTime = Date()
        let endTime = startTime.addingTimeInterval(5400) // 1 hour 30 minutes
        let meeting = Meeting(
            id: "meeting-123",
            name: "Weekly Standup",
            purpose: "Team progress update",
            startTime: startTime,
            endTime: endTime,
            participants: ["Alice", "Bob", "Charlie"],
            isActive: false,
            meetingNotes: "Discussed project milestones"
        )
        
        // Assert
        XCTAssertEqual(meeting.duration, 5400)
        XCTAssertEqual(meeting.formattedDuration, "1:30:00")
        XCTAssertTrue(meeting.isCompleted)
        
        // Test in-progress meeting
        let activeMeeting = Meeting(
            id: "meeting-123",
            name: "Weekly Standup",
            purpose: "Team progress update",
            startTime: startTime,
            endTime: nil,
            participants: ["Alice", "Bob", "Charlie"],
            isActive: true,
            meetingNotes: nil
        )
        
        XCTAssertNil(activeMeeting.duration)
        XCTAssertEqual(activeMeeting.formattedDuration, "In progress")
        XCTAssertFalse(activeMeeting.isCompleted)
    }
    
    func testMeetingAnalysisResultDecodesSuggestedActionsPayload() throws {
        let json = """
        {
          "meeting_id": "meeting-123",
          "analyzed_at": "2026-06-09T16:27:45.607843",
          "model_used": "claude-sonnet-4-5-20250929",
          "modes_analyzed": ["suggested_actions"],
          "custom_instructions": null,
          "action_items": null,
          "suggested_actions": [
            {
              "id": "proposal-123",
              "source_action_item_index": null,
              "source_task": "Follow up with engineering about Cursor features",
              "source_context": "Meeting discussed Cursor CLI, agents, automations, and cloud agents.",
              "source_timestamp": 20.0,
              "source_speaker": "Speaker 1",
              "suggested_agent_task": "Create a summary note of the Cursor features discussed.",
              "capability_type": "note",
              "confidence": 0.95,
              "why_basil_can_help": "Basil can create a structured reference document.",
              "missing_information": [],
              "requires_user_confirmation": true,
              "workspace_source": "meeting_analysis",
              "execution_status": "proposed",
              "submitted_agent_task_id": null
            }
          ],
          "summary": null,
          "decisions": null,
          "questions_answers": null,
          "sentiment_analysis": null,
          "custom_analysis": null,
          "transcript_duration": 1333.3,
          "speaker_count": 0,
          "processing_time": 24.1,
          "meeting_name": "Meeting 2026-06-02",
          "meeting_purpose": null,
          "participants": []
        }
        """
        
        let data = try XCTUnwrap(json.data(using: .utf8))
        let result = try JSONDecoder().decode(MeetingAnalysisResult.self, from: data)
        
        XCTAssertEqual(result.meetingId, "meeting-123")
        XCTAssertEqual(result.completedModes, [.suggestedActions])
        XCTAssertEqual(result.suggestedActions?.count, 1)
        
        let proposal = try XCTUnwrap(result.suggestedActions?.first)
        XCTAssertEqual(proposal.sourceTask, "Follow up with engineering about Cursor features")
        XCTAssertEqual(proposal.suggestedAgentTask, "Create a summary note of the Cursor features discussed.")
        XCTAssertEqual(proposal.whyBasilCanHelp, "Basil can create a structured reference document.")
        XCTAssertEqual(proposal.workspaceSource, "meeting_analysis")
    }

    func testMeetingAnalysisResultDecodesPartialFailurePayload() throws {
        let json = """
        {
          "meeting_id": "meeting-456",
          "analyzed_at": "2026-06-09T16:27:45.607843",
          "model_used": "claude-sonnet-4-5-20250929",
          "requested_modes": ["summary", "suggested_actions"],
          "modes_analyzed": ["summary"],
          "failed_modes": [
            {
              "mode": "suggested_actions",
              "category": "output_limit",
              "message": "anthropic_output_format ended incompletely: finish_reason=max_tokens",
              "retryable": false,
              "refusal_category": "general_harms",
              "refusal_explanation": "Provider detail"
            }
          ],
          "safety_omissions": [
            {
              "mode": "suggested_actions",
              "start_timestamp": 120.0,
              "end_timestamp": 120.0,
              "segment_count": 1,
              "provider": "anthropic",
              "refusal_category": "general_harms",
              "refusal_explanation": "Provider detail",
              "recovery": "omitted_refused_line"
            }
          ],
          "summary": "Completed summary",
          "transcript_duration": 600.0,
          "speaker_count": 2,
          "processing_time": 12.0
        }
        """

        let data = try XCTUnwrap(json.data(using: .utf8))
        let result = try JSONDecoder().decode(MeetingAnalysisResult.self, from: data)

        XCTAssertEqual(result.requestedModes, ["summary", "suggested_actions"])
        XCTAssertEqual(result.modesAnalyzed, ["summary"])
        XCTAssertEqual(result.analysisFailures.count, 1)
        XCTAssertEqual(result.analysisFailures.first?.mode, "suggested_actions")
        XCTAssertEqual(result.analysisFailures.first?.category, "output_limit")
        XCTAssertFalse(result.analysisFailures.first?.retryable ?? true)
        XCTAssertEqual(result.analysisFailures.first?.refusalCategory, "general_harms")
        XCTAssertEqual(result.safetyOmissions?.first?.startTimestamp, 120.0)
    }

    func testMeetingAnalysisResultLegacyPayloadDefaultsFailureListsToEmpty() throws {
        let json = """
        {
          "meeting_id": "meeting-123",
          "analyzed_at": "2026-06-09T16:27:45.607843",
          "model_used": "claude-sonnet-4-5-20250929",
          "modes_analyzed": ["summary"],
          "summary": "Legacy summary",
          "transcript_duration": 600.0,
          "speaker_count": 2,
          "processing_time": 12.0
        }
        """

        let data = try XCTUnwrap(json.data(using: .utf8))
        let result = try JSONDecoder().decode(MeetingAnalysisResult.self, from: data)

        XCTAssertNil(result.requestedModes)
        XCTAssertNil(result.failedModes)
        XCTAssertNil(result.safetyOmissions)
        XCTAssertTrue(result.analysisFailures.isEmpty)
    }

    func testMeetingAnalysisResultDecodesScheduledAgentTaskCapability() throws {
        // The analyzer can now emit a new capability_type, "scheduled_agent_task",
        // when a future-dated follow-up maps to a connected integration. The
        // client stores capability_type as a free String, so it must decode
        // without a whitelist change.
        let json = """
        {
          "meeting_id": "meeting-789",
          "analyzed_at": "2026-06-09T16:27:45.607843",
          "model_used": "claude-sonnet-4-5-20250929",
          "modes_analyzed": ["suggested_actions"],
          "suggested_actions": [
            {
              "id": "proposal-789",
              "source_task": "Export the Salesforce pipeline data on Wednesday.",
              "suggested_agent_task": "Schedule a task for Wednesday 5:00pm ET that asks Speakeasy to initiate the Salesforce export and monitors it.",
              "capability_type": "scheduled_agent_task",
              "confidence": 0.9,
              "why_basil_can_help": "Basil can schedule and run this via the connected Speakeasy integration.",
              "missing_information": [],
              "requires_user_confirmation": true,
              "workspace_source": "meeting_analysis",
              "execution_status": "proposed"
            }
          ],
          "transcript_duration": 600.0,
          "speaker_count": 2,
          "processing_time": 12.0
        }
        """

        let data = try XCTUnwrap(json.data(using: .utf8))
        let result = try JSONDecoder().decode(MeetingAnalysisResult.self, from: data)

        let proposal = try XCTUnwrap(result.suggestedActions?.first)
        XCTAssertEqual(proposal.capabilityType, "scheduled_agent_task")
        XCTAssertTrue(proposal.suggestedAgentTask.contains("Speakeasy"))
    }

    func testMeetingListItemAnalysisSummaryDecodesPresent() throws {
        let json = """
        {
          "id": "meeting-123",
          "name": "Weekly Standup",
          "purpose": null,
          "participants": [],
          "start_time": "2026-01-01T10:00:00Z",
          "end_time": null,
          "duration_seconds": 1200.0,
          "audio_path": null,
          "transcript_path": null,
          "is_post_processed": true,
          "analysis_summary": {
            "count": 2,
            "latest_filename": "analysis_20240101_000000.json",
            "latest_timestamp": "2026-01-01T11:00:00Z",
            "pending_action_count": 3
          }
        }
        """

        let data = try XCTUnwrap(json.data(using: .utf8))
        let item = try JSONDecoder().decode(MeetingListItem.self, from: data)

        let summary = try XCTUnwrap(item.analysisSummary)
        XCTAssertEqual(summary.count, 2)
        XCTAssertEqual(summary.latestFilename, "analysis_20240101_000000.json")
        XCTAssertEqual(summary.latestTimestamp, "2026-01-01T11:00:00Z")
        XCTAssertEqual(summary.pendingActionCount, 3)
    }

    func testMeetingListItemAnalysisSummaryDecodesAbsent() throws {
        let json = """
        {
          "id": "meeting-456",
          "name": "No Analysis Yet",
          "purpose": null,
          "participants": [],
          "start_time": "2026-01-02T10:00:00Z",
          "end_time": null,
          "duration_seconds": 600.0,
          "audio_path": null,
          "transcript_path": null,
          "is_post_processed": false
        }
        """

        let data = try XCTUnwrap(json.data(using: .utf8))
        let item = try JSONDecoder().decode(MeetingListItem.self, from: data)

        XCTAssertNil(item.analysisSummary)
    }

    func testMeetingListItemAnalysisSummaryDecodesNullPendingCount() throws {
        let json = """
        {
          "id": "meeting-789",
          "name": "Unknown Pending",
          "purpose": null,
          "participants": [],
          "start_time": "2026-01-03T10:00:00Z",
          "end_time": null,
          "duration_seconds": 900.0,
          "audio_path": null,
          "transcript_path": null,
          "is_post_processed": true,
          "analysis_summary": {
            "count": 1,
            "latest_filename": "analysis_20240101_000000.json",
            "latest_timestamp": "2026-01-03T11:00:00Z",
            "pending_action_count": null
          }
        }
        """

        let data = try XCTUnwrap(json.data(using: .utf8))
        let item = try JSONDecoder().decode(MeetingListItem.self, from: data)

        let summary = try XCTUnwrap(item.analysisSummary)
        XCTAssertEqual(summary.count, 1)
        XCTAssertNil(summary.pendingActionCount)
    }

    func testAnalysisMetadataLegacyUTCTimestampMatchesExplicitUTCFormatting() {
        let originalStyle = DateDisplayPreferenceStore.shared.style
        defer { DateDisplayPreferenceStore.shared.update(originalStyle) }
        DateDisplayPreferenceStore.shared.update(.absolute)

        let legacyTimestamp = AnalysisMetadataEntry(
            timestamp: "2026-07-15T18:30:00.000000",
            filename: "analysis_20260715_183000.json",
            modes: ["summary"],
            modelUsed: "test-model"
        )
        let explicitUTCTimestamp = AnalysisMetadataEntry(
            timestamp: "2026-07-15T18:30:00.000000Z",
            filename: "analysis_20260715_183001.json",
            modes: ["summary"],
            modelUsed: "test-model"
        )

        XCTAssertEqual(legacyTimestamp.formattedDate, explicitUTCTimestamp.formattedDate)
    }
    
    // MARK: - Transcript Segment Tests
    
    func testTranscriptSegmentEncoding() throws {
        // Arrange
        let segment = TranscriptSegment(
            id: "segment-123",
            speakerId: "speaker-456",
            speakerName: "Alice",
            text: "Let's discuss the new feature.",
            confidence: 0.92,
            startTime: 15.5,
            endTime: 19.2,
            audioSource: .localMicrophone,
            applicationName: "TestApp"
        )
        
        // Act
        let encoder = JSONEncoder()
        let data = try encoder.encode(segment)
        let decodedSegment = try JSONDecoder().decode(TranscriptSegment.self, from: data)
        
        // Assert
        XCTAssertEqual(decodedSegment.id, segment.id)
        XCTAssertEqual(decodedSegment.speakerId, segment.speakerId)
        XCTAssertEqual(decodedSegment.speakerName, segment.speakerName)
        XCTAssertEqual(decodedSegment.text, segment.text)
        XCTAssertEqual(decodedSegment.confidence, segment.confidence)
        XCTAssertEqual(decodedSegment.startTime, segment.startTime)
        XCTAssertEqual(decodedSegment.endTime, segment.endTime)
        XCTAssertEqual(decodedSegment.audioSource, segment.audioSource)
        
        // Computed properties
        XCTAssertEqual(segment.duration, 3.7, accuracy: 0.001)
        XCTAssertEqual(segment.formattedTimestamp, "00:15")
    }
    
    // MARK: - WebSocket Message Tests
    
    func testMeetingWebSocketMessage() throws {
        // Arrange
        let messageData: [String: Any] = [
            "meetingId": "meeting-123",
            "success": true,
            "timestamp": 1234567890.0
        ]
        
        let message = MeetingWebSocketMessage(type: .startMeeting, data: messageData)
        
        // Act
        let encoder = JSONEncoder()
        let data = try encoder.encode(message)
        let decodedMessage = try JSONDecoder().decode(MeetingWebSocketMessage.self, from: data)
        
        // Assert
        XCTAssertEqual(decodedMessage.type, .startMeeting)
        XCTAssertNotNil(decodedMessage.data)
        
        // Access data values with type casting
        if let successVal = decodedMessage.data?["success"]?.value as? Bool {
            XCTAssertTrue(successVal)
        } else {
            XCTFail("Could not retrieve success value")
        }
        
        if let meetingId = decodedMessage.data?["meetingId"]?.value as? String {
            XCTAssertEqual(meetingId, "meeting-123")
        } else {
            XCTFail("Could not retrieve meetingId value")
        }
        
        // Handle timestamp which could be decoded as either Double or Int
        if let timestamp = decodedMessage.data?["timestamp"]?.value as? Double {
            XCTAssertEqual(timestamp, 1234567890.0, accuracy: 0.1)
        } else if let timestamp = decodedMessage.data?["timestamp"]?.value as? Int {
            XCTAssertEqual(Double(timestamp), 1234567890.0, accuracy: 0.1)
        } else {
            XCTFail("Could not retrieve timestamp value")
        }
    }
    
    // MARK: - AnyCodable Tests
    
    func testAnyCodableEncoding() throws {
        // Arrange
        let testData: [String: Any] = [
            "stringValue": "Hello",
            "intValue": 42,
            "doubleValue": 3.14,
            "boolValue": true,
            "nullValue": NSNull(),
            "arrayValue": ["a", "b", "c"],
            "nestedDict": ["key": "value"]
        ]
        
        let codableDict = testData.mapValues { AnyCodable($0) }
        
        // Act
        let encoder = JSONEncoder()
        let data = try encoder.encode(codableDict)
        let decodedDict = try JSONDecoder().decode([String: AnyCodable].self, from: data)
        
        // Assert - Check each type
        XCTAssertEqual(decodedDict["stringValue"]?.value as? String, "Hello")
        XCTAssertEqual(decodedDict["intValue"]?.value as? Int, 42)
        XCTAssertEqual(decodedDict["doubleValue"]?.value as? Double, 3.14)
        XCTAssertEqual(decodedDict["boolValue"]?.value as? Bool, true)
        XCTAssertTrue(decodedDict["nullValue"]?.value is NSNull)
        
        // Test array value
        if let array = decodedDict["arrayValue"]?.value as? [Any] {
            XCTAssertEqual(array.count, 3)
            XCTAssertEqual(array[0] as? String, "a")
            XCTAssertEqual(array[1] as? String, "b")
            XCTAssertEqual(array[2] as? String, "c")
        } else {
            XCTFail("Array value not decoded correctly")
        }
        
        // Test nested dictionary
        if let nested = decodedDict["nestedDict"]?.value as? [String: Any],
           let nestedValue = nested["key"] as? String {
            XCTAssertEqual(nestedValue, "value")
        } else {
            XCTFail("Nested dictionary not decoded correctly")
        }
    }
    
    // MARK: - Response Structure Tests
    
    func testMeetingProcessingResultEncoding() throws {
        // Arrange
        let processingResult = MeetingProcessingResult(
            id: "result-123",
            meetingId: "meeting-456",
            resultType: .actionItems,
            content: "1. Complete project proposal\n2. Schedule follow-up meeting",
            createdAt: Date()
        )
        
        // Act
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let data = try encoder.encode(processingResult)
        
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decodedResult = try decoder.decode(MeetingProcessingResult.self, from: data)
        
        // Assert
        XCTAssertEqual(decodedResult.id, processingResult.id)
        XCTAssertEqual(decodedResult.meetingId, processingResult.meetingId)
        XCTAssertEqual(decodedResult.resultType, processingResult.resultType)
        XCTAssertEqual(decodedResult.content, processingResult.content)
    }
    
    func testSpeakerDiarizationResponseEncoding() throws {
        // Arrange
        let response = SpeakerDiarizationResponse(
            success: true,
            speakerId: "speaker-123",
            speakerName: "John Doe",
            confidence: 0.85,
            error: nil,
            isNewSpeaker: false
        )
        
        // Act
        let encoder = JSONEncoder()
        let data = try encoder.encode(response)
        let decodedResponse = try JSONDecoder().decode(SpeakerDiarizationResponse.self, from: data)
        
        // Assert
        XCTAssertEqual(decodedResponse.success, response.success)
        XCTAssertEqual(decodedResponse.speakerId, response.speakerId)
        XCTAssertEqual(decodedResponse.speakerName, response.speakerName)
        XCTAssertEqual(decodedResponse.confidence, response.confidence)
        XCTAssertNil(decodedResponse.error)
        XCTAssertEqual(decodedResponse.isNewSpeaker, response.isNewSpeaker)
    }
    
    // MARK: - MeetingAudioData Tests
    
    func testMeetingAudioDataEncoding() throws {
        // Arrange
        let metadata = MeetingAudioData.MeetingMetadata(
            meetingName: "Product Review",
            purpose: "Review Q2 roadmap",
            participants: ["Alice", "Bob"],
            currentSpeaker: "Alice"
        )
        
        let audioData = MeetingAudioData(
            meetingId: "meeting-123",
            audioSource: .localMicrophone,
            timestamp: 1234567890.0,
            metadata: metadata
        )
        
        // Act
        let encoder = JSONEncoder()
        let data = try encoder.encode(audioData)
        let decodedAudioData = try JSONDecoder().decode(MeetingAudioData.self, from: data)
        
        // Assert
        XCTAssertEqual(decodedAudioData.meetingId, audioData.meetingId)
        XCTAssertEqual(decodedAudioData.audioSource, audioData.audioSource)
        XCTAssertEqual(decodedAudioData.timestamp, audioData.timestamp)
        XCTAssertEqual(decodedAudioData.metadata?.meetingName, metadata.meetingName)
        XCTAssertEqual(decodedAudioData.metadata?.purpose, metadata.purpose)
        XCTAssertEqual(decodedAudioData.metadata?.participants, metadata.participants)
        XCTAssertEqual(decodedAudioData.metadata?.currentSpeaker, metadata.currentSpeaker)
    }
    
    // MARK: - Settings Tests
    
    func testMeetingSettingsEncoding() throws {
        // Arrange
        var settings = MeetingSettings()
        settings.autoStartTranscription = true
        settings.enableSpeakerIdentification = false
        settings.saveAudio = true
        settings.postMeetingProcessingEnabled = true
        settings.defaultProcessingTypes = [.actionItems, .summary]
        settings.widgetSize = [400, 600]
        settings.widgetPosition = [100, 200, 1]
        
        // Act
        let encoder = JSONEncoder()
        let data = try encoder.encode(settings)
        let decodedSettings = try JSONDecoder().decode(MeetingSettings.self, from: data)
        
        // Assert
        XCTAssertEqual(decodedSettings.autoStartTranscription, settings.autoStartTranscription)
        XCTAssertEqual(decodedSettings.enableSpeakerIdentification, settings.enableSpeakerIdentification)
        XCTAssertEqual(decodedSettings.saveAudio, settings.saveAudio)
        XCTAssertEqual(decodedSettings.postMeetingProcessingEnabled, settings.postMeetingProcessingEnabled)
        XCTAssertEqual(decodedSettings.defaultProcessingTypes, settings.defaultProcessingTypes)
        XCTAssertEqual(decodedSettings.widgetSize, settings.widgetSize)
        XCTAssertEqual(decodedSettings.widgetPosition, settings.widgetPosition)
    }
} 