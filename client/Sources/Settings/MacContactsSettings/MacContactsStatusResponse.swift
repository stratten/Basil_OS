struct MacContactsStatusResponse: Codable {
    let available: Bool
    let preferenceEnabled: Bool
    let authorizationStatus: String
    let canLookup: Bool
    let detail: String?
}
