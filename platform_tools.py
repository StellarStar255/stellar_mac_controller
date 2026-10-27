"""Select the native tool implementation without changing its mutable settings."""
import sys

if sys.platform == "darwin":
    import mac_tools as implementation
else:
    import desktop_tools as implementation

sys.modules[__name__] = implementation
