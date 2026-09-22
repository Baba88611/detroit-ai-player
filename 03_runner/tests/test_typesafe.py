import copy
import json
from pathlib import Path
import sys

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '03_runner' / 'src'))
from api_client import LLMClient
from runner import build_llm_client_from_model_registry, run_experiment
from campaign_runner import run_campaign


CHOICES = [{'id': 'save', 'text': 'Save the fish'}, {'id': 'leave', 'text': 'Leave it'}]
MESSAGES = [{'role': 'system', 'content': 'You are Connor. Save Emma. No walkthrough knowledge.'},
            {'role': 'user', 'content': 'A fish is on the floor. 1. Save it 2. Leave it'}]


def payload():
    return {'model': 'jev-1.13.0', 'answers': {'action': {
        'type': 'choice', 'choice': '2', 'probabilities': {'1': 0.2, '2': 0.8}, 'confidence': 0.4,
    }}, 'usage': {'input_tokens': 123, 'output_tokens': 20}}


class Response:
    def __init__(self, data=None, status=200):
        self.data = data if data is not None else payload()
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError('sensitive-server-body-and-key')

    def json(self):
        return self.data


def client(base='https://api.typesafe.test'):
    return LLMClient(base_url=base, api_key='test-secret', model='jev-latest', provider='typesafe')


@pytest.mark.parametrize('base', ['https://api.typesafe.test', 'https://api.typesafe.test/v1/'])
def test_request_mapping_and_private_history(monkeypatch, base):
    calls = []
    def post(url, **kwargs):
        calls.append((url, copy.deepcopy(kwargs)))
        return Response()
    monkeypatch.setattr('api_client.requests.post', post)
    ai = client(base)
    result = ai.choose('private_node_id', '', CHOICES, MESSAGES)
    url, kwargs = calls[0]
    assert url == 'https://api.typesafe.test/v1/systemone'
    assert kwargs['headers']['Authorization'] == 'Bearer test-secret'
    body = kwargs['json']
    assert set(body) == {'model', 'state', 'questions'}
    assert body['state']['messages'] == MESSAGES
    assert body['questions']['action']['criteria'] == {'1': 'Save the fish', '2': 'Leave it'}
    assert 'private_node_id' not in json.dumps(body)
    assert result['choice_id'] == 'leave' and result['reasoning'] is None
    assert json.loads(result['raw']) == payload()
    assert json.loads(result['history_content']) == {'choice': 2, 'text': 'Leave it'}
    assert result['decision_metadata']['probabilities'] == {'save': 0.2, 'leave': 0.8}
    assert ai.resolved_model == 'jev-1.13.0'
    assert ai.token_usage() == {'prompt_tokens': 123, 'completion_tokens': 20, 'total_tokens': 143}


@pytest.mark.parametrize('field,value', [
    ('choice', 'unknown'), ('choice', True), ('choice', '1'), ('type', 'noul'),
    ('confidence', True), ('confidence', -0.1), ('confidence', float('nan')),
    ('probabilities', {'1': 0.2}), ('probabilities', {'1': 0.4, '2': 0.8}),
    ('probabilities', {'1': True, '2': 0}), ('probabilities', {'1': -0.2, '2': 1.2}),
    ('probabilities', {'1': 0.2, '2': float('inf')}),
])
def test_invalid_answers_fail_without_fallback_or_retry(monkeypatch, field, value):
    data = payload()
    data['answers']['action'][field] = value
    calls = []
    monkeypatch.setattr('api_client.requests.post', lambda *a, **kw: calls.append(1) or Response(data))
    with pytest.raises(ValueError, match='Invalid TypeSafe response'):
        client().choose('node', '', CHOICES, MESSAGES)
    assert len(calls) == 1


@pytest.mark.parametrize('status,retries', [(401, 1), (422, 1), (429, 3), (529, 3), (503, 3)])
def test_http_retry_policy_and_secret_redaction(monkeypatch, status, retries):
    calls, sleeps = [], []
    monkeypatch.setattr('api_client.requests.post', lambda *a, **kw: calls.append(1) or Response(status=status))
    monkeypatch.setattr('api_client.time.sleep', sleeps.append)
    with pytest.raises(RuntimeError) as error:
        client().choose('node', '', CHOICES, MESSAGES)
    assert len(calls) == retries
    assert sleeps == ([1, 2] if retries == 3 else [])
    assert 'sensitive' not in str(error.value) and 'test-secret' not in str(error.value)


def test_network_retry_then_success(monkeypatch):
    calls = []
    def post(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise requests.Timeout('test-secret')
        return Response()
    monkeypatch.setattr('api_client.requests.post', post)
    monkeypatch.setattr('api_client.time.sleep', lambda _: None)
    assert client().choose('node', '', CHOICES, MESSAGES)['choice_id'] == 'leave'
    assert len(calls) == 2


@pytest.mark.parametrize('data', [None, [], {}, {'answers': None}, {
    **payload(), 'model': None,
}, {**payload(), 'usage': {'input_tokens': True, 'output_tokens': 1}}])
def test_malformed_envelopes_fail_closed(monkeypatch, data):
    response = Response()
    response.data = data
    monkeypatch.setattr('api_client.requests.post', lambda *a, **kw: response)
    with pytest.raises(ValueError, match='Invalid TypeSafe response'):
        client().choose('node', '', CHOICES, MESSAGES)


def test_registry_builds_typesafe_without_llm_environment(monkeypatch):
    for key in ('LLM_MODEL', 'LLM_BASE_URL', 'LLM_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    for key, value in {'TYPESAFE_MODEL': 'jev-1.13.0', 'TYPESAFE_BASE_URL': 'https://api.typesafe.test', 'TYPESAFE_API_KEY': 'test-secret'}.items():
        monkeypatch.setenv(key, value)
    ai = build_llm_client_from_model_registry('jev', ROOT / '02_setting/models.json', 0.7)
    assert ai.provider == 'typesafe' and ai.model == 'jev-1.13.0'
    assert ai.instruction_mode == 'typed_choice'


@pytest.mark.parametrize('language', ['en', 'zh'])
def test_full_campaign_typed_choices_history_events_and_saved_results(monkeypatch, tmp_path, language):
    calls = []
    def post(url, headers, json, timeout):
        body = copy.deepcopy(json)
        calls.append(body)
        criteria = body['questions']['action']['criteria']
        # Dynamic candidate sets must survive transport, including variant nodes.
        chosen = next(iter(criteria))
        data = payload()
        data['answers']['action'].update(choice=chosen, probabilities={k: float(k == chosen) for k in criteria}, confidence=1.0)
        return Response(data)
    monkeypatch.setattr('api_client.requests.post', post)
    ai = client()
    events = []
    result = run_campaign(sorted((ROOT / '01_json' / language).glob('ch*.json')), ai,
                          output_dir=tmp_path, on_event=events.append)
    assert result['status'] == 'complete' and result['progress']['completed'] == 32
    assert result['config']['temperature'] == 'N/A (typesafe)'
    assert result['config']['resolved_model'] == 'jev-1.13.0'
    saved = [json.loads(p.read_text()) for p in tmp_path.glob('ch*.json')]
    assert len(saved) == 32
    decisions = [d for chapter in saved for d in chapter['decisions'] if d['ai_choice_id']]
    assert len(decisions) == len(calls)
    for d in decisions:
        assert d['ai_reasoning'] is None
        assert set(d['decision_metadata']['probabilities']) == {c['id'] for c in d['choices_with_ids']}
        assert json.loads(d['ai_response_raw'])['model'] == 'jev-1.13.0'
    assert len([e for e in events if e['type'] == 'decision' and e['decision_metadata']]) == len(calls)
    assert all(c['questions']['action']['type'] == 'choice' for c in calls)
    assert any('previously' in c['state']['messages'][0]['content'] or '此前' in c['state']['messages'][0]['content'] for c in calls)
    for call in calls:
        text = json.dumps(call, ensure_ascii=False)
        for forbidden in ('success_probability', 'resolution_rule', 'effects', 'state_after', 'ending_resolution', 'test-secret'):
            assert forbidden not in text
        for message in call['state']['messages']:
            if message['role'] == 'assistant':
                assert set(json.loads(message['content'])) == {'choice', 'text'}
    assert len(calls[1]['state']['messages']) > len(calls[0]['state']['messages'])
    assert ai.token_usage()['total_tokens'] == len(calls) * 143
