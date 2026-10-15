"""Entry point of the TaxFill .mcpb bundle (manifest ``server.entry_point``).

The bundle carries no server code: ``pyproject.toml`` beside this directory depends on the published
``taxfill-mcp``, which ``uv run`` installs into the bundle's own environment. This file starts that server over
stdio, exactly as the ``taxfill-mcp`` console script does.
"""
from taxfill_mcp.server import main

if __name__ == "__main__":
    main()
