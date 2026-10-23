import Foundation
import os

/// Type-safe API client extensions for automatic encoding/decoding
extension APIClient {
    
    // MARK: - Type-Safe GET
    
    /// Perform a type-safe GET request with automatic decoding
    ///
    /// - Parameters:
    ///   - path: API endpoint path
    ///   - decoding: The type to decode the response into
    ///   - keyDecodingStrategy: JSON key decoding strategy (default: convertFromSnakeCase)
    /// - Returns: Decoded response of type T
    /// - Throws: APIError if the request fails or decoding fails
    func get<T: Decodable>(
        _ path: String,
        decoding: T.Type,
        keyDecodingStrategy: JSONDecoder.KeyDecodingStrategy = .convertFromSnakeCase
    ) async throws -> T {
        let data = try await get(path)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = keyDecodingStrategy
        decoder.dateDecodingStrategy = .customISO8601
        
        do {
            return try decoder.decode(T.self, from: data)
        } catch let error as DecodingError {
            #if DEBUG
            logDecodingError(error, path: path, data: data)
            #endif
            throw APIError.decodingFailed(error)
        }
    }
    
    // MARK: - Type-Safe PUT
    
    /// Perform a type-safe PUT request with automatic encoding and decoding
    ///
    /// - Parameters:
    ///   - path: API endpoint path
    ///   - body: Request body to encode
    ///   - decoding: The type to decode the response into
    ///   - keyEncodingStrategy: JSON key encoding strategy (default: convertToSnakeCase)
    ///   - keyDecodingStrategy: JSON key decoding strategy (default: convertFromSnakeCase)
    /// - Returns: Decoded response of type Response
    /// - Throws: APIError if the request fails, encoding fails, or decoding fails
    func put<Request: Encodable, Response: Decodable>(
        _ path: String,
        body: Request,
        decoding: Response.Type,
        keyEncodingStrategy: JSONEncoder.KeyEncodingStrategy = .convertToSnakeCase,
        keyDecodingStrategy: JSONDecoder.KeyDecodingStrategy = .convertFromSnakeCase
    ) async throws -> Response {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = keyEncodingStrategy
        let bodyData = try encoder.encode(body)
        
        let responseData = try await put(path, data: bodyData)
        
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = keyDecodingStrategy
        decoder.dateDecodingStrategy = .customISO8601
        
        do {
            return try decoder.decode(Response.self, from: responseData)
        } catch let error as DecodingError {
            #if DEBUG
            logDecodingError(error, path: path, data: responseData)
            #endif
            throw APIError.decodingFailed(error)
        }
    }
    
    // MARK: - Type-Safe POST
    
    /// Perform a type-safe POST request with automatic encoding and decoding
    ///
    /// - Parameters:
    ///   - path: API endpoint path
    ///   - body: Request body to encode
    ///   - decoding: The type to decode the response into
    ///   - keyEncodingStrategy: JSON key encoding strategy (default: convertToSnakeCase)
    ///   - keyDecodingStrategy: JSON key decoding strategy (default: convertFromSnakeCase)
    /// - Returns: Decoded response of type Response
    /// - Throws: APIError if the request fails, encoding fails, or decoding fails
    func post<Request: Encodable, Response: Decodable>(
        _ path: String,
        body: Request,
        decoding: Response.Type,
        keyEncodingStrategy: JSONEncoder.KeyEncodingStrategy = .convertToSnakeCase,
        keyDecodingStrategy: JSONDecoder.KeyDecodingStrategy = .convertFromSnakeCase
    ) async throws -> Response {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = keyEncodingStrategy
        let bodyData = try encoder.encode(body)
        
        let responseData = try await post(path, body: bodyData)
        
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = keyDecodingStrategy
        decoder.dateDecodingStrategy = .customISO8601
        
        do {
            return try decoder.decode(Response.self, from: responseData)
        } catch let error as DecodingError {
            #if DEBUG
            logDecodingError(error, path: path, data: responseData)
            #endif
            throw APIError.decodingFailed(error)
        }
    }
    
    // MARK: - Error Logging
    
    #if DEBUG
    /// Log detailed decoding error information for debugging
    private func logDecodingError(_ error: DecodingError, path: String, data: Data) {
        logger.error("❌ Decoding failed for \(path)")
        
        switch error {
        case .keyNotFound(let key, let context):
            logger.error("  Missing key: '\(key.stringValue)' at path: \(context.codingPath.map(\.stringValue).joined(separator: "."))")
            logger.error("  Debug description: \(context.debugDescription)")
            
        case .typeMismatch(let type, let context):
            logger.error("  Type mismatch: expected \(type) at path: \(context.codingPath.map(\.stringValue).joined(separator: "."))")
            logger.error("  Debug description: \(context.debugDescription)")
            
        case .valueNotFound(let type, let context):
            logger.error("  Value not found: \(type) at path: \(context.codingPath.map(\.stringValue).joined(separator: "."))")
            logger.error("  Debug description: \(context.debugDescription)")
            
        case .dataCorrupted(let context):
            logger.error("  Data corrupted at path: \(context.codingPath.map(\.stringValue).joined(separator: "."))")
            logger.error("  Debug description: \(context.debugDescription)")
            
        @unknown default:
            logger.error("  Unknown decoding error: \(error)")
        }
        
        // Log the raw JSON for debugging
        if let jsonString = String(data: data, encoding: .utf8) {
            logger.error("  Raw JSON response:")
            // Truncate if too long
            if jsonString.count > 1000 {
                logger.error("  \(jsonString.prefix(1000))... (truncated)")
            } else {
                logger.error("  \(jsonString)")
            }
        }
    }
    #endif
}

