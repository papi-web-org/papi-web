class Singleton(type):
    """A metaclass for singletons.
    Allows the use of class attributes, contrary to the previous solution
    using a class decorator."""
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]
