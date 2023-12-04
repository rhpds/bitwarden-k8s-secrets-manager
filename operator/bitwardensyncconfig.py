import asyncio
import json
import os

from base64 import b64decode, b64encode

import yaml

import kubernetes_asyncio

from k8sutil import CachedK8sObject, K8sUtil


class BitwardenSyncConfig(CachedK8sObject):
    api_group = K8sUtil.operator_domain
    api_version = K8sUtil.operator_version
    kind = 'BitwardenSyncConfig'
    plural = 'bitwardensyncconfigs'

    api_group_version = f"{api_group}/{api_version}"
    cache = {}
    sync_config_label = os.environ.get('MANAGED_SECRET_LABEL', f"{K8sUtil.operator_domain}/config")

    @classmethod
    async def on_create(cls, logger, **kwargs):
        config = cls.register(**kwargs)
        await config.sync_secrets(logger=logger)

    @classmethod
    async def on_delete(cls, logger, **kwargs):
        config = cls.register(**kwargs)
        await config.delete_secrets(logger=logger)

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
                name=name,
                namespace=namespace,
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
                name=name,
                namespace=namespace,
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
                    f"not managed by this config"
                )

    async def get_access_token(self):
        try:
            token_secret = await K8sUtil.core_v1_api.read_namespaced_secret(
                name=self.access_token_secret_name,
                namespace=self.namespace,
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
                data = {
                    key: b64encode(value.encode('utf-8')).decode('utf-8')
                    for key, value in bitwarden_secrets.get_values(secret_config.data).items()
                }
                annotations = bitwarden_secrets.get_values(secret_config.annotations)
                labels = bitwarden_secrets.get_values(secret_config.labels)
                labels['app.kubernetes.io/managed-by'] = 'bitwarden-k8s-secrets-manager'
                labels[self.sync_config_label] = self.sync_config_value

                secret = None
                try:
                    secret = await K8sUtil.core_v1_api.read_namespaced_secret(
                        name=secret_config.name,
                        namespace=namespace,
                    )
                    status_entry['uid'] = secret.metadata.uid
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
                        self.sync_config_label in secret.metadata.labels and
                        secret.metadata.labels[self.sync_config_label] != self.sync_config_value
                    ):
                        managed_by_namespace, managed_by_name = secret.metadata.labels[self.sync_config_label].split('.')
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
                            body=secret,
                            name=secret_config.name,
                            namespace=namespace,
                        )
                        logger.info(f"Updated {secret_config} for {self}")
                        status_entry['state'] = 'synced'
                    else:
                        status_entry['state'] = 'synced'

                else:
                    secret = await K8sUtil.core_v1_api.create_namespaced_secret(
                        body=kubernetes_asyncio.client.V1Secret(
                            data=data,
                            metadata=kubernetes_asyncio.client.V1ObjectMeta(
                                annotations=annotations,
                                name=secret_config.name,
                                labels=labels,
                            ),
                            type=secret_config.type,
                        ),
                        namespace=namespace,
                    )
                    logger.info(f"Created {secret_config} for {self}")
                    status_entry['state'] = 'synced'
                    status_entry['uid'] = secret.metadata.uid

            except BitwardenSyncError as err:
                logger.error(f"Failed to sync {secret_config} for {self}: {err}")
                status_entry['state'] = 'failed'
                status_entry['error'] = f"{err}"
            except Exception as err:
                logger.exception(f"Error syncing {secret_config} for {self}")
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


class BitwardenSyncConfigSecret:
    def __init__(self, definition):
        self.annotations = {
            key: BitwardenSyncConfigSecretSource(value)
            for key, value in definition.get('annotations', {}).items()
        }
        self.data = {
            key: BitwardenSyncConfigSecretSource(value)
            for key, value in definition.get('data', {}).items()
        }
        self.labels = {
            key: BitwardenSyncConfigSecretSource(value)
            for key, value in definition.get('labels', {}).items()
        }
        self.name = definition['name']
        self.namespace = definition.get('namespace')
        self.type = definition.get('type', 'Opaque')

    def __str__(self):
        return f"Secret {self.name} in {self.namespace}"


class BitwardenSyncConfigSecretSource:
    def __init__(self, definition):
        self.key = definition.get('key')
        self.secret = definition.get('secret')
        self.value = definition.get('value')
        self.project = definition.get('project')


class BitwardenSecrets:
    bws_cmd = os.environ.get('BWS_CMD', 'bws')

    @classmethod
    async def get_projects(cls, access_token):
        proc = await asyncio.create_subprocess_exec(
            cls.bws_cmd, '--access-token', access_token, '--output', 'json', 'list', 'projects',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if stderr:
            raise BitwardenSyncError(f"bws error: {stderr}")

        return json.loads(stdout)

    @classmethod
    async def get(cls, access_token):
        projects = await cls.get_projects(access_token)
        project_map = {project['id']: project['name'] for project in projects}
        proc = await asyncio.create_subprocess_exec(
            cls.bws_cmd, '--access-token', access_token, '--output', 'json', 'list', 'secrets',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if stderr:
            raise BitwardenSyncError(f"bws error: {stderr}")

        secrets = json.loads(stdout)
        for item in secrets:
            item['project'] = project_map.get(item['projectId'])

        return cls(
            secrets_dict={
                item['key']: BitwardenSecret(item)
                for item in secrets
            }
        )

    def __init__(self, secrets_dict):
        self.secrets_dict = secrets_dict

    def get_values(self, secret_sources):
        ret = {}
        for key, src in secret_sources.items():
            if src.value:
                ret[key] = src.value
            elif src.secret:
                if src.secret not in self.secrets_dict:
                    raise BitwardenSyncError(f"No Bitwarden secret {src.secret}")
                value = self.secrets_dict[src.secret].value
                if src.key:
                    if not isinstance(value, dict):
                        raise BitwardenSyncError(
                            f"Bitwarden secret {src.secret} not in YAML dictionary format"
                        )
                    if src.key not in value:
                        raise BitwardenSyncError(
                            f"Bitwarden secret {src.secret} has no key {src.key}"
                        )
                    value = value[src.key]
                if isinstance(value, str):
                    ret[key] = value
                else:
                    # Maybe not what is intended, but better than to fail?
                    ret[key] = json.dumps(value)
            else:
                raise BitwardenSyncError("No secret or value in configuration")
        return ret


class BitwardenSecret:
    def __init__(self, definition):
        self.id = definition['id']
        self.key = definition['key']
        self.project = definition['project']
        # Attempt to handle values as YAML, but only use YAML parsed value if it is not a string.
        try:
            self.value = yaml.safe_load(definition['value'])
            if isinstance(self.value, str):
                self.value = definition['value']
        except yaml.parser.ParserError:
            self.value = definition['value']

    def __str__(self):
        return f"{self.key} ({self.id}) {self.project}"


class BitwardenSyncError(Exception):
    pass
