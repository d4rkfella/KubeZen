
def get_all_subclasses(cls: type) -> set[type]:
    """Recursively finds all subclasses of a given class."""
    return set(cls.__subclasses__()).union(
        [s for c in cls.__subclasses__() for s in get_all_subclasses(c)]
    )
