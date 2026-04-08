class BuildError(Exception):
    pass


class ConfigurationError(BuildError):
    pass


class DependencyError(BuildError):
    pass


class ExtractionError(BuildError):
    pass


class ModificationError(BuildError):
    pass


class PackagingError(BuildError):
    pass
