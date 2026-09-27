# Project-specific Guidelines

## Managing Preferences and Settings

### Overview
Settings in Basil are managed through a consolidated preferences system that spans both the Swift client and Python backend. The system is designed to handle various types of settings (UI, behavior, models, etc.) in a consistent way.

### Critical Rules

1. **Model Synchronization**
   - Backend and client models MUST match EXACTLY
   - Field names must match (accounting for snake_case vs camelCase)
   - Required fields must be present on both sides
   - Default values should be consistent
   - Example of matching models:
   ```python
   # Backend (Python)
   class BehaviorSettings(BaseModel):
       start_on_startup: bool = Field(default=False)
       show_notifications: bool = Field(default=True)
       transcription_language: str = Field(default="en")
   ```
   ```swift
   // Client (Swift)
   struct BehaviorSettings: Codable {
       var startOnStartup: Bool
       var showNotifications: Bool
       var transcriptionLanguage: String
       
       enum CodingKeys: String, CodingKey {
           case startOnStartup = "start_on_startup"
           case showNotifications = "show_notifications"
           case transcriptionLanguage = "transcription_language"
       }
   }
   ```

2. **Field Requirements**
   - If a field is required in the backend model, it MUST be included in all client requests
   - Optional fields should be marked as such on both sides
   - When migrating settings, ensure all required fields have fallback values

3. **Version Compatibility**
   - When updating models, maintain compatibility with existing stored settings
   - Use migration logic to handle missing or deprecated fields
   - Consider adding version fields to settings models for future migrations

### Adding New Settings

1. **Define the Model (Backend)**
   - Add the new settings model in `backend/src/api/core/models/preferences.py`
   - Use Pydantic BaseModel with proper Field definitions and defaults
   - Include property methods for any computed values or enums
   ```python
   class NewSettingsType(BaseModel):
       setting_one: bool = Field(default=False, description="Description")
       setting_two: str = Field(default="default", description="Description")
   ```

2. **Add to Preferences Class**
   - Add the new settings to the appropriate parent class (UI, Behavior, Model)
   - If it's a new category, add it to the main Preferences class
   ```python
   class Preferences(BaseModel):
       existing_settings: ExistingType = Field(default_factory=ExistingType)
       new_settings: NewSettingsType = Field(default_factory=NewSettingsType)
   ```

3. **Create API Endpoints**
   - Add endpoints in `backend/src/api/routes/settings.py`
   - Include both GET and PUT endpoints
   - Follow the established pattern:
   ```python
   @router.get("/new_setting_type")
   async def get_new_settings() -> Dict[str, Any]:
       try:
           preferences = load_preferences()
           return {
               "status": "success",
               "settings": preferences.new_settings.model_dump()
           }
       except Exception as e:
           api_logger.error(f"❌ Error: {str(e)}", exc_info=True)
           raise HTTPException(status_code=500, detail=str(e))
   ```

4. **Define Client Model (Swift)**
   - Create corresponding model in the client
   - Match the structure of the backend model
   - Include proper Codable conformance
   ```swift
   struct NewSettingsResponse: Codable {
       let status: String
       let settings: NewSettings
   }

   struct NewSettings: Codable {
       let settingOne: Bool
       let settingTwo: String
       
       enum CodingKeys: String, CodingKey {
           case settingOne = "setting_one"
           case settingTwo = "setting_two"
       }
   }
   ```

5. **Add Client Caching (Optional)**
   - If settings need to be cached, add to `APIClient`:
   ```swift
   private var cachedNewSettings: NewSettings?
   
   func cacheNewSettings(_ settings: NewSettings) {
       cachedNewSettings = settings
   }
   ```

6. **Create Settings UI**
   - Add a new tab or section to the settings view
   - Create a dedicated ViewModel for the settings
   - Follow the established MVVM pattern

### Best Practices

1. **Consolidation**
   - Keep related settings together in a single model
   - Use a single endpoint for related settings
   - Avoid splitting logically related settings across multiple endpoints

2. **Migration**
   - When moving settings, include migration logic in the backend
   - Handle both old and new formats during transition
   - Provide fallback defaults for all settings

3. **Validation**
   - Use Pydantic validators for backend validation
   - Include proper error handling in both client and backend
   - Provide meaningful error messages

4. **Documentation**
   - Document all settings fields with descriptions
   - Include examples in comments for complex settings
   - Document any computed properties or special behaviors

### Common Pitfalls

1. **Avoid Circular Dependencies**
   - Don't create circular references between settings models
   - Keep the hierarchy clear and one-directional

2. **State Management**
   - Don't mix temporary state with persistent settings
   - Cache settings appropriately on the client side
   - Handle loading states properly in the UI

3. **Error Handling**
   - Always provide fallback defaults
   - Log errors comprehensively
   - Handle network failures gracefully

### Example: Adding Transcription Settings

```python
# 1. Define the model
class TranscriptionSettings(BaseModel):
    model_unload_delay: int = Field(
        default=TranscriptionModelUnloadDelay.MINUTES_1.value,
        description="Delay before unloading"
    )
    auto_paste: bool = Field(default=False)
    language: str = Field(default="en")
    selected_model: str = Field(default="base")

# 2. Add to preferences
class UIPreferences(BaseModel):
    transcription: TranscriptionSettings = Field(default_factory=TranscriptionSettings)

# 3. Create endpoints
@router.get("/transcription")
async def get_transcription_settings():
    preferences = load_preferences()
    settings = TranscriptionSettings(
        model_unload_delay=preferences.ui.transcription.model_unload_delay,
        auto_paste=preferences.ui.transcription.auto_paste,
        language=preferences.ui.transcription.language,
        selected_model=preferences.models.transcription_model
    )
    return {"status": "success", "settings": settings.model_dump()}
```

### Testing

1. **Backend Tests**
   - Add tests for new settings models
   - Test both valid and invalid inputs
   - Test migrations if applicable

2. **Client Tests**
   - Test settings persistence
   - Test UI updates
   - Test error handling

3. **Integration Tests**
   - Test full settings flow
   - Verify settings are properly saved and loaded
   - Test migration paths if applicable
