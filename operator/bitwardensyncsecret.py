import kubernetes_asyncio

from k8sutil import CachedK8sObject, K8sUtil
from bitwardensyncconfigsecretsource import BitwardenSyncConfigSecretSource
from bitwardensyncerror import BitwardenSyncError
from bitwardensyncutil import check_delete_secret, manage_secret

class BitwardenSyncSecret(CachedK8sObject):
    api_group = K8sUtil.operator_domain
    api_version = K8sUtil.operator_version
    kind = 'BitwardenSyncSecret'
    plural = 'bitwardensyncsecrets'

    api_group_version = f"{api_group}/{api_version}"
    cache = {}

    @classmethod
    async def on_create(cls, logger, **kwargs):
        secret = cls.register(**kwargs)
        logger.info(f"{secret} created")

    @classmethod
    async def on_delete(cls, logger, **kwargs):
        secret = cls(**kwargs)
        await secret.handle_delete(logger=logger)
        secret.unregister()
        logger.info(f"{secret} deleted")

    @classmethod
    async def on_resume(cls, logger, **kwargs):
        secret = cls.register(**kwargs)
        logger.info(f"{secret} handling resumed")

    @classmethod
    async def on_update(cls, logger, **kwargs):
        secret = cls.register(**kwargs)
        logger.info(f"{secret} updated")

    @classmethod
    async def sync_for_config(cls, bitwarden_projects, bitwarden_secrets, config, logger):
        for secret in cls.cache.values():
            if secret.config_name == config.name and secret.config_namespace == config.namespace:
                await secret.sync_secret(
                    bitwarden_projects=bitwarden_projects,
                    bitwarden_secrets=bitwarden_secrets,
                    logger=logger,
                )

    @property
    def config_name(self):
        return self.spec.get('config', {}).get('name', 'default')

    @property
    def config_namespace(self):
        return self.spec.get('config', {}).get('namespace', K8sUtil.operator_namespace or self.namespace)

    @property
    def project(self):
        return self.spec.get('project', None)

    @property
    def secret_annotations(self):
        return {
            key: BitwardenSyncConfigSecretSource(value)
            for key, value in self.spec.get('annotations', {}).items()
        }

    @property
    def secret_data(self):
        return {
            key: BitwardenSyncConfigSecretSource(value)
            for key, value in self.spec.get('data', {}).items()
        }

    @property
    def secret_labels(self):
        return {
            key: BitwardenSyncConfigSecretSource(value)
            for key, value in self.spec.get('labels', {}).items()
        }

    @property
    def sync_config_value(self):
        return f"{self.namespace}.{self.name}"

    @property
    def type(self):
        return self.spec.get('type', 'Opaque')

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
            secret.metadata.labels[K8sUtil.sync_config_label] != self.sync_config_value
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
        await check_delete_secret(
            managed_by=self,
            name=self.name,
            namespace=self.namespace,
            logger=logger,
        )

    async def sync_secret(self, bitwarden_projects, bitwarden_secrets, logger):
        try:
            secret = await manage_secret(
                bitwarden_projects = bitwarden_projects,
                bitwarden_secrets = bitwarden_secrets,
                managed_by = self,
                name = self.name,
                namespace = self.namespace,
                secret_config = self,
                logger = logger,
            )
            await self.merge_patch_status({
                "error": None,
                "state": "synced",
                "secret": {
                    "uid": secret.metadata.uid
                }
            })
        except BitwardenSyncError as err:
            logger.error(f"Failed to sync {self}: {err}")
            await self.merge_patch_status({
                "error": f"{err}",
                "state": "failed",
            })
        # pylint: disable-next=broad-except
        except Exception as err:
            logger.error(f"Error syncing {self}: {err}")
            await self.merge_patch_status({
                "error": f"{err}",
                "state": "error",
            })
