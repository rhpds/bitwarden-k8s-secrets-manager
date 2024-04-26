import json

import kubernetes_asyncio

from k8sutil import K8sUtil
from bitwardensyncerror import BitwardenSyncError

# pylint: disable=too-many-arguments

async def check_delete_secret(
    managed_by, name, namespace, logger,
):
    secret = None
    try:
        secret = await K8sUtil.core_v1_api.read_namespaced_secret(
            name = name,
            namespace = namespace,
        )
    except kubernetes_asyncio.client.rest.ApiException as err:
        if err.status == 404:
            logger.info(
                f"Did not find Secret {name} in {namespace} while deleting for {managed_by}"
            )
            return
        raise

    if (
        not secret.metadata.labels or
        secret.metadata.labels['app.kubernetes.io/managed-by'] != 'bitwarden-k8s-secrets-manager' or
        # DEPRECATED - sync_config_value, retain support for compatibility
        (
            secret.metadata.labels[K8sUtil.sync_config_label] != managed_by.sync_config_value and
            secret.metadata.labels[K8sUtil.sync_config_label] != managed_by.uid
        )
    ):
        logger.warning(
            f"Did not delete Secret {name} in {namespace} for {managed_by}: "
            f"{K8sUtil.sync_config_label} label value mismatch"
        )
        return

    try:
        secret = await K8sUtil.core_v1_api.delete_namespaced_secret(
            name = name,
            namespace = namespace,
        )
    except kubernetes_asyncio.client.rest.ApiException as err:
        if err.status == 404:
            logger.info(
                f"Did not find Secret {name} in {namespace} while deleting for {managed_by} after check"
            )
            return
        raise

    logger.info(
        f"Deleted Secret {name} in {namespace} for {managed_by}"
    )

async def manage_secret(
    bitwarden_projects, bitwarden_secrets, managed_by, name, namespace, secret_config, logger,
):
    data = {
        key: value
        for key, value in bitwarden_secrets.get_values(
            sources=secret_config.secret_data, projects=bitwarden_projects, for_data=True,
        ).items()
    }

    annotations = bitwarden_secrets.get_values(
        sources=secret_config.secret_annotations, projects=bitwarden_projects,
    )
    annotations[K8sUtil.sync_config_label] = json.dumps({
        "kind": managed_by.kind,
        "name": managed_by.name,
        "namespace": managed_by.namespace,
    })

    labels = bitwarden_secrets.get_values(
        sources=secret_config.secret_labels, projects=bitwarden_projects,
    )
    labels['app.kubernetes.io/managed-by'] = 'bitwarden-k8s-secrets-manager'
    labels[K8sUtil.sync_config_label] = managed_by.uid

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
                f"Secret {name} in {namespace} is managed by {secret.metadata.labels['app.kubernetes.io/managed-by']}"
            )

        if (
            secret.metadata.labels and
            K8sUtil.sync_config_label in secret.metadata.labels and
            # DEPRECATED - sync_config_value, retain support for compatibility
            (
                secret.metadata.labels[K8sUtil.sync_config_label] != managed_by.sync_config_value and
                secret.metadata.labels[K8sUtil.sync_config_label] != managed_by.uid
            )
        ):
            raise BitwardenSyncError(
                f"Secret {name} in {namespace} is managed by other BitwardenSyncConfig or BitwardenSyncSecret"
            )

        secret_annotations = secret.metadata.annotations or {}
        secret_data = secret.data or {}
        secret_labels = secret.metadata.labels or {}

        if secret_config.action == 'patch':
            if (
                secret_annotations != secret_annotations | annotations or
                secret_data != secret_data | data or
                secret_labels != secret_labels | labels
            ):
                secret = await K8sUtil.core_v1_api.patch_namespaced_secret(
                    body = {
                        "data": data,
                        "metadata": {
                            "annotations": annotations,
                            "labels": labels,
                        },
                    },
                    name = secret_config.name,
                    namespace = namespace,
                )
                logger.info(f"Patched Secret {name} in {namespace} for {managed_by}")
        else:
            if (
                secret_annotations != annotations or
                secret_data != data or
                secret_labels != labels or
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
                logger.info(f"Updated Secret {name} in {namespace} for {managed_by}")

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
    logger.info(f"Created Secret {name} in {namespace} for {managed_by}")
    return secret
