class BitwardenSecret:
    def __init__(self, definition):
        self.id = definition['id']
        self.key = definition['key']
        # Attempt to handle values as YAML, but only use YAML parsed value if it is not a string.
        try:
            self.value = yaml.safe_load(definition['value'])
            if isinstance(self.value, str):
                self.value = definition['value']
        except yaml.parser.ParserError:
            self.value = definition['value']

    def __str__(self):
        return f"{self.key} ({self.id})"
