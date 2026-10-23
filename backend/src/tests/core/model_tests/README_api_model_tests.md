# API Models Testing

`test_api_models.py` is a manual script that checks the API-key manager and the Claude and OpenAI model implementations against the live providers. It is not a pytest suite and it is not part of CI, because it needs real provider keys and network access and it spends tokens.

## What it checks

1. **API key management:** setting and reading a user key, switching between the application key and a user key, and clearing a user key. Key values live in the operating-system credential store, as described in `backend/src/config/README_api_keys.md`.
2. **Claude model:** initialization, switching models with `configure`, extended thinking, text generation, and streaming.
3. **OpenAI model:** initialization and text generation.

## Running it

The model names hard-coded in the script are historical and some have since been retired by their providers. Update them to models that are currently available before you run it.

```bash
cd backend/src/tests/core/model_tests
python test_api_models.py
```

The script adds `backend/src` to `sys.path`, prints a pass, fail, or partial result for each check, and writes the results to `api_models_test_results.json` in the same directory. That file is a local run artifact.

## Troubleshooting

1. **API key errors:** make sure a key is available for the provider, either in the environment (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`) or through the key settings.
2. **Import errors:** check that the path to `backend/src` near the top of the script is correct for where you run it.
3. **Network errors:** the checks call the provider APIs, so they need an internet connection.
