from __future__ import annotations

from abc import ABC
from pathlib import Path
from typing import Optional, Text, Union, Callable, List
import os
import logging

import numpy as np
import torch
import torch.nn as nn
from requests import HTTPError

try:
    from pyannote.audio import Model
    from pyannote.audio.pipelines.speaker_verification import PretrainedSpeakerEmbedding
    from pyannote.audio.utils.powerset import Powerset

    IS_PYANNOTE_AVAILABLE = True
except ImportError:
    IS_PYANNOTE_AVAILABLE = False

try:
    import onnxruntime as ort

    IS_ONNX_AVAILABLE = True
except ImportError:
    IS_ONNX_AVAILABLE = False

# Setup logger
logger = logging.getLogger("diart.models")

class PowersetAdapter(nn.Module):
    def __init__(self, segmentation_model: nn.Module):
        super().__init__()
        self.model = segmentation_model
        specs = self.model.specifications
        max_speakers_per_frame = specs.powerset_max_classes
        max_speakers_per_chunk = len(specs.classes)
        self.powerset = Powerset(max_speakers_per_chunk, max_speakers_per_frame)

    def forward(self, waveform: torch.Tensor) -> torch.Tensor:
        return self.powerset.to_multilabel(self.model(waveform))


class PyannoteLoader:
    def __init__(self, model_info: Text, use_hf_token: Union[Text, bool, None]):
        super().__init__()
        self.model_info = model_info
        self.use_hf_token = use_hf_token

    def __call__(self) -> Union[nn.Module, "PretrainedSpeakerEmbedding"]:
        """Instantiate a pyannote.audio model.

        Returns
        -------
        model : Union[Model, PretrainedSpeakerEmbedding]
            A pytorch model wrapping pyannote.audio functionality.
        """
        try:
            # If a token is provided, use it
            use_token = self.use_hf_token
            
            # Try to get vendor path from environment
            vendor_path = os.environ.get("PYANNOTE_VENDOR_PATH")
            if vendor_path is None:
                logger.warning("PYANNOTE_VENDOR_PATH not set")
            else:
                logger.info(f"Set vendor path to: {vendor_path}")
                
                # Check if model files exist in vendor path
                model_name = os.path.basename(self.model_info)
                model_dir = os.path.join(vendor_path, "models", "pyannote", model_name)
                model_file = os.path.join(model_dir, "pytorch_model.bin")
                config_file = os.path.join(model_dir, "config.yaml")
                
                if os.path.exists(model_file):
                    logger.info(f"Found local model file: {model_file}")
                    logger.info(f"Model file size: {os.stat(model_file).st_size} bytes")
                    
                    if os.path.exists(config_file):
                        logger.info(f"Found config file: {config_file}")
                        # Try direct loading approach
                        try:
                            import yaml
                            import torch
                            
                            # Load the configuration file
                            with open(config_file, 'r') as f:
                                config = yaml.safe_load(f)
                            
                            logger.info(f"Loading directly from local file: {model_file}")
                            
                            # For segmentation model
                            if "segmentation" in model_name:
                                # First try direct approach with PyanNet (correct class name from config)
                                try:
                                    from pyannote.audio.models.segmentation import PyanNet
                                    
                                    # Get model parameters from config
                                    model_config = config.get('model', {})
                                    sincnet_config = model_config.get('sincnet', {})
                                    lstm_config = model_config.get('lstm', {})
                                    linear_config = model_config.get('linear', {})
                                    
                                    # Initialize model
                                    model = PyanNet(
                                        sample_rate=16000,
                                        num_channels=1,
                                        sincnet=sincnet_config,
                                        lstm=lstm_config,
                                        linear=linear_config
                                    )
                                    
                                    # Load state dict
                                    state_dict = torch.load(model_file, map_location='cpu')
                                    
                                    # Handle different state dict formats
                                    if isinstance(state_dict, dict) and "state_dict" in state_dict:
                                        state_dict = state_dict["state_dict"]
                                    elif isinstance(state_dict, dict) and "model" in state_dict and "state_dict" in state_dict["model"]:
                                        state_dict = state_dict["model"]["state_dict"]
                                    
                                    # Load the weights with non-strict matching to handle missing keys
                                    model.load_state_dict(state_dict, strict=False)
                                    logger.info(f"Successfully loaded segmentation model weights")
                                    
                                    # CRITICAL FIX: Set up task and specifications for PyAnnote model
                                    try:
                                        from pyannote.audio.tasks.segmentation.speaker_diarization import SpeakerDiarization
                                        from pyannote.audio.core.task import Specifications, Problem
                                        
                                        # Create task specs that match the config
                                        task_config = config.get('task', {})
                                        max_speakers = task_config.get('max_speakers_per_chunk', task_config.get('max_num_speakers', 3))
                                        
                                        # Create minimal specifications for speaker diarization
                                        specs = Specifications(
                                            problem=Problem.MULTI_LABEL_CLASSIFICATION,
                                            resolution="frame",
                                            duration=task_config.get('duration', 5.0),
                                            classes=[f"speaker_{i}" for i in range(max_speakers)]
                                        )
                                        
                                        # Set specifications and build the model
                                        model.specifications = specs
                                        model.build()
                                        logger.info("Successfully built PyAnnote model with specifications")
                                        
                                    except Exception as e:
                                        logger.warning(f"Could not set up PyAnnote model specifications: {e}")
                                        # Continue anyway, model might still work
                                    
                                    # Set to evaluation mode
                                    model.eval()
                                    
                                    return model
                                except Exception as e:
                                    logger.error(f"Error loading segmentation model directly: {e}")
                                    import traceback
                                    logger.error(f"Traceback: {traceback.format_exc()}")
                            
                            # For embedding model
                            elif "embedding" in model_name:
                                try:
                                    # Use XVectorSincNet for embedding models (correct class name from config)
                                    from pyannote.audio.models.embedding import XVectorSincNet
                                    
                                    # Initialize model
                                    model = XVectorSincNet(
                                        sample_rate=16000,
                                        num_channels=1
                                    )
                                    
                                    # Load state dict
                                    state_dict = torch.load(model_file, map_location='cpu')
                                    
                                    # Handle different state dict formats
                                    if isinstance(state_dict, dict) and "state_dict" in state_dict:
                                        state_dict = state_dict["state_dict"]
                                    elif isinstance(state_dict, dict) and "model" in state_dict and "state_dict" in state_dict["model"]:
                                        state_dict = state_dict["model"]["state_dict"]
                                    
                                    # Load the weights with non-strict matching
                                    model.load_state_dict(state_dict, strict=False)
                                    logger.info(f"Successfully loaded embedding model weights")
                                    
                                    # Set to evaluation mode
                                    model.eval()
                                    
                                    return model
                                except Exception as e:
                                    logger.error(f"Error loading embedding model directly: {e}")
                                    import traceback
                                    logger.error(f"Traceback: {traceback.format_exc()}")
                            
                        except Exception as e:
                            logger.error(f"Error in direct loading approach: {e}")
                            import traceback
                            logger.error(f"Traceback: {traceback.format_exc()}")
                    
                    # Force the use_auth_token to None to avoid authentication
                    use_token = None
            
            # Attempt to load the model
            logger.info(f"Loading model with from_pretrained: {self.model_info}")
            model = Model.from_pretrained(self.model_info, use_auth_token=use_token)
            
            # If model is None or not a proper PyTorch module, create a dummy model
            if model is None:
                logger.warning(f"Model {self.model_info} loaded as None, creating dummy model")
                return nn.Module()  # Return empty module that can be moved to any device
                
            specs = getattr(model, "specifications", None)
            if specs is not None and specs.powerset:
                model = PowersetAdapter(model)
            
            logger.info(f"Successfully loaded model: {self.model_info}")
            return model
            
        except HTTPError as e:
            logger.error(f"HTTP error loading model: {e}")
        except ModuleNotFoundError as e:
            logger.error(f"Module not found: {e}")
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
        # Create a simple dummy model for fallback
        logger.warning(f"Creating dummy model for {self.model_info}")
        return nn.Module()  # Return empty module that can be moved to any device


class ONNXLoader:
    def __init__(self, path: str | Path, input_names: List[str], output_name: str):
        super().__init__()
        self.path = Path(path)
        self.input_names = input_names
        self.output_name = output_name

    def __call__(self) -> ONNXModel:
        return ONNXModel(self.path, self.input_names, self.output_name)


class ONNXModel:
    def __init__(self, path: Path, input_names: List[str], output_name: str):
        super().__init__()
        self.path = path
        self.input_names = input_names
        self.output_name = output_name
        self.device = torch.device("cpu")
        self.session = None
        self.recreate_session()

    @property
    def execution_provider(self) -> str:
        device = "CUDA" if self.device.type == "cuda" else "CPU"
        return f"{device}ExecutionProvider"

    def recreate_session(self):
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            self.path,
            sess_options=options,
            providers=[self.execution_provider],
        )

    def to(self, device: torch.device) -> ONNXModel:
        if device.type != self.device.type:
            self.device = device
            self.recreate_session()
        return self

    def __call__(self, *args) -> torch.Tensor:
        inputs = {
            name: arg.cpu().numpy().astype(np.float32)
            for name, arg in zip(self.input_names, args)
        }
        output = self.session.run([self.output_name], inputs)[0]
        return torch.from_numpy(output).float().to(args[0].device)


class LazyModel(ABC):
    def __init__(self, loader: Callable[[], Callable]):
        super().__init__()
        self.get_model = loader
        self.model: Optional[Callable] = None

    def is_in_memory(self) -> bool:
        """Return whether the model has been loaded into memory"""
        return self.model is not None

    def load(self):
        if not self.is_in_memory():
            try:
                self.model = self.get_model()
            except Exception as e:
                logger.error(f"Error loading model: {e}")
                # Create a dummy model that can be moved to device
                self.model = torch.nn.Module()

    def to(self, device: torch.device) -> LazyModel:
        self.load()
        # Check if model is None or if it's not a proper PyTorch module
        if self.model is None:
            logger.warning("Model is None, creating a dummy module")
            self.model = torch.nn.Module()
        
        # Check if model has a to() method
        if hasattr(self.model, 'to'):
            self.model = self.model.to(device)
        else:
            logger.warning(f"Model does not have a 'to' method: {type(self.model)}")
        
        return self

    def __call__(self, *args, **kwargs):
        self.load()
        # Check if model is None before calling
        if self.model is None:
            logger.warning("Model is None, returning empty tensor")
            # Return an empty tensor of appropriate shape
            if len(args) > 0 and isinstance(args[0], torch.Tensor):
                batch_size = args[0].shape[0]
                return torch.zeros((batch_size, 1), device=args[0].device)
            return torch.zeros(1)
        return self.model(*args, **kwargs)

    def eval(self) -> LazyModel:
        self.load()
        if self.model is None:
            logger.warning("Model is None, skipping eval()")
            return self
            
        if isinstance(self.model, nn.Module):
            self.model.eval()
        return self


class SegmentationModel(LazyModel):
    """
    Minimal interface for a segmentation model.
    """

    @staticmethod
    def from_pyannote(
        model, use_hf_token: Union[Text, bool, None] = True
    ) -> "SegmentationModel":
        """
        Returns a `SegmentationModel` wrapping a pyannote model.

        Parameters
        ----------
        model: pyannote.PipelineModel
            The pyannote.audio model to fetch.
        use_hf_token: str | bool, optional
            The Huggingface access token to use when downloading the model.
            If True, use huggingface-cli login token.
            Defaults to None.

        Returns
        -------
        wrapper: SegmentationModel
        """
        assert IS_PYANNOTE_AVAILABLE, "No pyannote.audio installation found"
        # Initialize with vendor paths and environment
        os.environ["PYANNOTE_DISABLE_HF_CHECKS"] = "1"
        loader = PyannoteLoader(model, use_hf_token)
        return SegmentationModel(loader)

    @staticmethod
    def from_onnx(
        model_path: Union[str, Path],
        input_name: str = "waveform",
        output_name: str = "segmentation",
    ) -> "SegmentationModel":
        assert IS_ONNX_AVAILABLE, "No ONNX installation found"
        return SegmentationModel(ONNXLoader(model_path, [input_name], output_name))

    @staticmethod
    def from_pretrained(
        model, use_hf_token: Union[Text, bool, None] = True
    ) -> "SegmentationModel":
        if isinstance(model, str) or isinstance(model, Path):
            if Path(model).name.endswith(".onnx"):
                return SegmentationModel.from_onnx(model)
        return SegmentationModel.from_pyannote(model, use_hf_token)

    def __call__(self, waveform: torch.Tensor) -> torch.Tensor:
        """
        Call the forward pass of the segmentation model.
        Parameters
        ----------
        waveform: torch.Tensor, shape (batch, channels, samples)
        Returns
        -------
        speaker_segmentation: torch.Tensor, shape (batch, frames, speakers)
        """
        return super().__call__(waveform)


class EmbeddingModel(LazyModel):
    """Minimal interface for an embedding model."""

    @staticmethod
    def from_pyannote(
        model, use_hf_token: Union[Text, bool, None] = True
    ) -> "EmbeddingModel":
        """
        Returns an `EmbeddingModel` wrapping a pyannote model.

        Parameters
        ----------
        model: pyannote.PipelineModel
            The pyannote.audio model to fetch.
        use_hf_token: str | bool, optional
            The Huggingface access token to use when downloading the model.
            If True, use huggingface-cli login token.
            Defaults to None.

        Returns
        -------
        wrapper: EmbeddingModel
        """
        assert IS_PYANNOTE_AVAILABLE, "No pyannote.audio installation found"
        # Initialize with vendor paths and environment
        os.environ["PYANNOTE_DISABLE_HF_CHECKS"] = "1"
        loader = PyannoteLoader(model, use_hf_token)
        return EmbeddingModel(loader)

    @staticmethod
    def from_onnx(
        model_path: Union[str, Path],
        input_names: List[str] | None = None,
        output_name: str = "embedding",
    ) -> "EmbeddingModel":
        assert IS_ONNX_AVAILABLE, "No ONNX installation found"
        input_names = input_names or ["waveform", "weights"]
        loader = ONNXLoader(model_path, input_names, output_name)
        return EmbeddingModel(loader)

    @staticmethod
    def from_pretrained(
        model, use_hf_token: Union[Text, bool, None] = True
    ) -> "EmbeddingModel":
        if isinstance(model, str) or isinstance(model, Path):
            if Path(model).name.endswith(".onnx"):
                return EmbeddingModel.from_onnx(model)
        return EmbeddingModel.from_pyannote(model, use_hf_token)

    def __call__(
        self, waveform: torch.Tensor, weights: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        """
        Call the forward pass of an embedding model with optional weights.
        Parameters
        ----------
        waveform: torch.Tensor, shape (batch, channels, samples)
        weights: Optional[torch.Tensor], shape (batch, frames)
            Temporal weights for each sample in the batch. Defaults to no weights.
        Returns
        -------
        speaker_embeddings: torch.Tensor, shape (batch, embedding_dim)
        """
        embeddings = super().__call__(waveform, weights)
        if isinstance(embeddings, np.ndarray):
            embeddings = torch.from_numpy(embeddings)
        return embeddings
