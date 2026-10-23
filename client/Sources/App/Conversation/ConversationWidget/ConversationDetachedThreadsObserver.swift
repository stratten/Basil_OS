import Foundation

@MainActor
protocol ConversationDetachedThreadsObserver: AnyObject {
    func updateDetachedConversationIds(_ ids: [String])
}
