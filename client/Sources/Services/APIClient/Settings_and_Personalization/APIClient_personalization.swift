import Foundation

extension APIClient {
    // MARK: - User Profile
    
    // Tolerant envelopes to match various response shapes if ever introduced
    private struct UserProfileEnvelope: Codable {
        let status: String?
        let profile: UserProfile?
        let data: UserProfile?
        let settings: UserProfile? // in case backend mirrors other tabs
        let user: UserProfile?
    }


    /// Get user profile
    func getUserProfile() async throws -> UserProfile {
        let data = try await get("/user/profile")

        #if DEBUG
        // Log raw payload characteristics
        DevLogger.shared.info("[PROFILE][GET] bytes=\(data.count)", context: "APIClient")
        if let jsonString = String(data: data, encoding: .utf8) {
            let head = String(jsonString.prefix(400))
            DevLogger.shared.info("[PROFILE][GET] json_head=\(head)", context: "APIClient")
        }
        // Log top-level keys and a few salient values before decoding
        do {
            let obj = try JSONSerialization.jsonObject(with: data, options: [])
            if let dict = obj as? [String: Any] {
                let keys = Array(dict.keys).sorted()
                DevLogger.shared.info("[PROFILE][GET] json_keys=\(keys)", context: "APIClient")
                let fn = dict["full_name"] ?? "nil"
                let pn = dict["preferred_name"] ?? "nil"
                let em = dict["email"] ?? "nil"
                DevLogger.shared.info("[PROFILE][GET] values full_name='\(fn)' preferred_name='\(pn)' email='\(em)'", context: "APIClient")
            } else {
                DevLogger.shared.info("[PROFILE][GET] json_root_is_not_object", context: "APIClient")
            }
        } catch {
            DevLogger.shared.error("[PROFILE][GET] json_parse_error: \(error)", context: "APIClient")
        }
        #endif
        
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .customISO8601
        
        do {
            // 1) Try direct decode to UserProfile
            var profile = try decoder.decode(UserProfile.self, from: data)
            #if DEBUG
            let allFields = """
            [PROFILE][DECODED] ALL FIELDS:
              id=\(profile.id)
              full_name='\(profile.full_name ?? "nil")'
              preferred_name='\(profile.preferred_name ?? "nil")'
              email='\(profile.email ?? "nil")'
              job_title='\(profile.job_title ?? "nil")'
              company_name='\(profile.company_name ?? "nil")'
              industry='\(profile.industry ?? "nil")'
              default_formality=\(profile.default_formality?.rawValue ?? "nil")
              default_tone=\(profile.default_tone?.rawValue ?? "nil")
            """
            DevLogger.shared.info(allFields, context: "APIClient")
            #endif
            // If everything is nil, attempt tolerant fallbacks
            let allNil = profile.full_name == nil &&
                         profile.preferred_name == nil &&
                         profile.email == nil &&
                         profile.job_title == nil &&
                         profile.company_name == nil &&
                         profile.industry == nil
            if allNil {
                #if DEBUG
                DevLogger.shared.info("[PROFILE][FALLBACK] Direct decode yielded empty fields. Trying envelope...", context: "APIClient")
                #endif
                if let env = try? decoder.decode(UserProfileEnvelope.self, from: data) {
                    if let wrapped = env.profile ?? env.data ?? env.settings ?? env.user {
                        profile = wrapped
                        #if DEBUG
                        DevLogger.shared.info("[PROFILE][FALLBACK] Envelope used. full_name='\(profile.full_name ?? "nil")'", context: "APIClient")
                        #endif
                        return profile
                    }
                }
            }
            #if DEBUG
            DevLogger.shared.info("[PROFILE][RETURN] Returning direct decode (no fallback triggered)", context: "APIClient")
            #endif
            return profile
        } catch {
            #if DEBUG
            DevLogger.shared.error("[PROFILE][DECODE] failed: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    /// Create or update user profile
    func saveUserProfile(_ profileData: UserProfileCreate) async throws -> UserProfile {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let encodedData = try encoder.encode(profileData)
        
        let responseData = try await post("/user/profile", body: encodedData)
        
        #if DEBUG
        if let jsonString = String(data: responseData, encoding: .utf8) {
            DevLogger.shared.info("Profile POST response: \(jsonString)", context: "APIClient")
        }
        #endif
        
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .customISO8601
        
        do {
            return try decoder.decode(UserProfile.self, from: responseData)
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to decode UserProfile from save: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    /// Delete user profile and all personalization data
    func deleteUserProfile() async throws {
        _ = try await delete("/user/profile")
    }
    
    // MARK: - Writing Samples
    
    /// Get count of writing samples
    func getWritingSamplesCount(contextType: String? = nil) async throws -> Int {
        var endpoint = "/user/writing-samples/count"
        if let contextType = contextType {
            endpoint += "?context_type=\(contextType)"
        }
        
        let data = try await get(endpoint)
        let decoder = JSONDecoder()
        
        struct CountResponse: Codable {
            let count: Int
        }
        
        let response = try decoder.decode(CountResponse.self, from: data)
        return response.count
    }
    
    /// List writing samples with pagination
    func listWritingSamples(contextType: String? = nil, limit: Int = 50, offset: Int = 0) async throws -> WritingSamplesListResponse {
        var endpoint = "/user/writing-samples?limit=\(limit)&offset=\(offset)"
        if let contextType = contextType {
            endpoint += "&context_type=\(contextType)"
        }
        
        let data = try await get(endpoint)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .customISO8601
        
        return try decoder.decode(WritingSamplesListResponse.self, from: data)
    }
    
    /// Delete a specific writing sample
    func deleteWritingSample(id: String) async throws {
        _ = try await delete("/user/writing-samples/\(id)")
    }
    
    /// Delete all writing samples (optionally filtered by context type)
    func deleteAllWritingSamples(contextType: String? = nil) async throws -> Int {
        var endpoint = "/user/writing-samples"
        if let contextType = contextType {
            endpoint += "?context_type=\(contextType)"
        }
        
        // Make direct HTTP request to get JSON response
        guard let url = URL(string: "\(baseURL)\(endpoint)") else {
            throw URLError(.badURL)
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let (data, _) = try await URLSession.shared.data(for: request)
        let decoder = JSONDecoder()
        
        struct DeleteResponse: Codable {
            let success: Bool
            let count: Int
            let message: String
        }
        
        let response = try decoder.decode(DeleteResponse.self, from: data)
        return response.count
    }
    
    // MARK: - Communication Style Analysis
    
    /// Get communication style profile for a specific context
    func getCommunicationStyle(contextType: String) async throws -> CommunicationStyleProfile? {
        do {
            let data = try await get("/user/style/\(contextType)")
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .customISO8601
            return try decoder.decode(CommunicationStyleProfile.self, from: data)
        } catch {
            // Return nil if 404 (no profile found), otherwise throw
            if let urlError = error as? URLError, urlError.code == .badServerResponse {
                return nil
            }
            throw error
        }
    }
    
    /// Trigger style analysis for a specific context
    func analyzeStyle(contextType: String, forceReanalysis: Bool = false) async throws -> CommunicationStyleProfile {
        var endpoint = "/user/style/analyze/\(contextType)"
        if forceReanalysis {
            endpoint += "?force_reanalysis=true"
        }
        
        let data = try await postForData(endpoint)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .customISO8601
        
        struct AnalyzeResponse: Codable {
            let success: Bool
            let context_type: String
            let profile: CommunicationStyleProfile
            let message: String
        }
        
        let response = try decoder.decode(AnalyzeResponse.self, from: data)
        return response.profile
    }
    
    /// Analyze all contexts that have writing samples
    func analyzeAllStyles() async throws -> [String: CommunicationStyleProfile] {
        let data = try await postForData("/user/style/analyze-all")
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .customISO8601
        
        struct AnalyzeAllResponse: Codable {
            let success: Bool
            let analyzed_contexts: Int
            let results: [String: ContextResult]
            let message: String
        }
        
        struct ContextResult: Codable {
            let success: Bool
            let confidence: Double?
            let sample_count: Int?
            let profile: CommunicationStyleProfile?
            let message: String?
        }
        
        let response = try decoder.decode(AnalyzeAllResponse.self, from: data)
        
        // Extract successful profiles
        var profiles: [String: CommunicationStyleProfile] = [:]
        for (contextType, result) in response.results {
            if result.success, let profile = result.profile {
                profiles[contextType] = profile
            }
        }
        
        return profiles
    }
}

