__version__ = "0.1.3"

__all__ = ["PGLOKApp", "main", "__version__"]


def __getattr__(name):
    if name == "PGLOKApp":
        from src.pglok import PGLOKApp
        return PGLOKApp
    if name == "main":
        from src.pglok import main
        return main
    raise AttributeError(f"module 'src' has no attribute '{name}'")
