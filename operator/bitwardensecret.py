import os
from base64 import b64encode, b64decode
import kubernetes_asyncio
from k8sutil import CachedK8sObject, K8sUtil
from bitwardensyncconfig import BitwardenSyncError, BitwardenSyncConfigSecret, BitwardenSecrets as BitwardenSecretsUtil


class BitwardenSecrets(CachedK8sObject):
    api_group = K8sUtil.operator_domain
    api_version = K8sUtil.operator_version
    kind = 'BitwardenSecret'
    plural = 'bitwardensecrets'

    api_group_version = f"{api_group}/{api_version}"
    cache = {}
    sync_config_label = os.environ.get('MANAGED_SECRET_LABEL', f"{K8sUtil.operator_domain}/bitwarden-secret")
    # TODO: Make this configurable
    # TODO: Validate Project name
    secret_access_token_secret_name = os.environ.get('SECRET_TOKEN_NAME', 'bitwarden-access-token')
    operator_namespace = os.environ.get('OPERATOR_NAMESPACE', 'bitwarden-dev')

    @classmethod
    async def on_create(cls, logger, **kwargs):
        secret = cls.register(**kwargs)
        await secret.sync_secret(logger=logger)

    @classmethod
    async def on_delete(cls, logger, **kwargs):
        secret = cls.register(**kwargs)
        await secret.delete_secret(logger=logger)

    @classmethod
    async def on_resume(cls, logger, **kwargs):
        secret = cls.register(**kwargs)
        await secret.sync_secret(logger=logger)

    @classmethod
    async def on_update(cls, logger, **kwargs):
        secret = cls.register(**kwargs)
        await secret.sync_secret(logger=logger)

    @property
    def owner_references(self):
        return kubernetes_asyncio.client.V1OwnerReference(
            api_version=self.api_group_version,
            kind="BitwardenSecret",
            name=self.name,
            uid=self.meta.uid,
            controller=True,
            )

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
        return self.spec.get('syncInterval', 30)

    @property
    def uid(self):
        return self.meta.get('uid')

    async def delete_secret(self, logger):
        logger.info(f"Deleting secrets for {self}")

    async def get_access_token(self):
        try:
            token_secret = await K8sUtil.core_v1_api.read_namespaced_secret(
                name=self.secret_access_token_secret_name,
                namespace=self.operator_namespace,
            )
        except kubernetes_asyncio.client.rest.ApiException as err:
            if err.status == 404:
                raise BitwardenSyncError(
                    f"Bitwarden access token secret '{self.secret_access_token_secret_name}' not found"
                ) from err
            raise

        if 'token' not in token_secret.data:
            raise BitwardenSyncError(
                f"Bitwarden access token secret '{self.secret_access_token_secret_name}' missing data.token"
            )

        return b64decode(token_secret.data['token']).decode('utf-8')

    async def get_bitwarden_secrets(self):
        bitwarden_access_token = await self.get_access_token()
        return await BitwardenSecretsUtil.get(access_token=bitwarden_access_token)

    async def get_secret_info(self, secret):
        return {
            "apiVersion": 'v1',
            "kind": "Secret",
            "name": secret.metadata.name,
            "namespace": secret.metadata.namespace,
            "uid": secret.metadata.uid,
            }

    async def is_managed(self, secret):
        return any(
            owner_ref.uid == self.uid and
            owner_ref.kind == self.kind and
            owner_ref.api_version == self.api_version
            for owner_ref in secret.metadata.owner_references or []
            )

    async def sync_secret(self, logger):
        try:
            bitwarden_secrets = await self.get_bitwarden_secrets()
        except BitwardenSyncError as err:
            logger.error(f"Failed getting Bitwarden secrets for {self}: {err}")
            return
        for secret_config in self.secrets:
            try:
                data = {
                    key: b64encode(value.encode('utf-8')).decode('utf-8')
                    for key, value in bitwarden_secrets.get_values(secret_config.data).items()
                }
                annotations = bitwarden_secrets.get_values(secret_config.annotations)
                labels = bitwarden_secrets.get_values(secret_config.labels)
                labels[self.sync_config_label] = self.sync_config_value

                secret = None
                try:
                    secret = await K8sUtil.core_v1_api.read_namespaced_secret(
                        name=secret_config.name,
                        namespace=self.namespace,
                    )
                except kubernetes_asyncio.client.rest.ApiException as err:
                    if err.status != 404:
                        raise BitwardenSyncError(f"Error {err.status} getting secret: {err}") from err

                if secret:
                    if not self.is_managed:
                        raise BitwardenSyncError(
                            f"{secret_config} is not owned by {self}"
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
                            body=secret,
                            name=secret_config.name,
                            namespace=self.namespace,
                        )
                        logger.info(f"Updated {secret_config} for {self}")
                else:
                    secret = await K8sUtil.core_v1_api.create_namespaced_secret(
                        body=kubernetes_asyncio.client.V1Secret(
                            data=data,
                            metadata=kubernetes_asyncio.client.V1ObjectMeta(
                                annotations=annotations,
                                name=secret_config.name,
                                labels=labels,
                                owner_references=[self.owner_references],
                            ),
                            type=secret_config.type,
                        ),
                        namespace=self.namespace,
                    )

                    logger.info(f"Created {secret_config} for {self}")

            except BitwardenSyncError as err:
                logger.error(f"Failed to sync {secret_config} for {self}: {err}")
            except Exception as err:
                logger.exception(f"Error syncing {secret_config} for {self}: {err}")
