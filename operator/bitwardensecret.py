import yaml

class BitwardenSecret:
    # pylint: disable=too-few-public-methods

    def __init__(self, definition):
        # "id" should be considered a valid name
        # pylint: disable=invalid-name
        self.id = definition['id']
        self.key = definition['key']
        self.project_id = definition['projectId']

        # Attempt to handle values as YAML, but only use YAML parsed value if it is not a string.
        try:
            self.value = yaml.safe_load(definition['value'])
            if isinstance(self.value, str):
                self.value = definition['value']
        except yaml.parser.ParserError:
            self.value = definition['value']

    def __str__(self):
        return f"{self.key} ({self.id})"
