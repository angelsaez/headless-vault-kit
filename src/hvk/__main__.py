"""Entry point for ``python -m hvk``, so the tool runs from a checkout without installing."""

from hvk.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
