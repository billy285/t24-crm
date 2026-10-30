"""Authoritative reply preparation across Google's list/get representations.

Only isolated SQLite and the fake provider/model seams are used. List and GET
payloads are deliberately independent: no version or permission guard is relaxed.
"""
import asyncio
import copy
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from models.customer_access_grants import CustomerAccessGrant
from models.customers import Customers
from models.employees import Employees
from test_google_business import OTHER, SECOND_OWNER, PREFIX, REVIEW, LOCATION, HIDDEN_LOCATION, gbp_env, current_review
from test_google_business_management import management_env, ai_env, protected_snapshot


@pytest_asyncio.fixture
async def split_review_env(ai_env, monkeypatch):
    env = ai_env
    listed = copy.deepcopy(env.fake.review)
    listed['comment'] = 'The service was slow.'
    listed['starRating'] = 'ONE'
    listed['reviewId'] = REVIEW.rsplit('/', 1)[-1]
    listed['reviewReply'] = {'comment': 'We appreciate your feedback.',
        'updateTime': '2026-10-30T10:00:00Z', 'reviewReplyState': 'APPROVED'}
    authoritative = copy.deepcopy(listed)
    authoritative['reviewReply'] = {'comment': listed['reviewReply']['comment'],
        'updateTime': '2026-10-30T10:00:00.987654321Z'}
    env.listed_review = listed
    env.fake.review = authoritative
    original = env.provider.GoogleClient
    class SplitProvider(original):
        async def reviews(self, location, page_token=None):
            env.fake.reads.append(('reviews', location, page_token))
            return {'reviews': [copy.deepcopy(env.listed_review)], 'nextPageToken': None}
    monkeypatch.setattr(env.provider, 'GoogleClient', SplitProvider)
    return env


async def selected_review(env, binding_id=1, review_name=REVIEW):
    return await env.client.get(PREFIX + f'/bindings/{binding_id}/review', params={'review_name': review_name})


def draft_body(env, review):
    return {'confirmed': True, 'request_id': str(uuid4()), 'review_name': review['name'],
        'expected_version': review['version'], 'runtime_fingerprint': env.ai_fingerprint}


@pytest.mark.asyncio
async def test_real_list_get_reply_shape_difference_uses_authoritative_version_without_weakening_it(split_review_env):
    env = split_review_env
    listed = await current_review(env)
    stale = await env.client.post(PREFIX + '/bindings/1/ai-reply-drafts', json=draft_body(env, listed))
    assert stale.status_code == 409 and not env.ai_calls and not env.fake.writes
    response = await selected_review(env)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert set(response.json()) == {'item', 'fetched_at'}
    current = response.json()['item']
    assert current['name'] == listed['name'] and current['comment'] == listed['comment']
    assert current['reply'] == listed['reply']
    assert current['version'] != listed['version']
    assert current['version'] == env.service.review_version(env.fake.review)
    assert current['reply_updated_at'] == '2026-10-30T10:00:00.987654321Z'
    assert current['reply_state'] is None  # Missing moderation is not APPROVED.
    result = await env.client.post(PREFIX + '/bindings/1/ai-reply-drafts', json=draft_body(env, current))
    assert result.status_code == 200, result.text
    assert result.json()['review_version'] == current['version'] and len(env.ai_calls) == 1
    assert not env.fake.writes and await protected_snapshot(env) == env.protected


@pytest.mark.asyncio
async def test_manual_reply_path_also_requires_the_authoritative_get_version(split_review_env):
    env = split_review_env
    listed = await current_review(env)
    stale_body = {'confirmed': True, 'request_id': str(uuid4()), 'review_name': REVIEW,
        'expected_version': listed['version'], 'reply': 'Thank you for your feedback.'}
    stale = await env.client.post(PREFIX + '/bindings/1/reply-drafts', json=stale_body)
    assert stale.status_code == 409 and not env.fake.writes
    response = await selected_review(env)
    current = response.json()['item']
    saved = await env.client.post(PREFIX + '/bindings/1/reply-drafts', json={**stale_body,
        'request_id': str(uuid4()), 'expected_version': current['version']})
    assert saved.status_code == 200, saved.text
    assert saved.json()['review_version'] == current['version']
    assert not env.ai_calls and not env.fake.writes


@pytest.mark.asyncio
async def test_only_fresh_authoritative_snapshot_can_reach_the_public_reply_writer(split_review_env):
    env = split_review_env
    listed = await current_review(env)
    body = {'confirmed': True, 'request_id': str(uuid4()), 'review_name': REVIEW,
        'expected_version': listed['version'], 'reply': 'Thank you for sharing your feedback.'}
    stale = await env.client.post(PREFIX + '/bindings/1/review-replies', json=body)
    assert stale.status_code == 200 and stale.json()['status'] == 'failed'
    assert not env.fake.writes
    current = (await selected_review(env)).json()['item']
    response = await env.client.post(PREFIX + '/bindings/1/review-replies', json={**body,
        'request_id': str(uuid4()), 'expected_version': current['version']})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'succeeded'
    assert env.fake.writes == [('reply', REVIEW, {'comment': body['reply']})]
    assert not env.ai_calls and await protected_snapshot(env) == env.protected


@pytest.mark.asyncio
async def test_authoritative_read_is_not_permission_to_overwrite_a_later_reply(split_review_env):
    env = split_review_env
    current = (await selected_review(env)).json()['item']
    env.fake.review['reviewReply']['comment'] = 'A response saved after the dialog opened.'
    response = await env.client.post(PREFIX + '/bindings/1/review-replies', json={
        'confirmed': True, 'request_id': str(uuid4()), 'review_name': REVIEW,
        'expected_version': current['version'], 'reply': 'Thank you for sharing your feedback.'})
    assert response.status_code == 200 and response.json()['status'] == 'failed'
    assert not env.fake.writes and not env.ai_calls


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['review_updated', 'reply_text', 'reply_time', 'reply_state', 'reply_policy'])
async def test_authoritative_snapshot_changes_still_block_generation_before_model(split_review_env, change):
    env = split_review_env
    row = (await selected_review(env)).json()['item']
    if change == 'review_updated': env.fake.review['updateTime'] = '2026-11-01T01:00:00Z'
    elif change == 'reply_text': env.fake.review['reviewReply']['comment'] = 'A different existing response.'
    elif change == 'reply_time': env.fake.review['reviewReply']['updateTime'] = '2026-10-30T10:00:00.987654322Z'
    elif change == 'reply_state': env.fake.review['reviewReply']['reviewReplyState'] = 'REJECTED'
    else: env.fake.review['reviewReply']['policyViolation'] = 'PERSONAL_INFO'
    response = await env.client.post(PREFIX + '/bindings/1/ai-reply-drafts', json=draft_body(env, row))
    assert response.status_code == 409 and not env.ai_calls and not env.fake.writes


@pytest.mark.asyncio
@pytest.mark.parametrize('name', [HIDDEN_LOCATION + '/reviews/foreign', LOCATION + '/reviews/../escape',
    'https://example.invalid/review', REVIEW + '?query=extra', REVIEW + '%2Fextra'])
async def test_selected_review_cannot_cross_location_or_inject_provider_path(split_review_env, name):
    env = split_review_env
    reads = list(env.fake.reads)
    response = await selected_review(env, review_name=name)
    assert response.status_code == 422
    assert env.fake.reads == reads and not env.ai_calls and not env.fake.writes


@pytest.mark.asyncio
@pytest.mark.parametrize('actor', [OTHER, SECOND_OWNER])
async def test_selected_review_cannot_bypass_owner_or_employee_customer_scope(split_review_env, actor):
    env = split_review_env; env.user = actor
    reads = list(env.fake.reads)
    response = await selected_review(env)
    assert response.status_code in {403, 404}
    assert env.fake.reads == reads and not env.fake.writes


@pytest.mark.asyncio
@pytest.mark.parametrize('raw', [None, {}, {'name': LOCATION + '/reviews/different'}, {'name': HIDDEN_LOCATION + '/reviews/foreign'}])
async def test_google_response_identity_must_match_the_exact_requested_review(split_review_env, raw):
    env = split_review_env
    env.fake.review = raw
    response = await selected_review(env)
    assert response.status_code == 409
    assert 'SECRET-' not in response.text and not env.fake.writes


@pytest.mark.asyncio
async def test_read_only_or_publish_only_grants_cannot_prepare_an_editable_reply(split_review_env):
    env = split_review_env
    async with env.sessions() as db:
        grant = await db.scalar(select(env.Grant).where(env.Grant.binding_id == 1, env.Grant.employee_id == 2))
        grant.can_reply = False; grant.can_publish = True
        await db.commit()
    assert (await env.client.get(PREFIX + '/bindings/1/reviews')).status_code == 200
    reads = list(env.fake.reads)
    response = await selected_review(env)
    assert response.status_code == 403 and env.fake.reads == reads


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['google_reply', 'client_delivery', 'employee', 'customer', 'lifecycle'])
async def test_reply_authorization_is_checked_again_after_slow_provider_read(split_review_env, change):
    env = split_review_env
    env.fake.read_started = asyncio.Event(); env.fake.release_read = asyncio.Event()
    running = asyncio.create_task(selected_review(env))
    try:
        await asyncio.wait_for(env.fake.read_started.wait(), timeout=3)
        async with env.sessions() as db:
            if change == 'google_reply':
                grant = await db.scalar(select(env.Grant).where(env.Grant.binding_id == 1, env.Grant.employee_id == 2))
                grant.can_reply = False; grant.can_publish = True
            elif change == 'client_delivery':
                grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == 10, CustomerAccessGrant.employee_id == 2))
                grant.scopes = {'basic': 'read_only', 'delivery': 'read_only'}
            elif change == 'employee':
                (await db.get(Employees, 2)).status = 'disabled'
            elif change == 'customer':
                (await db.get(Customers, 10)).status = 'paused'
            else:
                (await db.get(env.Binding, 1)).lifecycle = 'paused'
            await db.commit()
    finally:
        env.fake.release_read.set()
    response = await asyncio.wait_for(running, timeout=3)
    assert response.status_code in {403, 404, 409}
    assert 'item' not in response.json() and not env.fake.writes


@pytest.mark.asyncio
async def test_single_review_read_does_not_hold_company_database_writer_or_store_google_source(split_review_env):
    env = split_review_env
    env.fake.read_started = asyncio.Event(); env.fake.release_read = asyncio.Event()
    running = asyncio.create_task(selected_review(env))
    try:
        await asyncio.wait_for(env.fake.read_started.wait(), timeout=3)
        async def financial_canary():
            async with env.sessions() as db:
                await db.execute(text("UPDATE financial_canary SET amount='201.00' WHERE id=1"))
                await db.commit()
        await asyncio.wait_for(financial_canary(), timeout=2)
    finally:
        env.fake.release_read.set()
    response = await asyncio.wait_for(running, timeout=3)
    assert response.status_code == 200, response.text
    async with env.sessions() as db:
        actions = (await db.execute(select(env.Action))).scalars().all()
        drafts = (await db.execute(select(env.ai.Draft))).scalars().all()
        assert actions == [] and drafts == []
        assert (await db.execute(text('SELECT amount FROM financial_canary'))).scalar_one() == '201.00'
    assert not env.fake.writes and not env.ai_calls
