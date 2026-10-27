"""``python -m chaosmonkey ...`` runs ``python -m mcp_fault_bench ...``."""

import sys

from mcp_fault_bench.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
