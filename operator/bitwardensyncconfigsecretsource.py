class BitwardenSyncConfigSecretSource:
    def __init__(self, definition):
        self.key = definition.get('key')
        self.secret = definition.get('secret')
        self.value = definition.get('value')
