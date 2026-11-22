class Router:
    """Stand-in for a web framework router."""

    def __init__(self):
        self.routes = {}

    def get(self, path):
        def register(fn):
            self.routes[("GET", path)] = fn
            return fn

        return register

    def post(self, path):
        def register(fn):
            self.routes[("POST", path)] = fn
            return fn

        return register


router = Router()
