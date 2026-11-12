"""The OpenAI Responses and Anthropic Messages adapters, against streams recorded from a real
service (deepseek-v4.1-flash, which also streams its reasoning: the adapters keep it out of
what she says, and send it back with the calls it made)."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from eidolon.llm import ChatLLM, ChatMessage, LLMError, Reasoning, Tool, ToolCall
from eidolon.llm.anthropic import AnthropicLLM
from eidolon.llm.openai_compat import OpenAICompatLLM
from eidolon.llm.responses import ResponsesLLM
from eidolon.reply_format import ReplyParser, Segment

RECORDINGS = Path(__file__).parent / "recordings"

RECALL = Tool(
    "recall_story",
    "回顾剧情",
    {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
)

Adapter = Callable[[httpx.AsyncClient], ChatLLM]
ADAPTERS: dict[str, Adapter] = {
    "responses": lambda client: ResponsesLLM(
        "https://llm.example/v1/", "sk-test", "some-model", client=client
    ),
    "anthropic": lambda client: AnthropicLLM(
        "https://llm.example/v1/", "sk-test", "some-model", client=client
    ),
}


def recorded(name: str) -> str:
    return (RECORDINGS / f"{name}.sse").read_text(encoding="utf-8")


def serving(
    body: str | Callable[[httpx.Request], httpx.Response], requests: list[httpx.Request]
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if callable(body):
            return body(request)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def collect(llm: ChatLLM, messages: list[ChatMessage], tools: list[Tool] = []) -> list:
    return [item async for item in llm.stream(messages, tools)]


@pytest.mark.parametrize("protocol", ADAPTERS)
async def test_the_structured_reply_streams_through_leaving_the_reasoning_out(protocol: str):
    llm = ADAPTERS[protocol](serving(recorded(f"{protocol}_text"), []))

    streamed = await collect(llm, [ChatMessage("user", "你好")])

    # What the model thought streams apart, never as part of what she says.
    items = [i for i in streamed if not isinstance(i, Reasoning)]
    assert all(isinstance(i, str) for i in items)
    assert len(items) > 3  # streamed in pieces, not all at once
    parser = ReplyParser(bilingual=True)
    for item in items:
        parser.feed(item)
    parser.finish()
    expected = {
        "responses": [
            Segment("こんにちは。", "你好。"),
            Segment("今日はどのようにお手伝いしましょうか。", "今天我能怎么帮你？"),
        ],
        "anthropic": [Segment("こんにちは。", "你好。")],
    }
    assert parser.segments == expected[protocol]


@pytest.mark.parametrize("protocol", ADAPTERS)
async def test_a_recorded_tool_call_is_assembled(protocol: str):
    llm = ADAPTERS[protocol](serving(recorded(f"{protocol}_tool"), []))

    items = await collect(llm, [ChatMessage("user", "那次拍写真集")], [RECALL])

    call_ids = {
        "responses": "call_00_AB1TVlVKx4vdJplfOG716557",
        "anthropic": "call_00_T2lkblEVfvBy77TaH2jI2468",
    }
    assert [i for i in items if not isinstance(i, Reasoning)] == [
        ToolCall(call_ids[protocol], "recall_story", {"query": "拍写真集"})
    ]


PROMPT = [
    ChatMessage("system", "你是櫻木真乃。"),
    ChatMessage("user", "你好"),
    ChatMessage("assistant", "<ja>ほわっ</ja><zh>哇</zh>"),
    ChatMessage("user", "那次拍写真集"),
    ChatMessage(
        "assistant",
        "我查一下",
        tool_calls=(
            ToolCall("call_a", "recall_story", {"query": "写真集"}),
            ToolCall("call_b", "recall_story", None),
        ),
    ),
    ChatMessage("tool", "## 剧情……", tool_call_id="call_a"),
    ChatMessage("tool", "调用参数有误", tool_call_id="call_b"),
]


async def test_responses_request_carries_the_prompt_tools_and_tool_round_trip():
    requests: list[httpx.Request] = []
    llm = ADAPTERS["responses"](serving(recorded("responses_text"), requests))

    await collect(llm, PROMPT, [RECALL])

    (request,) = requests
    assert str(request.url) == "https://llm.example/v1/responses"
    assert request.headers["authorization"] == "Bearer sk-test"
    assert json.loads(request.content) == {
        "model": "some-model",
        "stream": True,
        "store": False,
        "instructions": "你是櫻木真乃。",
        "input": [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "<ja>ほわっ</ja><zh>哇</zh>"},
            {"role": "user", "content": "那次拍写真集"},
            {"role": "assistant", "content": "我查一下"},
            {
                "type": "function_call",
                "call_id": "call_a",
                "name": "recall_story",
                "arguments": '{"query": "写真集"}',
            },
            {
                "type": "function_call",
                "call_id": "call_b",
                "name": "recall_story",
                "arguments": "{}",
            },
            {"type": "function_call_output", "call_id": "call_a", "output": "## 剧情……"},
            {"type": "function_call_output", "call_id": "call_b", "output": "调用参数有误"},
        ],
        "tools": [
            {
                "type": "function",
                "name": "recall_story",
                "description": "回顾剧情",
                "parameters": RECALL.parameters,
            }
        ],
    }


async def test_anthropic_request_carries_the_prompt_tools_and_tool_round_trip():
    requests: list[httpx.Request] = []
    llm = ADAPTERS["anthropic"](serving(recorded("anthropic_text"), requests))

    await collect(llm, PROMPT, [RECALL])

    (request,) = requests
    assert str(request.url) == "https://llm.example/v1/messages"
    assert request.headers["x-api-key"] == "sk-test"
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(request.content)
    assert body == {
        "model": "some-model",
        "stream": True,
        "max_tokens": body["max_tokens"],
        "system": "你是櫻木真乃。",
        "messages": [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "<ja>ほわっ</ja><zh>哇</zh>"},
            {"role": "user", "content": "那次拍写真集"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "我查一下"},
                    {
                        "type": "tool_use",
                        "id": "call_a",
                        "name": "recall_story",
                        "input": {"query": "写真集"},
                    },
                    {"type": "tool_use", "id": "call_b", "name": "recall_story", "input": {}},
                ],
            },
            {  # results of one round go back together, in one user message
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "call_a", "content": "## 剧情……"},
                    {"type": "tool_result", "tool_use_id": "call_b", "content": "调用参数有误"},
                ],
            },
        ],
        "tools": [
            {"name": "recall_story", "description": "回顾剧情", "input_schema": RECALL.parameters}
        ],
    }
    assert body["max_tokens"] >= 4096  # Anthropic requires one; long drafts need room


async def test_anthropic_max_tokens_can_be_configured():
    requests: list[httpx.Request] = []
    llm = AnthropicLLM(
        "https://llm.example/v1", "sk-test", "some-model",
        client=serving(recorded("anthropic_text"), requests), max_tokens=2000,
    )

    await collect(llm, [ChatMessage("user", "你好")])

    assert json.loads(requests[0].content)["max_tokens"] == 2000


async def test_anthropic_system_messages_are_joined_and_an_empty_assistant_text_is_left_out():
    requests: list[httpx.Request] = []
    llm = ADAPTERS["anthropic"](serving(recorded("anthropic_text"), requests))

    await collect(
        llm,
        [
            ChatMessage("system", "甲"),
            ChatMessage("system", "乙"),
            ChatMessage("user", "你好"),
            ChatMessage("assistant", ""),
            ChatMessage("user", "在吗"),
            ChatMessage("assistant", "", tool_calls=(ToolCall("c", "recall_story", {}),)),
            ChatMessage("tool", "结果", tool_call_id="c"),
        ],
        [RECALL],
    )

    body = json.loads(requests[0].content)
    assert body["system"] == "甲\n\n乙"
    assert body["messages"][:3] == [
        {"role": "user", "content": "你好"},
        {"role": "user", "content": "在吗"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "c", "name": "recall_story", "input": {}}],
        },
    ]


SHARED_THEN_THE_REST = [
    ChatMessage("system", "甲", cache_breakpoint=True),
    ChatMessage("system", "乙"),
    ChatMessage("user", "你好"),
]
"""A prompt opening with a part every user's requests share, marked for caching, then the
rest of what the model is told."""


async def test_anthropic_caches_the_system_up_to_the_end_of_the_part_marked_for_it():
    requests: list[httpx.Request] = []
    llm = ADAPTERS["anthropic"](serving(recorded("anthropic_text"), requests))

    await collect(llm, SHARED_THEN_THE_REST)

    body = json.loads(requests[0].content)
    assert body["system"] == [
        {"type": "text", "text": "甲", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "乙"},
    ]
    # Not the top-level one, which few other services speaking the protocol say they take.
    assert "cache_control" not in body
    assert body["messages"] == [{"role": "user", "content": "你好"}]


CONTEXT_AFTER_THE_HISTORY = [
    ChatMessage("system", "甲", cache_breakpoint=True),
    ChatMessage("system", "乙"),
    ChatMessage("user", "你好"),
    ChatMessage("assistant", "<ja>ほわっ</ja><zh>哇</zh>", cache_breakpoint=True),
    ChatMessage("system", "丙"),
    ChatMessage("user", "在吗"),
]
"""A prompt as a turn's: what opens it, the history, marked for caching up to its end, then
what changes from turn to turn in a system message before what the user is saying now."""


async def test_responses_instructions_are_the_opening_system_messages_and_a_later_one_is_input():
    requests: list[httpx.Request] = []
    llm = ADAPTERS["responses"](serving(recorded("responses_text"), requests))

    await collect(llm, CONTEXT_AFTER_THE_HISTORY)

    body = json.loads(requests[0].content)
    assert body["instructions"] == "甲\n\n乙"
    assert body["input"] == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "<ja>ほわっ</ja><zh>哇</zh>"},
        {"role": "system", "content": "丙"},
        {"role": "user", "content": "在吗"},
    ]


async def test_anthropic_sends_a_later_system_message_as_the_user_turn_s_first_block():
    requests: list[httpx.Request] = []
    llm = ADAPTERS["anthropic"](serving(recorded("anthropic_text"), requests))

    await collect(llm, CONTEXT_AFTER_THE_HISTORY)

    body = json.loads(requests[0].content)
    assert body["system"] == [
        {"type": "text", "text": "甲", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "乙"},
    ]
    assert body["messages"] == [
        {"role": "user", "content": "你好"},
        {  # the second place cached up to, for the next turn to carry on from
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "<ja>ほわっ</ja><zh>哇</zh>",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": "丙"}, {"type": "text", "text": "在吗"}],
        },
    ]


async def test_anthropic_caches_up_to_the_last_block_of_a_message_with_tool_calls():
    requests: list[httpx.Request] = []
    llm = ADAPTERS["anthropic"](serving(recorded("anthropic_text"), requests))
    call = ToolCall("c", "recall_story", {"query": "写真集"})

    await collect(llm, [
        ChatMessage("user", "那次拍写真集"),
        ChatMessage("assistant", "我想想", (call,), cache_breakpoint=True),
        ChatMessage("tool", "## 剧情……", tool_call_id="c"),
    ], [RECALL])

    body = json.loads(requests[0].content)
    assert body["messages"][1]["content"] == [
        {"type": "text", "text": "我想想"},
        {
            "type": "tool_use", "id": "c", "name": "recall_story", "input": {"query": "写真集"},
            "cache_control": {"type": "ephemeral"},
        },
    ]


@pytest.mark.parametrize("protocol", ADAPTERS)
async def test_error_status_is_raised_with_the_provider_message(protocol: str):
    llm = ADAPTERS[protocol](
        serving(lambda _: httpx.Response(401, json={"error": {"message": "invalid api key"}}), [])
    )

    with pytest.raises(LLMError, match="401.*invalid api key"):
        await collect(llm, [ChatMessage("user", "你好")])


ERROR_IN_STREAM = {
    "responses": (
        'event: response.output_text.delta\n'
        'data: {"type":"response.output_text.delta","delta":"<ja>ほわ"}\n\n'
        'event: error\n'
        'data: {"type":"error","code":"server_error","message":"upstream overloaded"}\n\n'
    ),
    "anthropic": (
        'event: content_block_delta\n'
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"<ja>ほわ"}}\n\n'
        'event: error\n'
        'data: {"type":"error","error":{"type":"overloaded_error",'
        '"message":"upstream overloaded"}}\n\n'
    ),
}


@pytest.mark.parametrize("protocol", ADAPTERS)
async def test_error_sent_inside_the_stream_is_raised(protocol: str):
    llm = ADAPTERS[protocol](serving(ERROR_IN_STREAM[protocol], []))

    with pytest.raises(LLMError, match="upstream overloaded"):
        await collect(llm, [ChatMessage("user", "你好")])


async def test_a_failed_response_is_raised():
    stream = (
        'event: response.failed\n'
        'data: {"type":"response.failed","response":{"status":"failed",'
        '"error":{"code":"server_error","message":"the model crashed"}}}\n\n'
    )
    llm = ADAPTERS["responses"](serving(stream, []))

    with pytest.raises(LLMError, match="the model crashed"):
        await collect(llm, [ChatMessage("user", "你好")])


NOT_STREAMED = {
    "responses": {"id": "r1", "object": "response", "output": []},
    "anthropic": {"id": "m1", "type": "message", "content": [{"type": "text", "text": "hi"}]},
}


@pytest.mark.parametrize("protocol", ADAPTERS)
async def test_a_reply_that_is_not_streamed_is_an_error(protocol: str):
    llm = ADAPTERS[protocol](
        serving(lambda _: httpx.Response(200, json=NOT_STREAMED[protocol]), [])
    )

    with pytest.raises(LLMError, match="流式"):
        await collect(llm, [ChatMessage("user", "你好")])


@pytest.mark.parametrize("protocol", ADAPTERS)
async def test_tool_call_arguments_that_are_not_json_are_passed_on_as_malformed(protocol: str):
    stream = {
        "responses": (
            'data: {"type":"response.output_item.added","output_index":0,"item":'
            '{"type":"function_call","call_id":"call_x","name":"recall_story","arguments":""}}\n\n'
            'data: {"type":"response.function_call_arguments.delta","output_index":0,'
            '"delta":"{\\"query\\": "}\n\n'
            'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        ),
        "anthropic": (
            'data: {"type":"content_block_start","index":0,"content_block":'
            '{"type":"tool_use","id":"call_x","name":"recall_story","input":{}}}\n\n'
            'data: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"input_json_delta","partial_json":"{\\"query\\": "}}\n\n'
            'data: {"type":"message_stop"}\n\n'
        ),
    }[protocol]
    llm = ADAPTERS[protocol](serving(stream, []))

    items = await collect(llm, [ChatMessage("user", "你好")], [RECALL])

    assert items == [ToolCall("call_x", "recall_story", None)]


FORBIDDING: dict[str, tuple[Adapter, str, object]] = {
    # protocol: the adapter, a stream it can read, and how it says no tool may be called
    "chat-completions": (
        lambda client: OpenAICompatLLM("https://llm.example/v1/", "sk-test", "m", client=client),
        'data: {"choices":[{"delta":{"content":"はい"}}]}\n\n',
        "none",
    ),
    "responses": (ADAPTERS["responses"], recorded("responses_text"), "none"),
    "anthropic": (ADAPTERS["anthropic"], recorded("anthropic_text"), {"type": "none"}),
}


@pytest.mark.parametrize("protocol", FORBIDDING)
async def test_forbidding_calls_still_offers_the_tools(protocol: str):
    adapter, stream, choice = FORBIDDING[protocol]
    requests: list[httpx.Request] = []
    llm = adapter(serving(stream, requests))

    [_ async for _ in llm.stream(PROMPT, [RECALL], forbid_calls=True)]
    await collect(llm, PROMPT, [RECALL])
    [_ async for _ in llm.stream(PROMPT, [], forbid_calls=True)]

    forbidden, allowed, without_tools = [json.loads(r.content) for r in requests]
    assert [t.get("name") or t["function"]["name"] for t in forbidden["tools"]] == [
        "recall_story"
    ]
    assert forbidden["tools"] == allowed["tools"]
    assert forbidden["tool_choice"] == choice
    assert "tool_choice" not in allowed
    # A request offering no tools says nothing of calling them.
    assert "tools" not in without_tools and "tool_choice" not in without_tools


async def tool_round(protocol: str, first_stream: str) -> tuple[list, dict]:
    """The items `first_stream` streams, and the request body sent after them: the calls
    they made, with all the model sent alongside them, and their results."""
    replies = iter([first_stream, recorded(f"{protocol}_text")])
    requests: list[httpx.Request] = []
    llm = ADAPTERS[protocol](serving(lambda _: httpx.Response(200, text=next(replies)), requests))
    prompt = [ChatMessage("user", "公园那次呢？")]

    items = await collect(llm, prompt, [RECALL])
    calls = tuple(i for i in items if isinstance(i, ToolCall))
    said = "".join(i for i in items if isinstance(i, str))
    thought = tuple(i for i in items if isinstance(i, Reasoning))
    results = [ChatMessage("tool", "## 剧情……", tool_call_id=c.id) for c in calls]
    [_ async for _ in llm.stream(
        [*prompt, ChatMessage("assistant", said, calls, reasoning=thought), *results],
        [RECALL], forbid_calls=True,
    )]

    return items, json.loads(requests[-1].content)


async def test_anthropic_thinking_goes_back_as_streamed_ahead_of_the_text_and_calls():
    # Written after the documented stream: a signed thinking block, a redacted one, then
    # the text and the call.
    items, body = await tool_round("anthropic", recorded("anthropic_thinking_tool"))

    # What the model thought is never part of what she says.
    assert "".join(i for i in items if isinstance(i, str)) == "我想想"
    assert body["messages"][1] == {
        "role": "assistant",
        "content": [
            {
                "type": "thinking",
                "thinking": "制作人问的是公园那次。",
                "signature": "EqQBCgIYAhIM1gbcDa9GJwZA2b3hGgxBdjrkzLoky3dl1pkiMOYds",
            },
            {
                "type": "redacted_thinking",
                "data": "EmwKAhgBEgy3va3pzix/LafPsn4aDFIT2Xlxh0L5L8rLVyIwxtE3rAFBa8cr3qpP",
            },
            {"type": "text", "text": "我想想"},
            {
                "type": "tool_use",
                "id": "toolu_01A09q90qw90lq917835lq9",
                "name": "recall_story",
                "input": {"query": "公园"},
            },
        ],
    }


async def test_responses_reasoning_goes_back_as_completed_ahead_of_the_call():
    _, body = await tool_round("responses", recorded("responses_reasoning_tool"))

    assert body["store"] is False
    assert body["input"] == [
        {"role": "user", "content": "公园那次呢？"},
        {  # as the item was done: what was added at first may be cut short
            "id": "rs_01ReasoningToolRound",
            "type": "reasoning",
            "summary": [],
            "encrypted_content": (
                "gAAAAABoISQ24OyVRYbkYfukuVdmBr9rKfMQSkM04XZa0LBTyRhOxyAfLdNk1vI3AMJ5dGlqaHuMr5Mh"
            ),
        },
        {
            "type": "function_call",
            "call_id": "call_Ab12Cd34",
            "name": "recall_story",
            "arguments": '{"query": "公园"}',
        },
        {"type": "function_call_output", "call_id": "call_Ab12Cd34", "output": "## 剧情……"},
    ]


async def test_thinking_a_service_sent_without_a_signature_goes_back_as_it_came():
    # Recorded from DeepSeek, which signs nothing yet wants its thinking back.
    _, anthropic = await tool_round("anthropic", recorded("anthropic_tool"))
    _, responses = await tool_round("responses", recorded("responses_tool"))

    assert anthropic["messages"][1]["content"][0] == {"type": "thinking", "thinking": "The user is"}
    reasoning = responses["input"][1]
    assert reasoning["type"] == "reasoning"
    assert reasoning["encrypted_content"] == ""
    assert reasoning["summary"][0]["text"].startswith("The user wants me to use")
