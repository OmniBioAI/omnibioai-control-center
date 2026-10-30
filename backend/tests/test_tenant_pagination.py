"""Local aggregation contract tests. Upstream traffic is entirely mocked."""
import asyncio
import hashlib
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from control_center.api.routes_tenants import router
from control_center.tenants import service

AUTH = 'Bearer pagination-test'
ADMIN = {'sub': '1', 'permissions': ['manage_all_orgs']}
app = FastAPI()
app.include_router(router)


def row(i):
    identity = {'user_id': str(i), 'username': f'user{i:04d}', 'email': f'user{i}@example.test'}
    billing = {'plan_id': 'pro' if i % 2 else 'free', 'effective_plan_id': 'pro' if i % 2 else 'free',
               'plan_source': 'promo' if i % 2 else 'free', 'membership_status': 'active',
               'promo_expires_at': '2099-01-01T00:00:00Z' if i % 2 else None}
    return {**service.tenant_row(identity, billing, {'used_bytes': i}), 'id': i, 'status': 'active',
            'global_roles': [], 'org_count': 0, 'created_at': None}


def seed(rows):
    entry = service.TenantIndex(rows=rows, aggregate=service.summary(rows), updated_at=time.monotonic())
    service._indexes[hashlib.sha256(AUTH.encode()).hexdigest()] = entry
    return entry


@pytest.fixture(autouse=True)
def cleanup():
    service._indexes.clear()
    yield
    service._indexes.clear()


async def sources(client, headers, ids):
    identities = {i: {'user_id': i, 'username': f'user{int(i):04d}', 'email': f'user{i}@example.test'} for i in ids}
    billings = {i: {'plan_id': 'pro' if int(i) % 2 else 'free', 'effective_plan_id': 'pro' if int(i) % 2 else 'free',
                    'membership_status': 'active', 'plan_source': 'promo' if int(i) % 2 else 'free'} for i in ids}
    return identities, billings, {i: {'used_bytes': int(i)} for i in ids}


def test_api_filters_before_pagination_and_only_resolves_page():
    seed([row(i) for i in range(1, 2426)])
    with TestClient(app) as client, patch('control_center.core.auth.verify_token', return_value=ADMIN), patch.object(service, '_sources', AsyncMock(side_effect=sources)) as resolve, patch.object(service, 'all_tenants', AsyncMock()) as full:
        started = time.perf_counter()
        response = client.get('/admin/tenants?plan=pro&plan_source=promo&status=active&storage_status=ok&sort=-used_bytes&page=2&page_size=50', headers={'Authorization': AUTH})
        elapsed = time.perf_counter() - started
        assert response.status_code == 200
        body = response.json()
        assert body['total'] == 1213
        expected = [str(i) for i in range(2325, 2226, -2)]
        assert [item['tenant_id'] for item in body['items']] == expected
        assert resolve.await_args.args[2] == expected
        full.assert_not_awaited()
        assert elapsed < 1.0
        print(f'2425-row warm list, mocked upstream: {elapsed:.4f}s')
        response = client.get('/admin/tenants?q=user2425', headers={'Authorization': AUTH})
        assert response.json()['total'] == 1
        assert response.json()['page_size'] == 50
        for query in ['page=0', 'page_size=201', 'page_size=0', 'organization_id=0']:
            assert client.get('/admin/tenants?' + query, headers={'Authorization': AUTH}).status_code == 422
        assert client.get('/admin/tenants?page=999', headers={'Authorization': AUTH}).json()['items'] == []


def test_api_validity_user_status_and_org_role_semantics():
    rows = [row(1), row(2)]
    rows[0]['days_remaining'] = 3
    rows[1]['status'] = 'suspended'
    seed(rows)
    with TestClient(app) as client, patch('control_center.core.auth.verify_token', return_value=ADMIN), patch.object(service, '_sources', AsyncMock(side_effect=sources)), patch.object(service, '_directory', AsyncMock(return_value=[{'id': 1}])) as directory:
        response = client.get('/admin/tenants?validity=expiring_7d&user_status=active&organization_id=7&role=org_admin', headers={'Authorization': AUTH})
        assert response.json()['total'] == 1
        assert response.json()['items'][0]['tenant_id'] == '1'
        assert directory.await_args.kwargs == {'organization_id': 7, 'role': 'org_admin'}


def test_summary_single_flight_ttl_and_credentials_are_isolated(monkeypatch):
    async def scenario():
        now = [100.0]
        monkeypatch.setattr(service.time, 'monotonic', lambda: now[0])
        full = AsyncMock(return_value=([row(1)], {}, {}))
        monkeypatch.setattr(service, 'all_tenants', full)
        first, second = await asyncio.gather(service.cached_summary(AUTH), service.cached_summary(AUTH))
        assert first == second and first['tenants_total'] == 1
        assert full.await_count == 1
        now[0] = 159.9
        await service.cached_summary(AUTH)
        assert full.await_count == 1
        now[0] = 160.0
        await service.cached_summary(AUTH)
        task = service._index(AUTH).task
        if task:
            await task
        assert full.await_count == 2
        await service.cached_summary('Bearer other-admin')
        assert full.await_count == 3
    asyncio.run(scenario())


def test_cold_list_is_nonblocking_and_starts_one_background_refresh(monkeypatch):
    async def scenario():
        release = asyncio.Event()
        async def full(_):
            await release.wait()
            return [row(1)], {}, {}
        mock = AsyncMock(side_effect=full)
        monkeypatch.setattr(service, 'all_tenants', mock)
        for _ in range(3):
            with pytest.raises(service.UpstreamError, match='warming up'):
                await service.paginated_tenants(AUTH)
        await asyncio.sleep(0)
        assert mock.await_count == 1
        release.set()
        await service._index(AUTH).task
        assert (await service.cached_summary(AUTH))['tenants_total'] == 1
    asyncio.run(scenario())


def test_summary_and_actions_remain_admin_only():
    with TestClient(app) as client, patch('control_center.core.auth.verify_token', return_value={'sub': '2', 'permissions': []}):
        for method, path, body in [('GET', '', None), ('GET', '/summary', None), ('GET', '/1', None),
                                   ('PUT', '/1/storage-override', {'allocated_bytes': 1, 'reason': 'test'}),
                                   ('DELETE', '/1/storage-override', {'reason': 'test'}),
                                   ('POST', '/1/plan-grant', {'plan_id': 'pro', 'days': 1, 'reason': 'test'}),
                                   ('DELETE', '/1/plan-grant', {'reason': 'test'}),
                                   ('POST', '/1/recompute-usage', {'reason': 'test'})]:
            assert client.request(method, '/admin/tenants' + path, json=body, headers={'Authorization': AUTH}).status_code == 403


def test_expired_summary_failure_is_not_reported_as_fresh_and_retries_are_bounded(monkeypatch):
    async def scenario():
        entry = seed([row(1)])
        entry.updated_at = time.monotonic() - 61
        full = AsyncMock(side_effect=service.UpstreamError('billing', 503, 'billing unavailable'))
        monkeypatch.setattr(service, 'all_tenants', full)
        for _ in range(2):
            with pytest.raises(service.UpstreamError, match='billing unavailable'):
                await service.cached_summary(AUTH)
        assert full.await_count == 1
        assert entry.rows is not None  # List can still use the previous index.
    asyncio.run(scenario())


def test_mutation_invalidates_summary_and_refreshed_detail_updates_filter_index(monkeypatch):
    async def scenario():
        entry = seed([row(1)])
        async def fake_json(client, method, url, name, headers, **kwargs):
            if name == 'auth-service':
                return {'items': [{'user_id': '1', 'username': 'user0001', 'email': 'user1@example.test'}]}
            if name == 'billing-service':
                return {'plan_id': 'free', 'effective_plan_id': 'free', 'plan_source': 'free'}
            return {'used_bytes': 0}
        monkeypatch.setattr(service, '_json', fake_json)
        await service.mutate('DELETE', '1', 'plan-grant', {'reason': 'test'}, AUTH, 'billing')
        assert entry.updated_at == 0
        await service.tenant_detail('1', AUTH)
        assert service.filter_sort(entry.rows, plan_source='promo') == []
        assert entry.aggregate['per_plan']['free'] == 1
    asyncio.run(scenario())
