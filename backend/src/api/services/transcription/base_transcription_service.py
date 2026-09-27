from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class BaseTranscriptionService(ABC):
    def __init__(self):
        self._model_loaded = False

    def is_model_loaded(self) -> bool:
        """Return True if the transcription model is loaded."""
        return self._model_loaded

    @abstractmethod
    def load_model(self) -> None:
        """Load the transcription model.

        This method should load the necessary model and update the _model_loaded flag.
        """
        pass

    @abstractmethod
    def unload_model(self) -> None:
        """Unload the transcription model.

        This method should release the model resources and update the _model_loaded flag.
        """
        pass

    @abstractmethod
    async def transcribe(self, audio_data: bytes, context_info: Optional[Dict[str, Any]] = None) -> str:
        """Transcribe the provided audio data into text.

        :param audio_data: A bytes object containing audio input data.
        :param context_info: Optional dictionary containing context information.
        :return: The transcribed text as a string.
        """
        pass 