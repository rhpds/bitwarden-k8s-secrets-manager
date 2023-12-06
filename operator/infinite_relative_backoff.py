"""
Implementation of infinite backoff for Kopf
"""

class InfiniteRelativeBackoff:
    """
    Infinite backoff logic with configurable maximum retry period.
    """
    # pylint: disable=too-few-public-methods

    def __init__(self, initial_delay=0.1, scaling_factor=2, maximum=60):
        """
        Initialize with defaults.
        """
        self.initial_delay = initial_delay
        self.scaling_factor = scaling_factor
        self.maximum = maximum

    def __iter__(self):
        """
        Iterator called by kopf.
        """
        delay = self.initial_delay
        while True:
            if delay > self.maximum:
                yield self.maximum
            else:
                yield delay
                delay *= self.scaling_factor
