# API Models Testing

This document provides instructions for testing the API models integration in Basil.

## API Models Test Script

The `test_api_models.py` script tests the following components:

1. **API Key Management System**:
   - Setting and retrieving user API keys
   - Switching between application and user keys
   - Clearing user API keys

2. **Claude Model Implementation**:
   - Model initialization and loading
   - Switching between different Claude models (3, 3.5, 3.7)
   - Testing extended thinking mode for Claude 3.7
   - Basic text generation
   - Streaming response generation

## Running the Tests

To run the test script, follow these steps:

1. Make sure you have the required dependencies installed:
   ```bash
   pip install anthropic python-dotenv
   ```

2. From the Basil project root directory, run:
   ```bash
   cd Basil/tests/core/model_tests
   python test_api_models.py
   ```

3. The test will run through a series of checks and display results for each component.

4. Test results will also be saved to `api_models_test_results.json` in the same directory.

## Interpreting Results

The test script will output a summary showing:
- ✅ PASS: Test passed successfully
- ❌ FAIL: Test failed (with error details)
- ⚠️ PARTIAL: Test passed with limitations

## Troubleshooting

Common issues:

1. **API Key Errors**: Ensure the Anthropic API key is correctly set up in the API key management system.

2. **Import Errors**: If you encounter import errors, check the import path in the test script. It should correctly reference the Basil src directory.

3. **Network Errors**: The tests require an internet connection to communicate with the Anthropic API. Check your connection if API requests fail.

4. **Path Issues**: The test creates temporary files in the user's home directory. Ensure the script has appropriate permissions to write to `~/.basil/`.

## Integration with Other Tests

This test follows the same pattern as other model tests in the project:
- Located in `tests/core/model_tests/`
- Uses a similar class-based structure
- Provides detailed test results and validation

## Next Steps

After validating that the Claude model implementation works correctly:

1. Implement the OpenAI model following a similar pattern
2. Add similar tests for the OpenAI model
3. Test integration with the conversation service
4. Add UI components for selecting and configuring API models 