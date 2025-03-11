# Alltrue LLM Observability SDK

## Build

```shell
pip install -e.[full]
pytest
python -m build --wheel
```

## Usages

### Guardrails

Guard or observe the input/output messages

- Generic message guardrails

```python
from alltrue.guardrails.chat import ChatGuardrails, GuardrailsException
import httpx
import sys

# init guardrails
guardrails = ChatGuardrails(
    alltrue_api_url="https://api.alltrue-be.com",  # or via envar ALLTRUE_API_URL
    alltrue_api_key="<API_KEY>",                   # or via envar ALLTRUE_API_KEY
    alltrue_customer_id="<CUSTOMER_ID>",           # or via envar ALLTRUE_CUSTOMER_ID
    alltrue_endpoint_identifier="<IDENTIFIER>",    # or via envar ALLTRUE_ENDPOINT_IDENTIFIER
    logging_level="WARNING",
)

messages = ["What day is today?"]

# call guard_input to process the prompt messages
try:
    guarded_input = await guardrails.guard_input(messages)
except GuardrailsException:
    print("Something wrong in the messages")
    sys.exit(1)

# use the guarded prompt messages to call OpenAI API
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

# call guard_output to process the completion messages
try:
    guarded_output = await guardrails.guard_output(
        messages,
        [
            c.get("message", {}).get("content", "")
            for c in api_response.json().get("choices", [])
        ],
    )
except GuardrailsException:
    print("Something wrong from the model")
    sys.exit(1)
```
- Generic message observation

```python
from alltrue.guardrails.chat import ChatGuardrails
import httpx

# init guardrails
guardrails = ChatGuardrails(
    alltrue_api_url="https://api.alltrue-be.com",  # or via envar ALLTRUE_API_URL
    alltrue_api_key="<API_KEY>",                   # or via envar ALLTRUE_API_KEY
    alltrue_customer_id="<CUSTOMER_ID>",           # or via envar ALLTRUE_CUSTOMER_ID
    alltrue_endpoint_identifier="<IDENTIFIER>",    # or via envar ALLTRUE_ENDPOINT_IDENTIFIER
    logging_level="WARNING",
)

messages = ["What day is today?"]

# call observe_input to observe the message
guardrails.observe_input(messages)

# Call OpenAI API
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

# convert response into message list
responses = [
    c.get("message", {}).get("content", "")
    for c in api_response.json().get("choices", [])
]

# call observe_output to observe the response messages
guardrails.observe_output(
    messages,
    responses,
)
```

### Observers

 LLM client specific observers to watch and populate collected info in the background.

 - Observing OpenAI client
```python
from alltrue.observers.openai import OpenAIObserver
from openai import OpenAI

# init observer
observer = OpenAIObserver(
    alltrue_api_url="https://api.alltrue-be.com", # or via envar ALLTRUE_API_URL
    alltrue_api_key="<API_KEY>",                  # or via envar ALLTRUE_API_KEY
    alltrue_customer_id="<CUSTOMER_ID>",          # or via envar ALLTRUE_CUSTOMER_ID
    alltrue_endpoint_identifier="<IDENTIFIER>",   # or via envar ALLTRUE_ENDPOINT_IDENTIFIER
    blocking=False,                               # set to True to block on observed abnormalities (will be call latency overhead)
    logging_level="WARNING",
)
# register observer to client behaviors, since here, client communication will be watched and populated
observer.register()

completion = OpenAI().chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[
        {
            "role": "user",
            "content": "What day is today?",
        }
    ],
)

# finishing observation
observer.unregister()
```
