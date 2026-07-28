# Licence files

PromptMeld's own source code is covered by the MIT licence in the repository
root. Dependencies and bundled components remain under their respective
licences.

The GNU GPLv3 and LGPLv3 texts were downloaded verbatim from the GNU Project,
and the Apache 2.0 text was downloaded verbatim from the Apache Software
Foundation. Their reviewed SHA-256 hashes are enforced by
`tools/check_licenses.py`.

During a release build, PromptMeld copies this directory, the Python licence,
the Lucide licence, and the licence files exposed by reviewed installed
packages into the portable release. It also generates `DEPENDENCY_AUDIT.txt`
with the exact versions and selected licence terms.

The automated check is a guard against accidental dependency or packaging
changes. It is not a substitute for legal advice.
