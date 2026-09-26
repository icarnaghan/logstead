# Logstead - top-level developer & deployment commands.
#
# Run `make` or `make help` to see everything. Targets wrap the real tooling
# (SAM, npm, the infra/*.sh scripts) and handle a couple of local-env quirks
# (iCloud "* 2.*" duplicate files, and removing the backend venv before a
# container build).
#
# Written for portable Make (works with the macOS-default GNU Make 3.81):
# each recipe is a single shell line, so no .ONESHELL dependency.
#
# Config knobs (override on the CLI, e.g. `make deploy REGION=us-west-2`):
STACK   ?= logstead
REGION  ?= us-east-1
PY      ?= python3.12
# App origin the SPA is built for (OAuth redirect/logout + expected CORS origin).
# The SPA must be built for the exact origin it is served from, or sign-in
# and API calls fail with a state/CORS error. Set this to your deployed
# custom domain (e.g. https://app.example.com). For a no-custom-domain
# deploy, leave it empty and deploy-spa.sh falls back to the CloudFront domain.
#
# Keep your real value out of version control: put it in an untracked
# `local.mk` (gitignored), which is included below and overrides this default:
#     APP_ORIGIN = https://app.example.com
APP_ORIGIN ?= https://app.example.com

# Optional developer-local overrides (gitignored). Lets you set machine- or
# deployment-specific values (e.g. APP_ORIGIN, STACK, REGION) without editing
# or committing this Makefile. Silent no-op when the file is absent.
-include local.mk

ROOT      := $(shell pwd)
BACKEND   := $(ROOT)/backend
FRONTEND  := $(ROOT)/frontend
INFRA     := $(ROOT)/infra
VENV      := $(BACKEND)/.venv

SHELL := /bin/bash

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@echo "Logstead - make targets"; echo
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo; echo "Config: STACK=$(STACK) REGION=$(REGION) PY=$(PY)  (override on the CLI)"

.PHONY: install
install: install-backend install-frontend ## Install backend venv + frontend deps

.PHONY: install-backend
install-backend: ## Create backend venv and install (editable, with dev extras)
	cd $(BACKEND) && rm -rf .venv && $(PY) -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -e ".[dev]" && echo "backend venv ready at $(VENV)"

.PHONY: install-frontend
install-frontend: ## Install frontend npm dependencies
	cd $(FRONTEND) && npm install

.PHONY: dev
dev: ## Run the frontend dev server (Vite) against the deployed API
	cd $(FRONTEND) && npm run dev

.PHONY: test
test: test-backend test-frontend ## Run all backend + frontend tests

.PHONY: test-backend
test-backend: ensure-venv ## Run backend tests (pytest)
	cd $(BACKEND) && .venv/bin/python -m pytest -q

.PHONY: test-frontend
test-frontend: ## Run frontend tests (vitest)
	cd $(FRONTEND) && npm test

.PHONY: lint
lint: ## Type-check the frontend (tsc --noEmit)
	cd $(FRONTEND) && npm run lint

.PHONY: build-frontend
build-frontend: ## Type-check + build the SPA (tsc -b + vite build)
	cd $(FRONTEND) && npm run build

.PHONY: validate
validate: ## Validate the SAM template (lint)
	cd $(INFRA) && sam validate --lint --region $(REGION)

.PHONY: build
build: clean-icloud clean-venv ## SAM build in a container (Docker required)
	cd $(INFRA) && sam build --use-container

.PHONY: deploy-infra
deploy-infra: build ## Build + deploy the AWS stack (SAM)
	cd $(INFRA) && sam deploy --no-confirm-changeset --no-fail-on-empty-changeset

.PHONY: deploy-spa
deploy-spa: ## Build + publish the SPA and invalidate CloudFront
	APP_ORIGIN=$(APP_ORIGIN) $(INFRA)/deploy-spa.sh $(STACK) $(REGION)

.PHONY: deploy
deploy: deploy-infra deploy-spa ## Full deploy: infra then SPA
	@echo "Full deploy complete."

.PHONY: seed
seed: ## Seed the Schedule E category catalog (idempotent)
	$(INFRA)/seed-categories.sh $(STACK) $(REGION)

.PHONY: outputs
outputs: ## Show the deployed CloudFormation stack outputs
	aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) --query "Stacks[0].Outputs" --output table

.PHONY: create-user
create-user: ## Create first Cognito user (make create-user EMAIL=you@example.com)
	@test -n "$(EMAIL)" || { echo "Usage: make create-user EMAIL=you@example.com"; exit 1; }
	POOL=$$(aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue | [0]" --output text); test -n "$$POOL" -a "$$POOL" != "None" || { echo "Could not read UserPoolId."; exit 1; }; echo "Creating user $(EMAIL) in pool $$POOL ..."; aws cognito-idp admin-create-user --user-pool-id "$$POOL" --username "$(EMAIL)" --region $(REGION)

.PHONY: clean-icloud
clean-icloud: ## Delete iCloud "* 2.*" duplicate files that break builds
	found=$$(find . \( -name "* 2.*" -o -name "* 2" -o -name "* 3.*" -o -name "* 3" \) 2>/dev/null | grep -vE "/node_modules/|/\.venv/|/\.aws-sam/|/\.git/" || true); if [ -n "$$found" ]; then echo "$$found" | tr '\n' '\0' | xargs -0 rm -rf; echo "Removed iCloud duplicate files."; else echo "No iCloud duplicates found."; fi

.PHONY: clean-venv
clean-venv: ## Remove the backend venv (iCloud corrupts it before sam build)
	rm -rf $(VENV) && echo "Removed $(VENV)"

.PHONY: clean
clean: clean-icloud ## Remove build artifacts (.aws-sam, dist, caches)
	rm -rf $(INFRA)/.aws-sam $(ROOT)/.aws-sam $(FRONTEND)/dist $(FRONTEND)/*.tsbuildinfo $(BACKEND)/.pytest_cache $(BACKEND)/.hypothesis; find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true; echo "Cleaned build artifacts."

.PHONY: ensure-venv
ensure-venv:
	test -x "$(VENV)/bin/python" || { echo "backend venv missing - creating..."; $(MAKE) install-backend; }
