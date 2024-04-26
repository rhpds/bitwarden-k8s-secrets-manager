class BitwardenSyncConfigSecretSource:
    # pylint: disable=too-few-public-methods
    def __init__(self, definition):
        self.base64encode = definition.get('base64encode', True)
        self.key = definition.get('key')
        self.project = definition.get('project')
        self.secret = definition.get('secret')
        self.value = definition.get('value')
