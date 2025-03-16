# Alltrue LLM Observability SDK

Alltrue LLM Observability SDK provides monitoring, observability, and guardrails for Large Language Model interactions. It allows you to track, modify, and secure your LLM API calls with minimal code changes to your existing applications.

## Table of Contents
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Guardrails](#guardrails)
  - [Observers](#observers)
- [Features](#features)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Installation

### From GitHub

```shell
# Install directly from GitHub
pip install git+ssh://git@github.com/AllTrue-ai/alltrue-llm-observability.git#subdirectory=core
pip install git+ssh://git@github.com/AllTrue-ai/alltrue-llm-observability.git


# For development installation (editable mode)
git clone git@github.com:AllTrue-ai/alltrue-llm-observability.git
cd alltrue-llm-observability
pip install -e .[full]
 ```

## Configuration

Alltrue SDK can be configured through parameters or environment variables:

| Parameter | Environment Variable | Required | Description                                                                                                                                                                                                                                                                                |
|-----------|---------------------|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `alltrue_api_url` | `ALLTRUE_API_URL` | No | The tenant endpoint to send requests to. Defaults to the standard Alltrue API endpoint. This is configurable in case you have a custom tenant or need to use a proxy.                                                                                                                      |
| `alltrue_api_key` | `ALLTRUE_API_KEY` | Yes | Your API authentication key created inside the Alltrue application. This is used to authenticate your requests to the Alltrue API. See [API Keys documentation](https://prod.alltrue-be.com/_docs/docs/platform_services/admin_console#api-keys) for details on creating and managing keys. |
| `alltrue_customer_id` | `ALLTRUE_CUSTOMER_ID` | Yes | Your endpoint identifier configured in the AllTrue system application. This associates the API calls with your account.                                                                                                                                                                    |
| `alltrue_endpoint_identifier` | `ALLTRUE_ENDPOINT_IDENTIFIER` | Yes | Required identifier of the resource configured in the Alltrue application. This is used to match the API call with the specific settings and security rules that should be applied for observability.                                                                                      |
| `logging_level` | - | No | Sets the logging verbosity (e.g., "WARNING", "INFO", "DEBUG"). Defaults to "WARNING".                                                                                                                                                                                                      |
| `blocking` | - | No | Boolean flag indicating whether to block on detected abnormalities (for observers). When set to True, the SDK will prevent non-compliant requests/responses from proceeding. Defaults to False.                                                                                            |

## Usage

### Guardrails

Guardrails provide validation and filtering for LLM inputs and outputs. They can be used in two modes:

#### 1. Active Guardrails - Validating Messages

```python
from alltrue.guardrails.chat import ChatGuardrails, GuardrailsException
import httpx
import sys

# Initialize guardrails
guardrails = ChatGuardrails(
    alltrue_api_key="<API_KEY>",
    alltrue_customer_id="<CUSTOMER_ID>",
    alltrue_endpoint_identifier="<IDENTIFIER>",
    logging_level="WARNING",
)

messages = ["What day is today?"]

# Validate input messages before sending to LLM
try:
    guarded_input = await guardrails.guard_input(messages)
except GuardrailsException:
    print("Input validation failed - potential policy violation")
    sys.exit(1)

# Use the validated messages with OpenAI API
api_response = await httpx.AsyncClient(
    base_url=f"https://api.openai.com/v1",
).post(
    url=f"/chat/completions",
    json={
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": msg,
            }
            for msg in guarded_input
        ],
    },
)

# Extract model responses
responses = [
    c.get("message", {}).get("content", "")
    for c in api_response.json().get("choices", [])
]

# Validate model outputs
try:
    guarded_output = await guardrails.guard_output(messages, responses)
    # Use guarded_output in your application
except GuardrailsException:
    print("Output validation failed - potential unsafe content")
    sys.exit(1)
```

#### 2. Passive Observation - Monitoring Without Validation

```python
from alltrue.guardrails.chat import ChatGuardrails
import httpx

# Initialize guardrails
guardrails = ChatGuardrails(
    alltrue_api_key="<API_KEY>",
    alltrue_customer_id="<CUSTOMER_ID>",
    alltrue_endpoint_identifier="<IDENTIFIER>",
    logging_level="WARNING",
)

messages = ["What day is today?"]

# Monitor input without validation
guardrails.observe_input(messages)

# Call OpenAI API with original messages
api_response = await httpx.AsyncClient(
    base_url=f"https://api.openai.com/v1",
).post(
    url=f"/chat/completions",
    json={
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": msg,
            }
            for msg in messages
        ],
    },
)

# Extract model responses
responses = [
    c.get("message", {}).get("content", "")
    for c in api_response.json().get("choices", [])
]

# Monitor output without validation
guardrails.observe_output(messages, responses)
```

### Observers

Observers provide automated monitoring by intercepting LLM client calls directly, without requiring changes to your API calling code.

#### OpenAI Client Observer

```python
from alltrue.observers.openai import OpenAIObserver
from openai import OpenAI

# Initialize observer
observer = OpenAIObserver(
    alltrue_api_key="<API_KEY>",
    alltrue_customer_id="<CUSTOMER_ID>",
    alltrue_endpoint_identifier="<IDENTIFIER>",
    blocking=False,  # Set to True to validate and potentially block requests
    logging_level="WARNING",
)

# Register observer - from this point, all OpenAI client calls will be monitored
observer.register()

# Use OpenAI client as normal - monitoring happens automatically
completion = OpenAI().chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[
        {
            "role": "user",
            "content": "What day is today?",
        }
    ],
)

# Optional: unregister when monitoring is no longer needed
observer.unregister()
```

## Features

- **Input and Output Monitoring**: Track all interactions with LLM APIs
- **Content Validation**: Ensure compliance with your usage policies
- **Blocking Mode**: Optionally prevent non-compliant requests or responses
- **Seamless Integration**: Minimal changes to existing code
- **Asynchronous Support**: Works with both synchronous and asynchronous code
- **Multiple Integration Options**: Use guardrails for explicit validation or observers for automatic monitoring

## Troubleshooting

- **Configuration Issues**: Ensure all required parameters or environment variables are correctly set
- **Permission Errors**: Verify your API keys have the necessary permissions
- **Performance Considerations**: In blocking mode, requests will wait for validation, which may add latency


## License

This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.
