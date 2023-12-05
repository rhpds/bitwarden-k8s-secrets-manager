import asyncio
import json
import os

from base64 import b64decode, b64encode

import yaml

import kubernetes_asyncio

from k8sutil import CachedK8sObject, K8sUtil
from bitwardenk8ssyncconfigsecret import BitwardenSyncConfig
from bitwardenk8ssyncconfigsecret import BitwardenSyncConfigSecret
from bitwardensyncerror import BitwardenSyncError

class BitwardenSyncSecret(CachedK8sObject):
    api_group = K8sUtil.operator_domain
    api_version = K8sUtil.operator_version
    kind = 'BitwardenSyncSecret'
    plural = 'bitwardensyncsecrets'

    api_group_version = f"{api_group}/{api_version}"
    cache = {}
    sync_config_label = os.environ.get('MANAGED_SECRET_LABEL', f"{K8sUtil.operator_domain}/config")

    @classmethod
    async def on_create(cls, logger, **kwargs):
        secret = cls.register(**kwargs)

    @classmethod
    async def on_delete(cls, logger, **kwargs):
        secret = cls(**kwargs)
        await secret.handle_delete(logger=logger)
        secret.unregister()

    @classmethod
    async def on_resume(cls, logger, **kwargs):
        config = cls.register(**kwargs)

    @classmethod
    async def on_update(cls, logger, **kwargs):
        config = cls.register(**kwargs)

    @classmethod
    async def sync_for_config(cls, bitwarden_secrets, config, logger):
        for secret in cls.cache.values():
            if secret.config_name == config.name and secret.config_namespace == config.namespace:
                await secret.sync_secret(bitwarden_secrets=bitwarden_secrets, logger=logger)

    @property
    def annotations(self):
        return self.spec.get('annotations', {})

    @property
    def config_name(self):
        return self.spec.get('config', {}).get('name', 'default')

    @property
    def config_namespace(self):
        return self.spec.get('config', {}).get('namespace', self.namespace)

    @property
    def data(self):
        return self.spec.get('data', {})

    @property
    def labels(self):
        self.spec.get('labels', {})

    @property
    def sync_config_value(self):
        return f"{self.namespace}.{self.name}"

    async def check_delete_secret(self):
        secret = None
        try:
            secret = await K8sUtil.core_v1_api.read_namespaced_secret(
                name = self.name,
                namespace = self.namespace,
            )
        except kubernetes_asyncio.client.rest.ApiException as err:
            if err.status == 404:
                return None, None
            raise

        if (
            not secret.metadata.labels or
            secret.metadata.labels['app.kubernetes.io/managed-by'] != 'bitwarden-k8s-secrets-manager' or
            secret.metadata.labels[self.sync_config_label] != self.sync_config_value
        ):
            return secret, False

        try:
            secret = await K8sUtil.core_v1_api.delete_namespaced_secret(
                name = self.name,
                namespace = self.namespace,
            )
        except kubernetes_asyncio.client.rest.ApiException as err:
            if err.status != 404:
                raise
        return secret, True

    async def handle_delete(self, logger):
        secret, deleted = await self.check_delete_secret()
        if not secret:
            logger.info(
                f"Did not find Secret {name} in {namespace} while handling delete of {self}"
            )
        elif deleted:
            logger.info(
                f"Propagated delete of {self} to managed Secret {name} in {namespace}"
            )
        else:
            logger.warning(
                f"Did not delete Secret {name} in {namespace} while handling delete of {self}: "
                f"not managed by this {self.kind}"
            )

    async def sync_secret(self, bitwarden_secrets=bitwarden_secrets, config=config, logger=logger):
        status = {}
        try:
            secret = await BitwardenSyncConfig.manage_secret(
                bitwarden_secrets = bitwarden_secrets,
                configured_by = self,
                name = self.name,
                namespace = self.namespace,
                secret_config = self,
                logger = logger,
            )
            self.merge_patch_status({
                "secret": {
                    "state": "synced",
                    "uid": secret.metadata.uid
                }
            })
        except BitwardenSyncError as err:
            logger.error(f"Failed to sync {self}: {err}")
            self.merge_patch_status({
                "secret": {
                    "state": "failed",
                    "error": f"{err}",
                }
            })
        except Exception as err:
            logger.error(f"Error syncing {self}: {err}")
            self.merge_patch_status({
                "secret": {
                    "state": "error",
                    "error": f"{err}",
                }
            })
