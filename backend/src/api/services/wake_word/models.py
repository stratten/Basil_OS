from pydantic import BaseModel

class VoiceListenerSettings(BaseModel):
    voice_listener_enabled: bool = False
    # Future settings like audio_device_name: Optional[str] = None can be added here