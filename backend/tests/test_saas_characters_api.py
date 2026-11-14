"""Private, persisted user characters without deployment content or provider keys."""
from pathlib import Path

import httpx
import pytest

from eidolon.app import create_app
from eidolon.assembly import build
from eidolon.config import Settings


@pytest.mark.asyncio
async def test_empty_deployment_can_create_private_character_and_resume_it(tmp_path: Path):
    settings = Settings(database_path=tmp_path / 'app.db', dev_login=True)
    backend = build(settings)
    try:
        app = create_app(backend)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Origin': 'http://localhost:3000'}) as client:
            assert (await client.get('/api/characters')).status_code == 401
            login = await client.post('/api/auth/dev-login', json={'name': 'Alice'})
            assert login.status_code == 204, login.text
            await client.post('/api/account/consent', json={'agree_to_terms': True, 'at_least_13': True})
            created = await client.post('/api/characters', json={'name': '向导', 'sheet': '# 人设\n你是山间向导。', 'user_address': '旅人'})
            assert created.status_code == 201, created.text
            character = created.json()
            assert character['language_mode'] == 'single'
            assert character['birthday'] is None
            assert [c['id'] for c in (await client.get('/api/characters')).json()] == [character['id']]
            conversation = await client.post('/api/conversations', json={'character_id': character['id']})
            assert conversation.status_code == 201, conversation.text
            await client.post('/api/auth/logout')
            await client.post('/api/auth/dev-login', json={'name': 'Bob'})
            await client.post('/api/account/consent', json={'agree_to_terms': True, 'at_least_13': True})
            assert (await client.get('/api/characters')).json() == []
            assert (await client.get('/api/characters/' + character['id'])).status_code == 404
            assert (await client.put('/api/characters/' + character['id'], json={'name': '改名', 'sheet': '窃取'})).status_code == 404
            assert (await client.post('/api/conversations', json={'character_id': character['id']})).status_code == 404
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_own_model_streams_plain_reply_and_history_keeps_it(tmp_path: Path):
    import json
    from tests.fakes import FakeLLM, FakeLLMService

    service = FakeLLMService(FakeLLM(['山路', '向左。']))
    backend = build(Settings(database_path=tmp_path / 'plain.db', dev_login=True), own_llm_service=service)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(backend)), base_url='http://test', headers={'Origin': 'http://localhost:3000'}) as client:
            await client.post('/api/auth/dev-login', json={'name': 'Alice'})
            await client.post('/api/account/consent', json={'agree_to_terms': True, 'at_least_13': True})
            character = (await client.post('/api/characters', json={'name': '向导', 'sheet': '你是山间向导。'})).json()
            conversation = (await client.post('/api/conversations', json={'character_id': character['id']})).json()
            reply = await client.post('/api/conversations/' + conversation['id'] + '/turns', json={
                'text': '往哪走？',
                'own_keys': {'llm': {'base_url': 'https://model.example/v1', 'api_key': 'user-only-key', 'model': 'guide'}},
            })
            assert reply.status_code == 200, reply.text
            events = [json.loads(line[6:]) for line in reply.text.splitlines() if line.startswith('data: ')]
            assert not [event for event in events if event['type'] == 'error'], events
            assert ''.join(event['text'] for event in events if event['type'] == 'delta') == '山路向左。'
            assert all(event['lang'] == 'text' for event in events if event['type'] == 'delta')
            messages = (await client.get('/api/conversations/' + conversation['id'] + '/messages')).json()
            assert messages[-1]['text'] == '山路向左。'
            assert 'user-only-key' not in reply.text
    finally:
        await backend.aclose()




@pytest.mark.asyncio
async def test_avatar_is_private_and_only_returns_image(tmp_path, monkeypatch):
    import eidolon.app

    async def fetch(url):
        assert url == 'https://example.com/avatar.png'
        return b'image', 'image/png'

    monkeypatch.setattr(eidolon.app, 'fetch_avatar', fetch)
    backend = build(Settings(database_path=tmp_path / 'avatar.db', dev_login=True))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(backend)), base_url='http://test', headers={'Origin': 'http://localhost:3000'}) as client:
            await client.post('/api/auth/dev-login', json={'name': 'Alice'})
            await client.post('/api/account/consent', json={'agree_to_terms': True, 'at_least_13': True})
            character = (await client.post('/api/characters', json={'name': 'A', 'sheet': 'A'})).json()
            path = '/api/characters/' + character['id'] + '/avatar'
            assert (await client.get(path)).status_code == 404
            await client.put('/api/characters/' + character['id'], json={'name': 'A', 'sheet': 'A', 'avatar_url': 'https://example.com/avatar.png'})
            response = await client.get(path)
            assert response.status_code == 200
            assert response.content == b'image'
            assert response.headers['content-type'] == 'image/png'
            assert response.headers['x-content-type-options'] == 'nosniff'
            assert response.headers['cache-control'] == 'private, max-age=300'
            assert 'set-cookie' not in response.headers
            await client.post('/api/auth/logout')
            await client.post('/api/auth/dev-login', json={'name': 'Bob'})
            await client.post('/api/account/consent', json={'agree_to_terms': True, 'at_least_13': True})
            assert (await client.get(path)).status_code == 404
    finally:
        await backend.aclose()
