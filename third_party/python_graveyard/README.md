# Python Graveyard

Python is cleaning its standard library.  Some modules have easy replacements,
while others do not.  This directory holds forked code from Python for the not
easy cases.

## distutils_version.py

The `distutils` module was deprecated in Python 3.10 and dropped in 3.12 via
[PEP 632](https://peps.python.org/pep-0632/).  The `distutils.versions` module
was replaced by the `packaging.versions` module, but that's a 3rd party module
that isn't guaranteed to be installed.  Since `version.py` is so small, we
forked it to avoid external module dependencies.

This is the last version of the code before it was removed upstream.
https://github.com/python/cpython/blob/b07f546ea3a574bc3016fb023c157c65a47f4849/Lib/distutils/version.py
