// Add the OCRResponse model

struct OCRResponse: Decodable {
    let status: String
    let imagePath: String
    let appName: String?
    let rawText: String?
    let cleanedText: String?
    let processedText: String?
    let formattedText: String?
    let formatType: String?
    let error: String?
    let errorType: String?
    let processingTimeMs: Int
    
    enum CodingKeys: String, CodingKey {
        case status
        case imagePath = "image_path"
        case appName = "app_name"
        case rawText = "raw_text"
        case cleanedText = "cleaned_text"
        case processedText = "processed_text"
        case formattedText = "formatted_text"
        case formatType = "format_type"
        case error
        case errorType = "error_type"
        case processingTimeMs = "processing_time_ms"
    }
} 