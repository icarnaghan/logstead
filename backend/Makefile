# SAM makefile build for the Logstead API Lambda.
#
# SAM invokes build-<LogicalId> with ARTIFACTS_DIR set to the directory the
# packaged function must be assembled in. The backend uses a src/ layout, so
# we pip-install the project (and its runtime deps) into ARTIFACTS_DIR so the
# top-level `logstead` package resolves for the handler
# `logstead.router.handler.handler`. The recipe runs with the function
# CodeUri (backend/) as the working directory.

build-ApiFunction:
	pip install . --target "$(ARTIFACTS_DIR)"
