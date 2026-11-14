"""Character document HTTP API with the user's vector service."""

from dataclasses import replace

from tests.fakes import FakeLLM


def body(model="first"):
    return {"origin": "笔记", "text": "公園的猫", "own_keys": {"embedding": {
        "base_url": "https://openrouter.ai/api/v1", "api_key": "secret-key", "model": model,
        "dimensions": 4,
    }}}


async def test_document_api(make_client, own_vectors, settings, database_target):
    client = make_client(FakeLLM(), settings=replace(settings, database_path=database_target),
                         own_retrieval_service=own_vectors)
    url = "/api/characters/mano/documents"
    assert (await client.post(url, json={"origin": "笔记", "text": "猫"})).status_code == 400
    assert (await client.post("/api/characters/missing/documents", json=body())).status_code == 404
    assert (await client.post(url, json=body() | {"extra": 1})).status_code == 422
    response = await client.post(url, json=body())
    assert response.status_code == 201, response.text
    document_id = response.json()["id"]
    assert (await client.post(url, json=body("second"))).json() == {"id": document_id}
    listed = (await client.get(url)).json()
    assert len(listed) == 1
    assert listed[0]["origin"] == "笔记"
    assert listed[0]["created_at"]
    assert listed[0]["passage_count"] == listed[0]["embedded_passage_count"] == 1
    assert (await client.delete(f"{url}/{document_id}")).status_code == 204
    assert (await client.delete(f"{url}/{document_id}")).status_code == 404
    assert (await client.get(url)).json() == []

async def test_failed_embedding_leaves_text_for_retry(make_client):
    import httpx

    from eidolon.own_keys import OwnRetrievalService

    import json

    available = False

    def respond(request):
        if not available:
            return httpx.Response(400, json={"error": "unavailable"})
        inputs = json.loads(request.content)["input"]
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": [1.0, 0.0, 0.0, 0.0]} for i, _ in enumerate(inputs)
        ]})

    failing = OwnRetrievalService(public_only=False, transport=httpx.MockTransport(respond))
    try:
        client = make_client(FakeLLM(), own_retrieval_service=failing)
        url = "/api/characters/mano/documents"
        response = await client.post(url, json=body())
        assert response.status_code == 502
        listed = (await client.get(url)).json()
        assert listed[0]["embedded_passage_count"] == 0
        # Retry against the same database with a working service.
        available = True
        response = await client.post(url, json=body())
        assert response.status_code == 201
        assert response.json()["id"] == listed[0]["id"]
        assert (await client.get(url)).json()[0]["embedded_passage_count"] == 1
    finally:
        await failing.aclose()

async def test_other_users_character_is_not_accessible(make_client, own_vectors):
    alice = make_client(FakeLLM(), own_retrieval_service=own_vectors)
    bob = make_client(FakeLLM(), user="bob", own_retrieval_service=own_vectors)
    character = (await alice.post("/api/characters", json={"name": "A", "sheet": "A"})).json()
    url = f"/api/characters/{character['id']}/documents"
    document = (await alice.post(url, json=body())).json()
    assert (await bob.get(url)).status_code == 404
    assert (await bob.post(url, json=body())).status_code == 404
    assert (await bob.delete(f"{url}/{document['id']}")).status_code == 404
    assert len((await alice.get(url)).json()) == 1


async def test_document_input_limits(make_client):
    client = make_client(FakeLLM())
    url = "/api/characters/mano/documents"
    assert (await client.post(url, json=body() | {"text": " "})).status_code == 422
    assert (await client.post(url, json=body() | {"text": "x" * 1000001})).status_code == 422
    assert (await client.post(url, json=body() | {"origin": "x" * 501})).status_code == 422
