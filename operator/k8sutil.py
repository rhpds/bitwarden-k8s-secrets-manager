"""
Kubernetes utility classes.
"""
# pylint: disable=too-many-arguments

import asyncio
import os

import kubernetes_asyncio

class K8sUtil:
    """
    Global class for accessing API and processed environment settings
    """

    operator_domain = os.environ.get(
        'OPERATOR_DOMAIN', 'bitwarden-k8s-secrets-manager.demo.redhat.com'
    )
    operator_namespace = None
    operator_version = os.environ.get('OPERATOR_VERSION', 'v1')
    sync_config_label = os.environ.get('MANAGED_SECRET_LABEL', f"{operator_domain}/config")

    @classmethod
    async def on_startup(cls):
        """
        Initialize API on startup
        """
        if os.path.exists('/run/secrets/kubernetes.io/serviceaccount'):
            kubernetes_asyncio.config.load_incluster_config()
            with open('/run/secrets/kubernetes.io/serviceaccount/namespace', encoding="utf-8") as file:
                cls.operator_namespace = file.read()
        else:
            await kubernetes_asyncio.config.load_kube_config()
            cls.operator_namespace = os.environ.get('OPERATOR_NAMSEPACE', None)

        cls.api_client = kubernetes_asyncio.client.ApiClient()
        cls.core_v1_api = kubernetes_asyncio.client.CoreV1Api(cls.api_client)
        cls.custom_objects_api = kubernetes_asyncio.client.CustomObjectsApi(cls.api_client)

    @classmethod
    async def on_cleanup(cls):
        """
        Gracefully shutdown on cleanup
        """
        await cls.api_client.close()

class K8sObject:
    """
    Base class for kopf objects
    """
    # Disable pylint warnings for properties which must be declared in subclass
    # pylint: disable=no-member

    def __init__(self, annotations, labels, meta, name, namespace, spec, status, **_):
        """
        Initalize object from kopf keywords args
        """
        self.annotations = annotations
        self.labels = labels
        self.meta = meta
        self.name = name
        self.namespace = namespace
        self.spec = spec
        self.status = status

    def __str__(self):
        """
        Stringify to description of object.
        """
        return f"{self.kind} {self.name} in {self.namespace}"

    def refresh_from_definition(self, definition):
        """
        Update from object definition as returned by kubernetes api
        """
        self.annotations = definition['metadata'].get('annotations', {})
        self.labels = definition['metadata'].get('labels', {})
        self.meta = definition['metadata']
        self.spec = definition['spec']
        self.status = definition.get('status', {})

    async def delete(self):
        """
        Delete object, treating 404 NOT FOUND as success
        """
        try:
            definition = await K8sUtil.custom_objects_api.delete_namespaced_custom_object(
                group = self.api_group,
                name = self.name,
                namespace = self.namespace,
                plural = self.plural,
                version = self.api_version,
            )
            self.refresh_from_definition(definition)
        except kubernetes_asyncio.client.rest.ApiException as err:
            if err.status != 404:
                raise

    async def merge_patch(self, patch):
        """
        Apply JSON merge patch to object.
        """
        definition = await K8sUtil.custom_objects_api.patch_namespaced_custom_object(
            group = self.api_group,
            name = self.name,
            namespace = self.namespace,
            plural = self.plural,
            version = self.api_version,
            body = patch,
            _content_type = 'application/merge-patch+json',
        )
        self.refresh_from_definition(definition)

    async def merge_patch_status(self, patch):
        """
        Apply JSON merge patch to object status.
        """
        definition = await K8sUtil.custom_objects_api.patch_namespaced_custom_object_status(
            group = self.api_group,
            name = self.name,
            namespace = self.namespace,
            plural = self.plural,
            version = self.api_version,
            body = {"status": patch},
            _content_type = 'application/merge-patch+json',
        )
        self.refresh_from_definition(definition)

class CachedK8sObject(K8sObject):
    """
    Base class for kopf objects with cache
    """
    # Disable pylint warning for cache, which must be declared in subclass
    # pylint: disable=no-member

    def __init__(self, annotations, labels, meta, name, namespace, spec, status, **_):
        """
        Initalize object from kopf keywords args and add asyncio lock.
        """
        super().__init__(
            annotations = annotations,
            labels = labels,
            meta = meta,
            name = name,
            namespace = namespace,
            spec = spec,
            status = status,
        )
        self.lock = asyncio.Lock()

    @classmethod
    def register(cls, annotations, labels, meta, name, namespace, spec, status, **_):
        """
        Ceating object in cashe or updating existing from kopf keyword args
        """
        obj = cls.cache.get((namespace, name))
        if obj:
            obj.annotations = annotations
            obj.labels = labels
            obj.meta = meta
            obj.spec = spec
            obj.status = status
        else:
            obj = cls(
                annotations = annotations,
                labels = labels,
                meta = meta,
                name = name,
                namespace = namespace,
                spec = spec,
                status = status,
            )
            cls.cache[(namespace, name)] = obj
        return obj

    def unregister(self):
        """
        Remove object from cache.
        """
        self.cache.pop((self.namespace, self.name))
