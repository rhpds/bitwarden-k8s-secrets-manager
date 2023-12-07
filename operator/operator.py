"""
Kopf operator module.
"""

import asyncio
import logging

import kopf

from configure_kopf_logging import configure_kopf_logging
from infinite_relative_backoff import InfiniteRelativeBackoff
from bitwardensyncconfig import BitwardenSyncConfig
from bitwardensyncsecret import BitwardenSyncSecret
from k8sutil import K8sUtil

@kopf.on.startup()
async def startup(settings: kopf.OperatorSettings, **_):
    """
    Initialize on startup.
    """
    # Never give up from network errors
    settings.networking.error_backoffs = InfiniteRelativeBackoff()

    # Store last handled configuration in status
    settings.persistence.diffbase_storage = kopf.StatusDiffBaseStorage(field='status.diffBase')

    # Use operator domain as finalizer
    settings.persistence.finalizer = K8sUtil.operator_domain

    # Store progress in status.
    settings.persistence.progress_storage = kopf.StatusProgressStorage(field='status.kopf.progress')

    # Only create events for warnings and errors
    settings.posting.level = logging.WARNING

    # Disable scanning for CustomResourceDefinitions updates
    settings.scanning.disabled = True

    # Configure logging
    configure_kopf_logging()

    await K8sUtil.on_startup()

@kopf.on.cleanup()
async def cleanup(**_):
    """
    Gracefully shutdown on cleanup
    """
    await K8sUtil.on_cleanup()

@kopf.on.create(
    BitwardenSyncConfig.api_group, BitwardenSyncConfig.api_version, BitwardenSyncConfig.plural,
)
async def bitwarden_sync_config_create(**kwargs):
    """
    Handle creation of BitwardenSyncConfig
    """
    await BitwardenSyncConfig.on_create(**kwargs)

@kopf.on.delete(
    BitwardenSyncConfig.api_group, BitwardenSyncConfig.api_version, BitwardenSyncConfig.plural,
)
async def bitwarden_sync_config_delete(**kwargs):
    """
    Handle delete of BitwardenSyncConfig
    """
    await BitwardenSyncConfig.on_delete(**kwargs)

@kopf.on.resume(
    BitwardenSyncConfig.api_group, BitwardenSyncConfig.api_version, BitwardenSyncConfig.plural,
)
async def bitwarden_sync_config_resume(**kwargs):
    """
    Handle resume of BitwardenSyncConfig
    """
    await BitwardenSyncConfig.on_resume(**kwargs)

@kopf.on.update(
    BitwardenSyncConfig.api_group, BitwardenSyncConfig.api_version, BitwardenSyncConfig.plural,
)
async def bitwarden_sync_config_update(**kwargs):
    """
    Handle update of BitwardenSyncConfig
    """
    await BitwardenSyncConfig.on_update(**kwargs)

@kopf.daemon(
    BitwardenSyncConfig.api_group, BitwardenSyncConfig.api_version, BitwardenSyncConfig.plural,
    cancellation_timeout=1,
)
async def bitwarden_sync_config_daemon(logger, stopped, **kwargs):
    """
    BitwardenSyncConfig sync daemon
    """
    config = BitwardenSyncConfig.register(**kwargs)
    try:
        while not stopped:
            await asyncio.sleep(config.sync_interval)
            await config.sync_secrets(logger=logger)
    except asyncio.CancelledError:
        pass

@kopf.on.create(
    BitwardenSyncSecret.api_group, BitwardenSyncSecret.api_version, BitwardenSyncSecret.plural,
)
async def bitwarden_sync_secret_create(**kwargs):
    """
    Handle creation of BitwardenSyncSecret
    """
    await BitwardenSyncSecret.on_create(**kwargs)

@kopf.on.delete(
    BitwardenSyncSecret.api_group, BitwardenSyncSecret.api_version, BitwardenSyncSecret.plural,
)
async def bitwarden_sync_secret_delete(**kwargs):
    """
    Handle delete of BitwardenSyncSecret
    """
    await BitwardenSyncSecret.on_delete(**kwargs)

@kopf.on.resume(
    BitwardenSyncSecret.api_group, BitwardenSyncSecret.api_version, BitwardenSyncSecret.plural,
)
async def bitwarden_sync_secret_resume(**kwargs):
    """
    Handle resume of BitwardenSyncSecret
    """
    await BitwardenSyncSecret.on_resume(**kwargs)

@kopf.on.update(
    BitwardenSyncSecret.api_group, BitwardenSyncSecret.api_version, BitwardenSyncSecret.plural,
)
async def bitwarden_sync_secret_update(**kwargs):
    """
    Handle update of BitwardenSyncSecret
    """
    await BitwardenSyncSecret.on_update(**kwargs)
