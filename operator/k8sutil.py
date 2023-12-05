import asyncio
import os

import kubernetes_asyncio

class K8sUtil:
    operator_domain = os.environ.get('OPERATOR_DOMAIN', 'bitwarden-k8s-secrets-manager.demo.redhat.com')
    operator_version = os.environ.get('OPERATOR_VERSION', 'v1')

    @classmethod
    async def on_startup(cls):
        if os.path.exists('/run/secrets/kubernetes.io/serviceaccount'):
            kubernetes_asyncio.config.load_incluster_config()
        else:
            await kubernetes_asyncio.config.load_kube_config()

        cls.core_v1_api = kubernetes_asyncio.client.CoreV1Api()
        cls.custom_objects_api = kubernetes_asyncio.client.CustomObjectsApi()

class K8sObject:
    def __init__(self, annotations, labels, meta, name, namespace, spec, status, **_):
        self.annotations = annotations
        self.labels = labels
        self.meta = meta
        self.name = name
        self.namespace = namespace
        self.spec = spec
        self.status = status

    @classmethod
    async def get(cls, name):
        definition = await K8sUtil.custom_objects_api.get_cluster_custom_object(
            group = cls.group,
            name = name,
            namespace = namespace,
            plural = cls.plural,
            version = cls.version,
        )
        return cls(definition)

    def __str__(self):
        return f"{self.kind} {self.name} in {self.namespace}"

    def refresh_from_definition(self, definition):
        self.annotations = definition['metadata'].get('annotations', {})
        self.labels = definition['metadata'].get('labels', {})
        self.meta = definition['metadata']
        self.spec = definition['spec']
        self.status = definition.get('status', {})

    async def delete(self):
        try:
            definition = await K8sUtil.custom_objects_api.delete_namespaced_custom_object(
                group = self.api_group,
                name = self.name,
                namespace = self.namespace,
                plural = self.plural,
                version = self.api_version,
            )
            self.refresh_from_definition(definition)
        except kubernetes_asyncio.client.rest.ApiException as e:
            if e.status != 404:
                raise

    async def merge_patch(self, patch):
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
    def __init__(self, annotations, labels, meta, name, namespace, spec, status):
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
        cls.cache.pop((self.namespace, self.name))
