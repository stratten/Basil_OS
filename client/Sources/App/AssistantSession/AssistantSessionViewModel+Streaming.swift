import SwiftUI
import Combine
import Foundation

// MARK: - Streaming: Token Processing State Machine
extension AssistantSessionViewModel {
    
    // MARK: - Streaming Token Processing
    
    /// Processes incoming streaming tokens, parsing <think> tags and separating thinking from content.
    /// Uses a state machine approach to handle partial tags across token boundaries.
    /// - Parameters:
    ///   - token: The incoming token string to process.
    ///   - isFinal: Whether this is the final token (triggers buffer flush).
    func processStreamingToken(_ token: String, isFinal: Bool) {
        guard var state = streamingState else { return }
        
        state.buffer += token
        
        // Helper to retain potential start/end tag fragments while still streaming
        let thinkStart = "<think>"
        let thinkEnd = "</think>"
        let preserveOutside = max(0, thinkStart.count - 1)
        let preserveInside = max(0, thinkEnd.count - 1)
        
        processingLoop: while !state.buffer.isEmpty {
            if state.isInsideThinking {
                // Looking for closing tag
                if let closingRange = state.buffer.range(of: thinkEnd) {
                    let segment = String(state.buffer[..<closingRange.lowerBound])
                    state.thinking += segment
                    state.buffer = String(state.buffer[closingRange.upperBound...])
                    state.isInsideThinking = false
                    continue processingLoop
                } else {
                    // No closing tag yet, flush most of buffer but preserve end for potential tag
                    let countToFlush = max(0, state.buffer.count - preserveInside)
                    if countToFlush > 0 {
                        let flushEnd = state.buffer.index(state.buffer.startIndex, offsetBy: countToFlush)
                        let segment = String(state.buffer[..<flushEnd])
                        state.thinking += segment
                        state.buffer = String(state.buffer[flushEnd...])
                    }
                    break processingLoop
                }
            } else {
                // Looking for opening tag
                if let openingRange = state.buffer.range(of: thinkStart) {
                    let segment = String(state.buffer[..<openingRange.lowerBound])
                    state.content += segment
                    state.buffer = String(state.buffer[openingRange.upperBound...])
                    state.isInsideThinking = true
                    continue processingLoop
                } else {
                    // No opening tag, flush most of buffer but preserve end for potential tag
                    let countToFlush = max(0, state.buffer.count - preserveOutside)
                    if countToFlush > 0 {
                        let flushEnd = state.buffer.index(state.buffer.startIndex, offsetBy: countToFlush)
                        let segment = String(state.buffer[..<flushEnd])
                        state.content += segment
                        state.buffer = String(state.buffer[flushEnd...])
                    }
                    break processingLoop
                }
            }
        }
        
        // On final, flush remaining buffer
        if isFinal && !state.buffer.isEmpty {
            if state.isInsideThinking {
                state.thinking += state.buffer
            } else {
                state.content += state.buffer
            }
            state.buffer = ""
        }
        
        // Update stored state
        streamingState = state
        
        // Update UI properties with current state
        updateUIFromStreamingState(isFinal: isFinal)
    }
    
    // MARK: - Buffer Flush
    
    /// Flushes any remaining content in the streaming buffer.
    /// Called when streaming is complete to ensure no content is lost.
    /// - Parameter isFinal: Whether this is the final flush operation.
    func flushStreamingBuffer(isFinal: Bool) {
        guard var state = streamingState else { return }
        
        if !state.buffer.isEmpty {
            if state.isInsideThinking {
                state.thinking += state.buffer
            } else {
                state.content += state.buffer
            }
            state.buffer = ""
        }
        
        streamingState = state
        updateUIFromStreamingState(isFinal: isFinal)
    }
    
    // MARK: - UI State Synchronisation
    
    /// Updates the published UI properties from the current streaming state.
    /// Handles normalisation (trimming) on final updates.
    /// - Parameter isFinal: Whether this is the final update (triggers trimming).
    func updateUIFromStreamingState(isFinal: Bool) {
        guard let state = streamingState else { return }
        
        var normalizedContent = state.content
        var normalizedThinking = state.thinking
        
        if isFinal {
            normalizedContent = normalizedContent.trimmingCharacters(in: .whitespacesAndNewlines)
            normalizedThinking = normalizedThinking.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        
        // Update properties
        assistantOutput = normalizedContent
        thinkingContent = normalizedThinking.isEmpty ? nil : normalizedThinking
    }
}
