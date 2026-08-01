# Thin CodeUri for SAM CustomMakeBuilder — keeps CopySource tiny on Windows.
# Real packaging: backend/scripts/package_lambda_for_sam.py
#
# build.ps1 sets BACKEND to an absolute path so this works after CopySource
# copies lambda_src into a temp scratch directory.

.PHONY: \
	build-DiscoverSchemaFunction \
	build-ProvisionShadowClusterFunction \
	build-LoadSchemaFunction \
	build-ExecuteMigrationFunction \
	build-CollectMetricsFunction \
	build-PersistResultsFunction \
	build-CleanupFunction \
	build-ShadowSweeperFunction

# Prefer env BACKEND (absolute). Relative fallback for local experiments only.
BACKEND ?= ../../backend

define PACKAGE_LAMBDA
	python "$(BACKEND)/scripts/package_lambda_for_sam.py" "$(ARTIFACTS_DIR)"
endef

build-DiscoverSchemaFunction:
	$(PACKAGE_LAMBDA)

build-ProvisionShadowClusterFunction:
	$(PACKAGE_LAMBDA)

build-LoadSchemaFunction:
	$(PACKAGE_LAMBDA)

build-ExecuteMigrationFunction:
	$(PACKAGE_LAMBDA)

build-CollectMetricsFunction:
	$(PACKAGE_LAMBDA)

build-PersistResultsFunction:
	$(PACKAGE_LAMBDA)

build-CleanupFunction:
	$(PACKAGE_LAMBDA)

build-ShadowSweeperFunction:
	$(PACKAGE_LAMBDA)
