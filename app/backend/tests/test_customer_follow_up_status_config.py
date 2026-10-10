from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from backend.routers import app_config as config


def test_status_validation_rejects_empty_and_duplicate_names():
    for value in ('', 'a:正常,b:正常', 'a:正常,a:待续费', 'a:名称:错误'):
        with pytest.raises(HTTPException) as error:
            config.validate_customer_follow_up_statuses({'customerFollowUpStatuses': value})
        assert error.value.status_code == 422


def test_archive_retains_deleted_status_and_prevents_key_reuse():
    config.validate_customer_follow_up_statuses({'customerFollowUpStatuses': 'b:待续费', 'customerFollowUpStatusArchive': 'a:正常'})
    with pytest.raises(HTTPException):
        config.validate_customer_follow_up_statuses({'customerFollowUpStatuses': 'a:新名称', 'customerFollowUpStatusArchive': 'a:原名称'})


@pytest.mark.asyncio
async def test_non_admin_cannot_change_follow_up_statuses(monkeypatch):
    current = deepcopy(config.DEFAULT_APP_CONFIGS['dict_config'])
    monkeypatch.setattr(config, 'require_tables', AsyncMock())
    monkeypatch.setattr(config, 'read_config_value', AsyncMock(return_value=config.AppConfigValue(key='dict_config', value=current)))
    db = AsyncMock()
    payload = config.AppConfigUpdate(value={**current, 'customerFollowUpStatuses': 'custom:待回复'})
    with pytest.raises(HTTPException) as error:
        await config.update_app_config('dict_config', payload, type('User', (), {'role': 'ops'})(), db)
    assert error.value.status_code == 403
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_older_settings_client_preserves_customer_statuses(monkeypatch):
    current = {**config.DEFAULT_APP_CONFIGS['dict_config'], 'customerFollowUpStatuses': 'custom:待回复'}
    monkeypatch.setattr(config, 'require_tables', AsyncMock())
    monkeypatch.setattr(config, 'read_config_value', AsyncMock(return_value=config.AppConfigValue(key='dict_config', value=current)))
    db = AsyncMock()
    payload = config.AppConfigUpdate(value={'industries': 'other:其他'})
    await config.update_app_config('dict_config', payload, type('User', (), {'role': 'ops'})(), db)
    assert payload.value['customerFollowUpStatuses'] == 'custom:待回复'
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_can_archive_status(monkeypatch):
    current = deepcopy(config.DEFAULT_APP_CONFIGS['dict_config'])
    monkeypatch.setattr(config, 'require_tables', AsyncMock())
    monkeypatch.setattr(config, 'read_config_value', AsyncMock(return_value=config.AppConfigValue(key='dict_config', value=current)))
    db = AsyncMock()
    payload = config.AppConfigUpdate(value={**current, 'customerFollowUpStatuses': 'b:待续费', 'customerFollowUpStatusArchive': 'a:正常服务中'})
    await config.update_app_config('dict_config', payload, type('User', (), {'role': 'admin'})(), db)
    db.execute.assert_awaited_once()
