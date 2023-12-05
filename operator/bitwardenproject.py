class BitwardenProject:
    # pylint: disable=too-few-public-methods

    def __init__(self, definition):
        # "id" should be considered a valid name
        # pylint: disable=invalid-name
        self.id = definition['id']
        self.name = definition['name']

    def __str__(self):
        return f"{self.name} ({self.id})"
