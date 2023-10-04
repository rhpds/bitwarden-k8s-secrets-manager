import asyncio
import kopf
import logging
import os
import yaml

from datetime import datetime, timedelta, timezone

import kubernetes_asyncio

from configure_kopf_logging import configure_kopf_logging
from infinite_relative_backoff import InfiniteRelativeBackoff
from bitwardensyncconfig import BitwardenSyncConfig

from k8sutil import K8sUtil

@kopf.on.startup()
async def startup(settings: kopf.OperatorSettings, **_):
    # Never give up from network errors
    settings.networking.error_backoffs = InfiniteRelativeBackoff()

    # Store last handled configuration in status
    settings.persistence.diffbase_storage = kopf.StatusDiffBaseStorage(field='status.diffBase')

    # Use operator domain as finalizer
    settings.persistence.finalizer = K8sUtil.operator_domain

    # Store progress in status. Some objects may be too large to store status in metadata annotations
    settings.persistence.progress_storage = kopf.StatusProgressStorage(field='status.kopf.progress')

    # Only create events for warnings and errors
    settings.posting.level = logging.WARNING

    # Disable scanning for CustomResourceDefinitions updates
    settings.scanning.disabled = True

    # Configure logging
    configure_kopf_logging()

    await K8sUtil.on_startup()


@kopf.on.create(BitwardenSyncConfig.api_group, BitwardenSyncConfig.api_version, BitwardenSyncConfig.plural)
async def bitwarden_sync_config_create(**kwargs):
    await BitwardenSyncConfig.on_create(**kwargs)

@kopf.on.delete(BitwardenSyncConfig.api_group, BitwardenSyncConfig.api_version, BitwardenSyncConfig.plural)
async def bitwarden_sync_config_create(**kwargs):
    await BitwardenSyncConfig.on_delete(**kwargs)

@kopf.on.resume(BitwardenSyncConfig.api_group, BitwardenSyncConfig.api_version, BitwardenSyncConfig.plural)
async def bitwarden_sync_config_resume(**kwargs):
    await BitwardenSyncConfig.on_resume(**kwargs)

@kopf.on.update(BitwardenSyncConfig.api_group, BitwardenSyncConfig.api_version, BitwardenSyncConfig.plural)
async def bitwarden_sync_config_update(**kwargs):
    await BitwardenSyncConfig.on_update(**kwargs)

@kopf.daemon(BitwardenSyncConfig.api_group, BitwardenSyncConfig.api_version, BitwardenSyncConfig.plural, cancellation_timeout=1)
async def bitwarden_sync_config_daemon(logger, stopped, **kwargs):
    config = BitwardenSyncConfig.register(**kwargs)
    try:
        while not stopped:
            await asyncio.sleep(config.sync_interval)
            await config.sync_secrets(logger=logger)
    except asyncio.CancelledError:
        pass
