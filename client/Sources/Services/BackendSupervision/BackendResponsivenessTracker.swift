import Foundation

/// Pure state machine behind ``BackendResponsivenessMonitor``: it is told the result of each backend health probe and says when the backend has been unresponsive for long enough to offer the user a restart. It owns no clock, timer, or network, so a test can drive it with explicit times.
///
/// Probes that fail before the backend has ever answered are ignored, because a backend that is still starting up is not a frozen one. A single successful probe clears the unresponsive streak, so a backend that is merely slow, or that answers between long stalls, never reaches the offer.
struct BackendResponsivenessTracker {
    enum Event: Equatable {
        /// Every probe has failed for ``offerAfterSeconds`` or more, and no offer is outstanding or the re-offer interval has passed. `unresponsiveSeconds` is the length of the streak so far.
        case offerRestart(unresponsiveSeconds: Double)
        /// The backend answered after a restart offer had been made for the streak that just ended.
        case recoveredAfterOffer
    }

    let offerAfterSeconds: Double
    let reofferAfterSeconds: Double
    private(set) var hasBeenHealthy = false
    private(set) var unresponsiveSince: Double?
    private(set) var lastOfferAt: Double?

    init(offerAfterSeconds: Double, reofferAfterSeconds: Double) {
        self.offerAfterSeconds = offerAfterSeconds
        self.reofferAfterSeconds = reofferAfterSeconds
    }

    /// Records one probe result taken at monotonic time `now` (seconds).
    mutating func record(isHealthy: Bool, now: Double) -> Event? {
        if isHealthy {
            let hadOffer = lastOfferAt != nil
            hasBeenHealthy = true
            unresponsiveSince = nil
            lastOfferAt = nil
            return hadOffer ? .recoveredAfterOffer : nil
        }
        guard hasBeenHealthy else { return nil }
        guard let since = unresponsiveSince else {
            unresponsiveSince = now
            return nil
        }
        let streak = now - since
        guard streak >= offerAfterSeconds else { return nil }
        if let offeredAt = lastOfferAt, now - offeredAt < reofferAfterSeconds { return nil }
        lastOfferAt = now
        return .offerRestart(unresponsiveSeconds: streak)
    }

    /// Ends the current unresponsive streak and any outstanding offer, but keeps knowing the backend has been healthy before. Call it after the user-approved restart finishes: if the new process still does not answer, a fresh streak starts and the offer returns after ``offerAfterSeconds``.
    mutating func clearStreak() {
        unresponsiveSince = nil
        lastOfferAt = nil
    }
}
