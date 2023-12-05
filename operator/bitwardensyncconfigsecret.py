from bitwardensyncconfigsecretsource import BitwardenSyncConfigSecretSource

class BitwardenSyncConfigSecret:
    # pylint: disable=too-few-public-methods
    def __init__(self, definition):
        self.secret_annotations = {
            key: BitwardenSyncConfigSecretSource(value)
            for key, value in definition.get('annotations', {}).items()
        }
        self.secret_data = {
            key: BitwardenSyncConfigSecretSource(value)
            for key, value in definition.get('data', {}).items()
        }
        self.secret_labels = {
            key: BitwardenSyncConfigSecretSource(value)
            for key, value in definition.get('labels', {}).items()
        }
        self.name = definition['name']
        self.namespace = definition.get('namespace')
        self.type = definition.get('type', 'Opaque')
