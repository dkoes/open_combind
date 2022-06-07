"""Open-source docking pipeline leveraging pairwise statistics"""

# Add imports here
from .open_combind import *

# Handle versioneer
from ._version import get_versions
versions = get_versions()
__version__ = versions['version']
__git_revision__ = versions['full-revisionid']
del get_versions, versions
