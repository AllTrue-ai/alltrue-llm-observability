#
#  Copyright 2025 AllTrue.ai Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import json

from fastapi import FastAPI, Request

from .. import TEST_PROMPT_CANARY, TEST_PROMPT_SUBSTITUTION

app = FastAPI()


@app.post("/v1/llm-firewall/chat/check-connection/{proxy_type}")
async def check_connection(request: Request, proxy_type: str):
    print(f"checking connection for {proxy_type}")
    return {"status_code": 200}


def _handle_request_payload(data: dict) -> dict:
    js_body = json.loads(data["original_request_body"])
    print(f"prompt messages: {js_body['messages']}")
    txt = js_body["messages"][-1]["content"]
    print(f"prompt message: {txt}")
    status = 200
    if TEST_PROMPT_CANARY in txt:
        if "reject" in txt:
            js_body = {"Reason": "Rejected"}
            status = 403
        elif "modify" in txt:
            new_txt = txt.replace(
                TEST_PROMPT_CANARY,
                f"{TEST_PROMPT_SUBSTITUTION} {data['endpoint_identifier']}",
            )
            print(f"New prompt content: {new_txt}")
            js_body["messages"][-1]["content"] = new_txt
    return {"processed_input": json.dumps(js_body), "status_code": status}


@app.post("/v1/llm-firewall/chat/process-input/{proxy_type}")
async def chat_request(request: Request, proxy_type: str):
    data = await request.json()
    print(f"chat request for type {proxy_type}: orig: {data}")
    return _handle_request_payload(data)


@app.post("/v1/llm-firewall/chat/batch/process-input/{proxy_type}")
async def chat_batch_request(request: Request, proxy_type: str):
    data = await request.json()
    status = 0
    processed = []
    print(f"processing {len(data['requests'])} input batches")
    for request in data["requests"]:
        result = _handle_request_payload(request)
        processed.append(result["processed_input"])
        status = max(status, result["status_code"])
    return {"processed_inputs": json.dumps(processed), "status_code": status}


def _handle_response_payload(data: dict) -> dict:
    js_body = json.loads(data["original_response_body"])
    txt = js_body["choices"][-1]["message"]["content"]
    status = 200
    if TEST_PROMPT_CANARY in txt:
        if "rewrite-reply" in txt:
            new_txt = txt.replace(TEST_PROMPT_CANARY, TEST_PROMPT_SUBSTITUTION)
            new_txt += f" [{data['endpoint_identifier']}]"
            js_body["choices"][-1]["message"]["content"] = new_txt
        elif "disallow-reply" in txt:
            js_body["choices"][-1]["message"]["content"] = "[REMOVED]"
            status = 403
    return {"processed_output": json.dumps(js_body), "status_code": status}


@app.post("/v1/llm-firewall/chat/process-output/{proxy_type}")
async def chat_response(request: Request, proxy_type: str):
    data = await request.json()
    return _handle_response_payload(data)


@app.post("/v1/llm-firewall/chat/batch/process-output/{proxy_type}")
async def chat_batch_response(request: Request, proxy_type: str):
    data = await request.json()
    status = 0
    processed = []
    print(f"processing {len(data['requests'])} output batches")
    for request in data["requests"]:
        result = _handle_response_payload(request)
        processed.append(result["processed_output"])
        status = max(status, result["status_code"])
    return {"processed_outputs": json.dumps(processed), "status_code": status}


@app.post("/v1/auth/issue-jwt-token")
async def get_jwt_token(request: Request):
    print(
        f"Asked for token via API Key: {(await request.json()).get('api_key', 'unknown')}"
    )
    return {
        "access_token": "random-token",
    }
