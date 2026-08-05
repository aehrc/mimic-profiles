"""Shared helpers for the terminology build scripts.

Scripts under terminology/, conceptmaps/ and verify/ bootstrap this package with

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

so they stay directly runnable (`uv run scripts/.../build_x.py`) without the
repo needing to be installed as a package.
"""
