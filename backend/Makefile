# SAM custom build (CodeUri = backend/). Uses Python so host (Windows) and
# container builds both work. ARTIFACTS_DIR is injected by `sam build`.

.PHONY: \
	build-DiscoverSchemaFunction \
	build-ProvisionShadowClusterFunction \
	build-LoadSchemaFunction \
	build-ExecuteMigrationFunction \
	build-CollectMetricsFunction \
	build-PersistResultsFunction \
	build-CleanupFunction \
	build-ShadowSweeperFunction

define PACKAGE_LAMBDA
	python scripts/package_lambda_for_sam.py "$(ARTIFACTS_DIR)"
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
