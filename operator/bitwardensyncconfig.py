from base64 import b64decode

import kubernetes_asyncio

from k8sutil import CachedK8sObject, K8sUtil
from bitwardensyncconfigsecret import BitwardenSyncConfigSecret
from bitwardensecrets import BitwardenSecrets
from bitwardensyncerror import BitwardenSyncError
from bitwardensyncsecret import BitwardenSyncSecret
from bitwardensyncutil import check_delete_secret, manage_secret

class BitwardenSyncConfig(CachedK8sObject):
    api_group = K8sUtil.operator_domain
    api_version = K8sUtil.operator_version
    kind = 'BitwardenSyncConfig'
    plural = 'bitwardensyncconfigs'

    api_group_version = f"{api_group}/{api_version}"
    cache = {}


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
    def project(self):
        return self.spec.get("project", None)

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

    async def delete_secrets(self, logger):
        if not self.status:
            return
        secrets = self.status.get('secrets')
        if not secrets:
            return
        for secret_ref in secrets:
            name = secret_ref['name']
            namespace = secret_ref['namespace']
            await check_delete_secret(managed_by=self, name=name, namespace=namespace, logger=logger)

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
        return await BitwardenSecrets.get(access_token=bitwarden_access_token, project=self.project)

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
                secret = await manage_secret(
                    bitwarden_secrets=bitwarden_secrets,
                    managed_by=self,
                    name=name,
                    namespace=namespace,
                    secret_config=secret_config,
                    logger=logger,
                )
                status_entry['uid'] = secret.metadata.uid
                status_entry['state'] = 'synced'
            except BitwardenSyncError as err:
                logger.error(f"Failed to sync Secret {name} in {namespace} for {self}: {err}")
                status_entry['state'] = 'failed'
                status_entry['error'] = f"{err}"
            # pylint: disable-next=broad-except
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
                    await check_delete_secret(managed_by=self, name=name, namespace=namespace, logger=logger)

        await self.merge_patch_status({
            "secrets": status_entries,
        })

        await BitwardenSyncSecret.sync_for_config(
                bitwarden_secrets=bitwarden_secrets,
                config=self,
                logger=logger,
        )
