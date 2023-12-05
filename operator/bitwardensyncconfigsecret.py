from bitwardenk8ssyncconfigsecret import BitwardenSyncConfigSecretSource

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
