from pathlib import Path

import onnxruntime as ort

from api.services.wake_word import wake_word_detector

VENDOR_DIR = Path(wake_word_detector.__file__).resolve().parents[2] / "vendor" / "models" / "wake_word"


def test_each_basil_wake_word_name_resolves_to_exactly_one_bundled_model():
    names = [name for name in wake_word_detector.PRE_TRAINED_MODELS_TO_USE if name.startswith("hey_basil")]
    assert names
    for name in names:
        matches = sorted(path.name for path in VENDOR_DIR.glob(f"{name}*.onnx"))
        assert len(matches) == 1, f"{name} matches {matches}"


def test_every_bundled_basil_model_has_the_input_and_output_the_detector_feeds():
    files = sorted(VENDOR_DIR.glob("hey_basil*.onnx"))
    assert files
    for path in files:
        session = ort.InferenceSession(str(path))
        assert [(item.name, list(item.shape)) for item in session.get_inputs()] == [("input_layer", [1, 16, 96])]
        assert [list(item.shape) for item in session.get_outputs()] == [[1, 1]]
