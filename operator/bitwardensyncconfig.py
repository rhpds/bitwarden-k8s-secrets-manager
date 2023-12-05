import asyncio
import json
import os

from base64 import b64decode, b64encode

import yaml

import kubernetes_asyncio

from k8sutil import CachedK8sObject, K8sUtil
from bitwardenk8ssyncconfigsecret import BitwardenSyncConfigSecret
from bitwardensecrets import BitwardenSecrets
from bitwardensyncerror import BitwardenSyncError
from bitwardensyncsecret import BitwardenSyncSecret

class BitwardenSyncConfig(CachedK8sObject):
    api_group = K8sUtil.operator_domain
    api_version = K8sUtil.operator_version
    kind = 'BitwardenSyncConfig'
    plural = 'bitwardensyncconfigs'

    api_group_version = f"{api_group}/{api_version}"
    cache = {}
    sync_config_label = os.environ.get('MANAGED_SECRET_LABEL', f"{K8sUtil.operator_domain}/config")

    @classmethod
    async def manage_secret(
        cls, bitwarden_secrets, configured_by, name, namespace, secret_config, logger,
    ):
        data = {
            key: b64encode(value.encode('utf-8')).decode('utf-8')
            for key, value in bitwarden_secrets.get_values(secret_config.data).items()
        }
        annotations = bitwarden_secrets.get_values(secret_config.annotations)
        labels = bitwarden_secrets.get_values(secret_config.labels)
        labels['app.kubernetes.io/managed-by'] = 'bitwarden-k8s-secrets-manager'
        labels[cls.sync_config_label] = configured_by.sync_config_value

        secret = None
        try:
            secret = await K8sUtil.core_v1_api.read_namespaced_secret(
                name = secret_config.name,
                namespace = namespace,
            )
        except kubernetes_asyncio.client.rest.ApiException as err:
            if err.status != 404:
                raise BitwardenSyncError(f"Error {err.status} getting secret: {err}") from err

        if secret:
            if (
                secret.metadata.labels and
                'app.kubernetes.io/managed-by' in secret.metadata.labels and
                secret.metadata.labels['app.kubernetes.io/managed-by'] != labels['app.kubernetes.io/managed-by']
            ):
                raise BitwardenSyncError(
                    f"{secret_config} is managed by {secret.metadata.labels['app.kubernetes.io/managed-by']}"
                )

            if (
                secret.metadata.labels and
                cls.sync_config_label in secret.metadata.labels and
                secret.metadata.labels[cls.sync_config_label] != configured_by.sync_config_value
            ):
                managed_by_namespace, managed_by_name = secret.metadata.labels[cls.sync_config_label].split('.')
                raise BitwardenSyncError(
                    f"{secret_config} is managed by BitwardenSyncConfig {managed_by_name} in {managed_by_namespace}"
                )

            if (
                secret.data != data or
                (secret.metadata.annotations or {}) != annotations or
                (secret.metadata.labels or {}) != labels or
                secret.type != secret_config.type
            ):
                secret.data = data
                secret.metadata.annotations = annotations
                secret.metadata.labels = labels
                secret.type = secret_config.type

                secret = await K8sUtil.core_v1_api.replace_namespaced_secret(
                    body = secret,
                    name = secret_config.name,
                    namespace = namespace,
                )
                logger.info(f"Updated Secret {name} in {namespace} for {configured_by}")

            return secret

        secret = await K8sUtil.core_v1_api.create_namespaced_secret(
            body = kubernetes_asyncio.client.V1Secret(
                data = data,
                metadata = kubernetes_asyncio.client.V1ObjectMeta(
                    annotations = annotations,
                    name = secret_config.name,
                    labels = labels,
                ),
                type = secret_config.type,
            ),
            namespace = namespace,
        )
        logger.info(f"Created Secret {name} in {namespace} for {configured_by}")
        return secret

    @classmethod
    async def on_create(cls, logger, **kwargs):
        config = cls.register(**kwargs)
        await config.sync_secrets(logger=logger)

    @classmethod
    async def on_delete(cls, logger, **kwargs):
        config = cls(**kwargs)
        await config.delete_secrets(logger=logger)
        config.unregister()

    @classmethod
    async def on_resume(cls, logger, **kwargs):
        config = cls.register(**kwargs)
        await config.sync_secrets(logger=logger)

    @classmethod
    async def on_update(cls, logger, **kwargs):
        config = cls.register(**kwargs)
        await config.sync_secrets(logger=logger)

    @property
    def access_token_secret_name(self):
        return self.spec.get("accessTokenSecret", {}).get("name")

    @property
    def secrets(self):
        return [
            BitwardenSyncConfigSecret(item) for item in self.spec.get("secrets", [])
        ]

    @property
    def sync_config_value(self):
        return f"{self.namespace}.{self.name}"

    @property
    def sync_interval(self):
        return self.spec.get('syncInterval', 300)

    async def check_delete_secret(self, name, namespace):
        secret = None
        try:
            secret = await K8sUtil.core_v1_api.read_namespaced_secret(
                name = name,
                namespace = namespace,
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
                name = name,
                namespace = namespace,
            )
        except kubernetes_asyncio.client.rest.ApiException as err:
            if err.status != 404:
                raise
        return secret, True

    async def delete_secrets(self, logger):
        if not self.status:
            return
        secrets = self.status.get('secrets')
        if not secrets:
            return
        for secret_ref in secrets:
            name = secret_ref['name']
            namespace = secret_ref['namespace']
            secret, deleted = await self.check_delete_secret(name=name, namespace=namespace)
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

    async def get_access_token(self):
        try:
            token_secret = await K8sUtil.core_v1_api.read_namespaced_secret(
                name = self.access_token_secret_name,
                namespace = self.namespace,
            )
        except kubernetes_asyncio.client.rest.ApiException as err:
            if err.status == 404:
                raise BitwardenSyncError(
                    f"Bitwarden access token secret '{self.access_token_secret_name}' not found"
                ) from err
            raise

        if 'token' not in token_secret.data:
            raise BitwardenSyncError(
                f"Bitwarden access token secret '{self.access_token_secret_name}' missing data.token"
            )

        return b64decode(token_secret.data['token']).decode('utf-8')

    async def get_bitwarden_secrets(self):
        bitwarden_access_token = await self.get_access_token()
        return await BitwardenSecrets.get(access_token=bitwarden_access_token)

    async def sync_secrets(self, logger):
        try:
            bitwarden_secrets = await self.get_bitwarden_secrets()
        except BitwardenSyncError as err:
            logger.error(f"Failed getting Bitwarden secrets for {self}: {err}")
            return
        status_entries = []
        for secret_config in self.secrets:
            name = secret_config.name
            namespace = secret_config.namespace or self.namespace
            status_entry = {
                "name": name,
                "namespace": namespace,
            }
            status_entries.append(status_entry)
            try:
                secret = await self.manage_secret(
                    bitwarden_secrets = bitwarden_secrets,
                    configured_by = self,
                    name = name,
                    namespace = namespace,
                    secret_config = secret_config,
                )
                status_entry['uid'] = secret.metadata.uid
                status_entry['state'] = 'synced'
            except BitwardenSyncError as err:
                logger.error(f"Failed to sync Secret {name} in {namespace} for {self}: {err}")
                status_entry['state'] = 'failed'
                status_entry['error'] = f"{err}"
            except Exception as err:
                logger.exception(f"Error syncing Secret {name} in {namespace} for {self}")
                status_entry['state'] = 'error'
                status_entry['error'] = f"{err}"

        if self.status and 'secrets' in self.status:
            for secret_ref in self.status['secrets']:
                name = secret_ref['name']
                namespace = secret_ref['namespace']
                for status_entry in status_entries:
                    if name == status_entry['name'] and namespace == status_entry['namespace']:
                        break
                else:
                    secret, deleted = await self.check_delete_secret(name=name, namespace=namespace)
                    if not secret:
                        logger.info(
                            f"Did not find Secret {name} in {namespace} for delete from {self}"
                        )
                    elif deleted:
                        logger.info(
                            f"Deleted Secret {secret_ref['name']} in {secret_ref['namespace']} no longer provided by {self}"
                        )
                    else:
                        logger.warning(
                            f"Did not delete Secret {name} in {namespace} no longer provided by {self}: "
                            f"not managed by this config"
                        )

        await self.merge_patch_status({
            "secrets": status_entries,
        })

        await BitwardenSyncSecret.sync_for_config(
                bitwarden_secrets=bitwarden_secrets,
                config=self,
                logger=logger,
        )
