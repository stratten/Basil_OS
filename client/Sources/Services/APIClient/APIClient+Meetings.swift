import Foundation

// MARK: - Meeting History Methods for APIClient
extension APIClient {
    
    // MARK: - List Meetings
    
    /// Fetch a list of meetings ordered by most recent
    /// - Parameters:
    ///   - limit: Maximum number of meetings to return (default: 50)
    ///   - offset: Pagination offset (default: 0)
    /// - Returns: Array of MeetingListItem
    func listMeetings(limit: Int = 50, offset: Int = 0) async throws -> [MeetingListItem] {
        #if DEBUG
        DevLogger.shared.info("📋 Fetching meeting list (limit: \(limit), offset: \(offset))", context: "APIClient")
        #endif
        
        let data = try await get("/meetings?limit=\(limit)&offset=\(offset)")
        let decoder = JSONDecoder()
        
        do {
            let meetings = try decoder.decode([MeetingListItem].self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Fetched \(meetings.count) meetings", context: "APIClient")
            #endif
            return meetings
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode meetings: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    // MARK: - Search Meetings

    /// Full-text search meetings by transcript/metadata content. Results are the
    /// same session-grouped representatives as `listMeetings`.
    /// - Parameters:
    ///   - query: Search text (percent-encoded for the query string).
    ///   - limit: Maximum number of meetings to return (default: 50).
    ///   - offset: Pagination offset (default: 0).
    /// - Returns: Array of MeetingListItem
    func searchMeetings(
        query: String,
        filters: MeetingHistorySearchFilters,
        limit: Int = 50,
        offset: Int = 0
    ) async throws -> [MeetingListItem] {
        var components = URLComponents()
        components.path = "/meetings/search"
        var queryItems = [
            URLQueryItem(name: "limit", value: String(limit)),
            URLQueryItem(name: "offset", value: String(offset)),
        ]
        if !query.isEmpty {
            queryItems.append(URLQueryItem(name: "query", value: query))
            queryItems.append(URLQueryItem(name: "query_mode", value: filters.queryMode.rawValue))
        }
        let textFilters = [
            ("name", filters.name, filters.nameMode),
            ("purpose", filters.purpose, filters.purposeMode),
            ("participants", filters.participants, filters.participantsMode),
            ("transcript", filters.transcript, filters.transcriptMode),
            ("source", filters.source, filters.sourceMode),
        ]
        for (name, value, mode) in textFilters where !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            queryItems.append(URLQueryItem(name: name, value: value))
            queryItems.append(URLQueryItem(name: "\(name)_mode", value: mode.rawValue))
        }
        if let startDate = filters.startDate {
            queryItems.append(URLQueryItem(name: "start_date", value: startDate))
        }
        if let endDate = filters.endDate {
            queryItems.append(URLQueryItem(name: "end_date", value: endDate))
        }
        if filters.processing != .any {
            queryItems.append(URLQueryItem(name: "processing", value: filters.processing.rawValue))
        }
        if filters.analysis != .any {
            queryItems.append(URLQueryItem(name: "analysis", value: filters.analysis.rawValue))
        }
        components.queryItems = queryItems
        guard let path = components.string else {
            throw URLError(.badURL)
        }

        #if DEBUG
        DevLogger.shared.info("🔎 Searching meetings (query: \(query), filters: \(filters), limit: \(limit), offset: \(offset))", context: "APIClient")
        #endif

        let data = try await get(path)
        let decoder = JSONDecoder()

        do {
            let meetings = try decoder.decode([MeetingListItem].self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Search returned \(meetings.count) meetings", context: "APIClient")
            #endif
            return meetings
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode meeting search results: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }

    // MARK: - Get Meeting
    
    /// Get a meeting by ID with its metadata and transcript
    /// - Parameter meetingId: ID of the meeting to fetch
    /// - Returns: Tuple containing meeting metadata and transcript
    func getMeeting(id meetingId: String) async throws -> (metadata: MeetingListItem, transcript: BackendMeetingTranscript?) {
        #if DEBUG
        DevLogger.shared.info("📖 Fetching meeting: \(meetingId)", context: "APIClient")
        #endif
        
        let data = try await get("/meetings/\(meetingId)")
        let decoder = JSONDecoder()
        
        do {
            // Backend returns: { "metadata": {...}, "transcript": {...} }
            #if DEBUG
            if let jsonString = String(data: data, encoding: .utf8) {
                DevLogger.shared.info("📥 Raw response: \(jsonString.prefix(500))...", context: "APIClient")
            }
            #endif
            
            let response = try decoder.decode(MeetingResponse.self, from: data)
            
            #if DEBUG
            DevLogger.shared.info("✅ Fetched meeting: \(response.metadata.name), transcript: \(response.transcript != nil ? "present (\(response.transcript!.segments.count) segments)" : "nil")", context: "APIClient")
            #endif
            
            return (metadata: response.metadata, transcript: response.transcript)
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode meeting: \(error)", context: "APIClient")
            if let jsonString = String(data: data, encoding: .utf8) {
                DevLogger.shared.error("Raw data was: \(jsonString.prefix(500))", context: "APIClient")
            }
            #endif
            throw error
        }
    }
    
    // MARK: - Delete Meeting
    
    /// Delete a meeting and all its associated data (audio, transcript, metadata)
    /// - Parameter meetingId: ID of the meeting to delete
    func deleteMeeting(id meetingId: String) async throws {
        #if DEBUG
        DevLogger.shared.info("🗑️ Deleting meeting: \(meetingId)", context: "APIClient")
        #endif
        
        _ = try await delete("/meetings/\(meetingId)")
        
        #if DEBUG
        DevLogger.shared.info("✅ Successfully deleted meeting", context: "APIClient")
        #endif
    }
    
    /// Update editable metadata for a saved meeting.
    func updateMeetingMetadata(
        meetingId: String,
        name: String,
        purpose: String?,
        participants: [String]
    ) async throws {
        struct MeetingMetadataUpdateRequest: Codable {
            let name: String
            let purpose: String?
            let participants: [String]
        }
        
        #if DEBUG
        DevLogger.shared.info("✏️ Updating meeting metadata for \(meetingId): \(name)", context: "APIClient")
        #endif
        
        let request = MeetingMetadataUpdateRequest(
            name: name,
            purpose: purpose,
            participants: participants
        )
        let requestData = try JSONEncoder().encode(request)
        _ = try await put("/meetings/\(meetingId)", data: requestData)
        
        #if DEBUG
        DevLogger.shared.info("✅ Updated meeting metadata", context: "APIClient")
        #endif
    }
    
    // MARK: - Analysis Methods
    
    /// List all analyses for a meeting
    /// - Parameter meetingId: ID of the meeting
    /// - Returns: Array of analysis metadata entries
    func listMeetingAnalyses(meetingId: String) async throws -> [AnalysisMetadataEntry] {
        #if DEBUG
        DevLogger.shared.info("📊 Fetching analyses for meeting: \(meetingId)", context: "APIClient")
        #endif
        
        let data = try await get("/meetings/\(meetingId)/analyses")
        let decoder = JSONDecoder()
        
        do {
            let analyses = try decoder.decode([AnalysisMetadataEntry].self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Fetched \(analyses.count) analyses", context: "APIClient")
            #endif
            return analyses
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode analyses: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    /// Get a specific analysis by filename
    /// - Parameters:
    ///   - meetingId: ID of the meeting
    ///   - filename: Analysis filename (e.g., analysis_20241226_123045.json)
    /// - Returns: Meeting analysis result
    func getMeetingAnalysis(meetingId: String, filename: String) async throws -> MeetingAnalysisResult {
        #if DEBUG
        DevLogger.shared.info("📊 Fetching analysis \(filename) for meeting: \(meetingId)", context: "APIClient")
        #endif
        
        let data = try await get("/meetings/\(meetingId)/analyses/\(filename)")
        let decoder = JSONDecoder()
        
        do {
            let analysis = try decoder.decode(MeetingAnalysisResult.self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Fetched analysis with \(analysis.completedModes.count) modes", context: "APIClient")
            #endif
            return analysis
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode analysis: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    /// Delete a specific analysis
    /// - Parameters:
    ///   - meetingId: ID of the meeting
    ///   - filename: Analysis filename to delete
    func deleteMeetingAnalysis(meetingId: String, filename: String) async throws {
        #if DEBUG
        DevLogger.shared.info("🗑️ Deleting analysis \(filename) for meeting: \(meetingId)", context: "APIClient")
        #endif
        
        _ = try await delete("/meetings/\(meetingId)/analyses/\(filename)")
        
        #if DEBUG
        DevLogger.shared.info("✅ Successfully deleted analysis", context: "APIClient")
        #endif
    }
    
    /// Persist a single suggested-action proposal's outcome to its analysis file.
    /// - Parameters:
    ///   - meetingId: ID of the meeting
    ///   - filename: Analysis filename (e.g., analysis_20241226_123045.json)
    ///   - proposalId: Stable backend id of the proposal
    ///   - executionStatus: New execution status (e.g. "submitted", "dismissed", "proposed")
    ///   - submittedAgentTaskId: Delegated agent task id, or nil to clear it
    ///
    /// A `nil` `submittedAgentTaskId` is encoded as an explicit JSON `null` (via
    /// `JSONSerialization` + `NSNull`) because `JSONEncoder` would otherwise omit
    /// the key entirely, leaving a stale id on the server during dismiss/restore.
    func updateMeetingAnalysisProposal(
        meetingId: String,
        filename: String,
        proposalId: String,
        executionStatus: String,
        submittedAgentTaskId: String?,
        todoId: String? = nil
    ) async throws {
        #if DEBUG
        DevLogger.shared.info("💾 Updating proposal \(proposalId) -> \(executionStatus) (agentTask: \(submittedAgentTaskId ?? "nil"))", context: "APIClient")
        #endif
        
        let body: [String: Any] = [
            "execution_status": executionStatus,
            "submitted_agent_task_id": submittedAgentTaskId ?? NSNull(),
            "todo_id": todoId ?? NSNull()
        ]
        let requestData = try JSONSerialization.data(withJSONObject: body)
        _ = try await put("/meetings/\(meetingId)/analyses/\(filename)/proposals/\(proposalId)", data: requestData)
        
        #if DEBUG
        DevLogger.shared.info("✅ Persisted proposal outcome", context: "APIClient")
        #endif
    }
    
    // MARK: - Helper Types
    
    /// Response structure for getting a single meeting
    private struct MeetingResponse: Codable {
        let metadata: MeetingListItem
        let transcript: BackendMeetingTranscript?
    }
}

