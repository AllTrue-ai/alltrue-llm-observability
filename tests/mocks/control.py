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
from typing import Optional, cast

from fastapi import FastAPI, Request

from .. import TEST_PROMPT_CANARY, TEST_PROMPT_SUBSTITUTION

app = FastAPI()


@app.post("/v1/llm-firewall/chat/check-connection/{proxy_type}")
async def check_connection(request: Request, proxy_type: str):
    print(f"checking connection for {proxy_type}")
    return {"status_code": 200}


@app.post("/v1/llm-firewall/chat/process-input/{proxy_type}")
async def chat_request(request: Request, proxy_type: str):
    data = await request.json()
    print(f"chat request for type {proxy_type}: orig: {data}")
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


@app.post("/v1/llm-firewall/chat/process-output/{proxy_type}")
async def chat_response(request: Request, proxy_type: str):
    data = await request.json()
    js_body = json.loads(data["original_response_body"])

    txt = js_body["choices"][-1]["message"]["content"]
    print(f"chat response for type: {proxy_type} body: {txt}")
    status = 200
    if TEST_PROMPT_CANARY in txt:
        if "rewrite-reply" in txt:
            new_txt = txt.replace(TEST_PROMPT_CANARY, TEST_PROMPT_SUBSTITUTION)
            new_txt += f' [{data["endpoint_identifier"]}]'
            js_body["choices"][-1]["message"]["content"] = new_txt
        elif "disallow-reply" in txt:
            js_body["choices"][-1]["message"]["content"] = "[REMOVED]"
            status = 403
    return {"processed_output": json.dumps(js_body), "status_code": status}


@app.get("/v1/llm-firewall/combined-settings/{api_provider}")
async def llm_rules(request: Request):
    embedded_headers: Optional[str] = request.headers.get(
        "x-alltrue-llm-api-headers", None
    )
    api_key = cast(dict, json.loads(embedded_headers or "{}")).get(
        "Authorization", None
    )
    if not embedded_headers or not api_key:
        return {"status_code": 400}
    if request.query_params.get("endpoint_identifier", None) == "__no_rule__":
        return {
            "rules": [
                {
                    "rule_type": "ProfanityCheckRule",
                    "settings": {
                        "trigger": {"blacklist": []},
                        "input_action": {
                            "action_type": "LOG",
                            "message": "Warning: AllTrue Prompt Firewall Found Profanity in prompt input.",
                        },
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Warning: AllTrue Prompt Firewall Found Profanity in prompt input.",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                }
            ],
        }
    else:
        return {
            "rules": [
                {
                    "rule_type": "RemoveSubstringRule",
                    "settings": {
                        "trigger": {"substring": "ALLTRUE_TRIGGER_FIREWALL"},
                        "input_action": {
                            "action_type": "MODIFY",
                            "message": "AllTrue AI Prompt Firewall: Substring found in prompt input",
                        },
                        "output_action": {
                            "action_type": "MODIFY",
                            "message": "AllTrue AI Prompt Firewall: Substring found in prompt output",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "ProfanityCheckRule",
                    "settings": {
                        "trigger": {"blacklist": []},
                        "input_action": {
                            "action_type": "LOG",
                            "message": "Warning: AllTrue Prompt Firewall Found Profanity in prompt input.",
                        },
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Warning: AllTrue Prompt Firewall Found Profanity in prompt input.",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "PII",
                    "settings": {
                        "trigger": {
                            "entities": [
                                "UUID",
                                "Address",
                                "Company Name",
                                "Credit Card",
                                "Email",
                                "IPV4 Address",
                                "IPV6 Address",
                                "Name",
                                "Phone Number",
                                "SSN",
                                "SIN",
                                "URL",
                                "US Passport",
                                "US Driver License",
                                "US ITIN",
                                "US Bank Number",
                                "IBAN Code",
                                "Crypto",
                                "Key",
                            ]
                        },
                        "input_action": {
                            "action_type": "LOG",
                            "message": "AllTrue AI Prompt Firewall: PII found in input",
                        },
                        "output_action": {
                            "action_type": "LOG",
                            "message": "AllTrue AI Prompt Firewall: PII found in output",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "PreventJailbreakRule",
                    "settings": {
                        "trigger": {"indicator_phrases": []},
                        "input_action": {
                            "action_type": "LOG",
                            "message": "Alert! Jailbreak attempt detected.",
                        },
                        "output_action": {"action_type": "NOOP"},
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "ClipTokenRule",
                    "settings": {
                        "trigger": {
                            "input_token_limit": 16095,
                            "tiktoken_encoding": None,
                            "tiktoken_encoding_for_model": "gpt-3.5-turbo-0125",
                            "include_context": False,
                        },
                        "input_action": {
                            "action_type": "MODIFY",
                            "input_token_limit": 16095,
                            "clip_from_start": True,
                            "tiktoken_encoding": None,
                            "tiktoken_encoding_for_model": "gpt-3.5-turbo-0125",
                        },
                        "output_action": {"action_type": "NOOP"},
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "XSSProtectionRule",
                    "settings": {
                        "trigger": {},
                        "input_action": {
                            "action_type": "LOG",
                            "message": "Potential cross-site-scripting (XSS) injection detected",
                        },
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Potential cross-site-scripting (XSS) injection detected",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "BooleanValidationRule",
                    "settings": {
                        "trigger": {},
                        "input_action": {"action_type": "NOOP"},
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Not a valid boolean object",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "JSONValidationRule",
                    "settings": {
                        "trigger": {"required_elements": 1},
                        "input_action": {"action_type": "NOOP"},
                        "output_action": {
                            "action_type": "MODIFY",
                            "replacement_type": "REPLACE",
                            "replacement": None,
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "CodeInjectionRule",
                    "settings": {
                        "trigger": {
                            "prohibited_languages": [
                                "ARM Assembly",
                                "C",
                                "C#",
                                "C++",
                                "COBOL",
                                "Erlang",
                                "Fortran",
                                "Go",
                                "Java",
                                "JavaScript",
                                "Kotlin",
                                "Lua",
                                "Mathematica/Wolfram Language",
                                "PHP",
                                "Pascal",
                                "Perl",
                                "PowerShell",
                                "Python",
                                "R",
                                "Ruby",
                                "Rust",
                                "Scala",
                                "Swift",
                                "Visual Basic .NET",
                                "jq",
                            ]
                        },
                        "input_action": {"action_type": "NOOP"},
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Potential code injection detected",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "StringValidationRule",
                    "settings": {
                        "trigger": {"allowed_outputs": []},
                        "input_action": {"action_type": "NOOP"},
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Not allowed string object",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "MessageCountControlRule",
                    "settings": {
                        "trigger": {"number_of_messages": 30},
                        "input_action": {
                            "action_type": "LOG",
                            "message": "The numbers of messages in the prompt is too high. Please reduce the number of messages.",
                        },
                        "output_action": {
                            "action_type": "LOG",
                            "message": "The numbers of messages in the prompt is too high. Please reduce the number of messages.",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "RefutationPreventionRule",
                    "settings": {
                        "trigger": {"additional_refutation_patterns": []},
                        "input_action": {"action_type": "NOOP"},
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Potential refutation detected",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "SQLIRule",
                    "settings": {
                        "trigger": {
                            "catch_injection_auth_bypass_payloads": True,
                            "catch_generic_union_select_payloads": True,
                            "catch_generic_time_based_sql_injection_payloads": True,
                            "catch_generic_error_based_payloads": True,
                        },
                        "input_action": {
                            "action_type": "LOG",
                            "message": "Potential SQL injection detected",
                        },
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Potential SQL injection detected",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "RemoveInvisibleTextRule",
                    "settings": {
                        "trigger": {"triggers": []},
                        "input_action": {
                            "action_type": "LOG",
                            "message": "Warning! Invisible characters detected in the input.",
                        },
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Warning! Invisible characters detected in the output.",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "ProhibitTopics",
                    "settings": {
                        "trigger": {
                            "topics": [
                                "violence",
                                "religion",
                                "politics",
                                "hate",
                                "discrimination",
                                "illegal activity",
                                "sexual content",
                                "finance",
                                "human resources",
                                "contracts",
                                "employment",
                            ]
                        },
                        "input_action": {
                            "action_type": "BLOCK",
                            "message": "AllTrue AI Prompt Firewall: Sensitive topic found in input",
                        },
                        "output_action": {
                            "action_type": "BLOCK",
                            "message": "AllTrue AI Prompt Firewall: Sensitive topic found in output",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "PreventObfuscatedAttackRule",
                    "settings": {
                        "trigger": {"additional_regex": []},
                        "input_action": {
                            "action_type": "LOG",
                            "message": "Warning! Obfuscated input detected.",
                        },
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Warning! Obfuscated output detected.",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "PreventLeakageRule",
                    "settings": {
                        "trigger": {"indicator_phrases": [], "llm_fallback": False},
                        "input_action": {
                            "action_type": "BLOCK",
                            "message": "AllTrue LLM Firewall: Prompt blocked due to leakage attempt.",
                        },
                        "output_action": {
                            "action_type": "BLOCK",
                            "message": "AllTrue LLM Firewall: Prompt blocked due to leakage attempt.",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "PreventEncodedAttacksRule",
                    "settings": {
                        "trigger": {"enable_partial_matching": False},
                        "input_action": {
                            "action_type": "LOG",
                            "message": "Warning! Potential encoded attack detected in the input.",
                        },
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Warning! Potential encoded attack detected in the output.",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "FunctionCallRule",
                    "settings": {
                        "trigger": {
                            "validate_function_call": True,
                            "catch_argument_injection": True,
                            "catch_homoglyphs": True,
                            "catch_binary_strings": True,
                        },
                        "input_action": {"action_type": "NOOP"},
                        "output_action": {
                            "action_type": "LOG",
                            "message": "AllTrue AI Prompt Firewall: Function Calling Warning",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "DetectMaliciousUrlsRule",
                    "settings": {
                        "trigger": {
                            "shortened_url_domains": [],
                            "suspicious_words": [],
                        },
                        "input_action": {
                            "action_type": "LOG",
                            "message": "Warning! Potentially malicious URL found in input.",
                        },
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Warning! Potentially malicious URL found in output.",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
                {
                    "rule_type": "DetectLanguagesRule",
                    "settings": {
                        "trigger": {"supported_languages": ["en"]},
                        "input_action": {
                            "action_type": "LOG",
                            "message": "Warning! Unsupported language detected in input.",
                        },
                        "output_action": {
                            "action_type": "LOG",
                            "message": "Warning! Unsupported language detected in output.",
                        },
                        "issue_generation": {
                            "generate_issues": False,
                            "issue_severity": "MEDIUM",
                        },
                    },
                },
            ]
        }


@app.post("/v1/auth/issue-jwt-token")
async def get_jwt_token(request: Request):
    print(
        f"Asked for token via API Key: {(await request.json()).get('api_key', 'unknown')}"
    )
    return {
        "access_token": "random-token",
    }
