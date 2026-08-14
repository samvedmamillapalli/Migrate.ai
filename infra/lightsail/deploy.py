#!/usr/bin/env python3
"""Deploy Migration Oracle to Amazon Lightsail Containers (us-east-1).

Two Lightsail container services, the cheapest AWS path that still gives a
managed HTTPS endpoint with no domain purchase and no load balancer bill:

    migration-oracle-api   micro (1 GB)    $10/mo   FastAPI control plane
    migration-oracle       nano  (512 MB)   $7/mo   Next.js web console

Why staged rather than one shot: Next.js inlines NEXT_PUBLIC_API_BASE_URL into
the client bundle at BUILD time, so the web image cannot be built until the API
URL exists; and the API's CORS_ORIGINS cannot be set until the web URL exists.
That circular dependency is resolved by running the stages in order.

    python infra/lightsail/deploy.py services   # create both services (~5 min)
    python infra/lightsail/deploy.py api        # build+push+deploy the API
    python infra/lightsail/deploy.py web        # build+push+deploy the console
    python infra/lightsail/deploy.py finalize   # point API CORS at the console
    python infra/lightsail/deploy.py status     # show URLs and states

Every stage is idempotent; re-running one redeploys that piece.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REGION = "us-east-1"
API_SERVICE = "migration-oracle-api"
WEB_SERVICE = "migration-oracle"
API_POWER, WEB_POWER = "micro", "nano"

# lightsailctl is invoked by the AWS CLI, not by us, so it only needs to be
# discoverable on PATH.
LIGHTSAILCTL_DIR = Path.home() / "bin"


# --------------------------------------------------------------------------
# .env handling
# --------------------------------------------------------------------------

def load_env() -> dict[str, str]:
    """Parse repo-root .env, folding multi-line values (the GitHub App PEM)."""
    raw = (REPO / ".env").read_text(encoding="utf-8-sig")
    pairs: list[list[str]] = []
    for line in raw.splitlines():
        line = line.rstrip("\r")
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if m:
            pairs.append([m.group(1), m.group(2)])
        elif pairs and line.strip() and not line.lstrip().startswith("#"):
            pairs[-1][1] += "\n" + line
    return {k: v.strip().strip('"') for k, v in pairs}


# Secrets and config the API container needs. Anything not listed here is
# deliberately not shipped to the container.
API_PASSTHROUGH = [
    "DATABASE_URL",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION",
    "MIGRATION_WORKFLOW_ARN", "RUN_ARTIFACTS_BUCKET", "USER_DATABASE_SECRET_PREFIX",
    "BEDROCK_PREDICTION_MODEL_ID", "BEDROCK_RECOMMENDATION_MODEL_ID",
    "BEDROCK_EMBEDDING_MODEL_ID", "BEDROCK_REGION",
    "AWS_CLOUDWATCH_NAMESPACE",
    "SHADOW_PROVIDER", "SHADOW_APP_TAG", "SHADOW_CLUSTER_CLOUD",
    "SHADOW_CLUSTER_REGION", "SHADOW_MAX_CONCURRENT", "SHADOW_MAX_LIFETIME_MINUTES",
    "CCLOUD_API_KEY", "CCLOUD_API_SECRET", "CCLOUD_API_BASE_URL", "SHADOW_CLUSTER_PLAN",
    "CLERK_SECRET_KEY", "CLERK_PUBLISHABLE_KEY",
    "SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET", "SLACK_SIGNING_SECRET",
    "SLACK_STATE_SECRET", "SLACK_TOKEN_ENCRYPTION_KEY",
    "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_WEBHOOK_SECRET",
    "GITHUB_API_BASE_URL",
    "GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET",
    "GITHUB_OAUTH_STATE_SECRET", "GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY",
]


def api_environment(env: dict[str, str], api_url: str, web_url: str | None) -> dict[str, str]:
    out = {k: env[k] for k in API_PASSTHROUGH if env.get(k)}
    out.update(
        ENVIRONMENT="production",
        DEBUG="false",
        LOG_LEVEL="INFO",
        AWS_ENABLED="true",
        APP_NAME="Migration Oracle",
    )
    # The demo-database button reads this; without it the route falls back to a
    # gitignored local file that does not exist in the image.
    demo = env.get("DEMO_READONLY_DATABASE_URL") or read_local_secret()
    if demo:
        out["DEMO_READONLY_DATABASE_URL"] = demo

    # URL-dependent values. Before the web service exists we still need a valid
    # CORS_ORIGINS (the app validates each origin at startup and refuses to boot
    # on a malformed one), so fall back to localhost.
    front = web_url or "http://localhost:3000"
    out.update(
        FRONTEND_URL=front,
        CORS_ORIGINS=front,
        SLACK_REDIRECT_URI=f"{api_url}/api/slack/oauth/callback",
        SLACK_INSTALL_SUCCESS_REDIRECT=f"{front}/dashboard/settings?slack=connected",
        SLACK_INSTALL_ERROR_REDIRECT=f"{front}/dashboard/settings?slack=error",
        GITHUB_OAUTH_REDIRECT_URI=f"{api_url}/api/github/oauth/callback",
        GITHUB_OAUTH_INSTALL_SUCCESS_REDIRECT=f"{front}/dashboard/settings?github=connected",
        GITHUB_OAUTH_INSTALL_ERROR_REDIRECT=f"{front}/dashboard/settings?github=error",
    )
    return out


def read_local_secret() -> str | None:
    p = REPO / ".local_secrets" / ".judge_ro_database_url"
    return p.read_text(encoding="utf-8").strip() if p.is_file() else None


# --------------------------------------------------------------------------
# AWS plumbing
# --------------------------------------------------------------------------

def aws(*args: str, capture: bool = True, env: dict[str, str] | None = None) -> str:
    shell_env = os.environ.copy()
    if env:
        for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
            if env.get(k):
                shell_env[k] = env[k]
        shell_env.pop("AWS_PROFILE", None)  # would shadow the explicit keys
    shell_env["PATH"] = f"{LIGHTSAILCTL_DIR}{os.pathsep}{shell_env['PATH']}"
    cmd = ["aws", *args, "--region", REGION]
    r = subprocess.run(cmd, capture_output=capture, text=True, env=shell_env)
    if r.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(cmd[:4])}...\n{r.stderr or r.stdout}")
    return r.stdout


def service_state(name: str, env) -> tuple[str, str] | None:
    try:
        out = aws("lightsail", "get-container-services", "--service-name", name,
                  "--output", "json", env=env)
    except SystemExit as exc:
        # "not found" is a normal pre-create answer; anything else (notably the
        # AccessDenied you get before the lightsail policy is attached) must not
        # be silently reported as "does not exist".
        text = str(exc)
        if "AccessDenied" in text or "not authorized" in text:
            raise SystemExit(
                "AccessDenied on lightsail:GetContainerServices.\n"
                "The IAM user needs a lightsail:* policy - see the "
                "'lightsail-deploy' step in docs/AWS_DEPLOYMENT_PLAN.md."
            ) from exc
        return None
    svcs = json.loads(out).get("containerServices", [])
    if not svcs:
        return None
    return svcs[0]["state"], svcs[0].get("url", "").rstrip("/")


def ensure_service(name: str, power: str, env) -> None:
    if service_state(name, env):
        print(f"  {name}: already exists")
        return
    print(f"  {name}: creating ({power}, scale 1) ...")
    aws("lightsail", "create-container-service", "--service-name", name,
        "--power", power, "--scale", "1", "--output", "json", env=env)


def wait_ready(name: str, env, timeout: int = 900) -> str:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        st = service_state(name, env)
        if st:
            state, url = st
            if state != last:
                print(f"  {name}: {state}")
                last = state
            if state == "READY":
                return url
            if state in {"FAILED", "DISABLED"}:
                raise SystemExit(f"{name} entered {state}")
        time.sleep(15)
    raise SystemExit(f"timed out waiting for {name}")


def docker(*args: str) -> None:
    r = subprocess.run(["docker", *args], text=True)
    if r.returncode != 0:
        raise SystemExit(f"docker {args[0]} failed")


def push_image(service: str, label: str, local_tag: str, env) -> str:
    """Push a local image and return the ':service.label.N' reference."""
    print(f"  pushing {local_tag} -> {service}/{label} (this takes a few minutes)")
    out = aws("lightsail", "push-container-image", "--service-name", service,
              "--label", label, "--image", local_tag, env=env)
    m = re.search(r'"(:[\w.-]+)"', out) or re.search(r"(:[\w-]+\.[\w-]+\.\d+)", out)
    if not m:
        raise SystemExit(f"could not parse pushed image ref from:\n{out}")
    ref = m.group(1)
    print(f"  pushed as {ref}")
    return ref


def deploy(service: str, containers: dict, endpoint: dict, env) -> None:
    aws("lightsail", "create-container-service-deployment",
        "--service-name", service,
        "--containers", json.dumps(containers),
        "--public-endpoint", json.dumps(endpoint),
        "--output", "json", env=env)


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------

def stage_services(env) -> None:
    print("Creating container services ...")
    ensure_service(API_SERVICE, API_POWER, env)
    ensure_service(WEB_SERVICE, WEB_POWER, env)
    api_url = wait_ready(API_SERVICE, env)
    web_url = wait_ready(WEB_SERVICE, env)
    print(f"\n  API endpoint: {api_url}\n  Web endpoint: {web_url}\n")
    print("Next: python infra/lightsail/deploy.py api")


def stage_api(env) -> None:
    api_url = wait_ready(API_SERVICE, env)
    _, web_url = service_state(WEB_SERVICE, env) or ("", "")

    print("Building API image ...")
    docker("build", "--platform", "linux/amd64", "-t", "migration-oracle-api:deploy", str(REPO))
    ref = push_image(API_SERVICE, "api", "migration-oracle-api:deploy", env)

    containers = {
        "api": {
            "image": ref,
            "environment": api_environment(env, api_url, web_url or None),
            "ports": {"8000": "HTTP"},
        }
    }
    endpoint = {
        "containerName": "api",
        "containerPort": 8000,
        # /health is cheap and reflects DB + AWS reachability, so an unhealthy
        # deployment is rolled back rather than served.
        "healthCheck": {
            "path": "/health",
            "intervalSeconds": 30,
            "timeoutSeconds": 10,
            "healthyThreshold": 2,
            "unhealthyThreshold": 5,
            "successCodes": "200-299",
        },
    }
    print("Deploying API ...")
    deploy(API_SERVICE, containers, endpoint, env)
    wait_ready(API_SERVICE, env)
    print(f"\n  API live: {api_url}/health\n")
    print("Next: python infra/lightsail/deploy.py web")


def stage_web(env) -> None:
    api_url = wait_ready(API_SERVICE, env)
    clerk_pk = env.get("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY") or env.get("CLERK_PUBLISHABLE_KEY", "")
    if not clerk_pk:
        raise SystemExit("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY missing from .env")

    print(f"Building web image against API {api_url} ...")
    # Build args, not runtime env: Next inlines NEXT_PUBLIC_* into the bundle.
    docker("build", "--platform", "linux/amd64",
           "-f", str(REPO / "frontend/oracle/Dockerfile"), str(REPO / "frontend/oracle"),
           "--build-arg", f"NEXT_PUBLIC_API_BASE_URL={api_url}",
           "--build-arg", f"NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY={clerk_pk}",
           "-t", "migration-oracle-web:deploy")
    ref = push_image(WEB_SERVICE, "web", "migration-oracle-web:deploy", env)

    containers = {
        "web": {
            "image": ref,
            "environment": {
                "NODE_ENV": "production",
                "PORT": "3000",
                "HOSTNAME": "0.0.0.0",
                "CLERK_SECRET_KEY": env.get("CLERK_SECRET_KEY", ""),
                # Clerk's server-side helpers read the publishable key at
                # runtime too, not only at build time.
                "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": clerk_pk,
                "NEXT_PUBLIC_API_BASE_URL": api_url,
            },
            "ports": {"3000": "HTTP"},
        }
    }
    endpoint = {
        "containerName": "web",
        "containerPort": 3000,
        "healthCheck": {
            "path": "/",
            "intervalSeconds": 30,
            "timeoutSeconds": 10,
            "healthyThreshold": 2,
            "unhealthyThreshold": 5,
            "successCodes": "200-299",
        },
    }
    print("Deploying web console ...")
    deploy(WEB_SERVICE, containers, endpoint, env)
    web_url = wait_ready(WEB_SERVICE, env)
    print(f"\n  Web live: {web_url}\n")
    print("Next: python infra/lightsail/deploy.py finalize")


def stage_finalize(env) -> None:
    """Re-deploy the API with the real web URL in CORS_ORIGINS and redirects."""
    api_url = wait_ready(API_SERVICE, env)
    web_url = wait_ready(WEB_SERVICE, env)

    cur = json.loads(aws("lightsail", "get-container-service-deployments",
                         "--service-name", API_SERVICE, "--output", "json", env=env))
    deployments = cur.get("deployments", [])
    if not deployments:
        raise SystemExit("API has no deployment yet — run the 'api' stage first")
    image = deployments[0]["containers"]["api"]["image"]

    containers = {
        "api": {
            "image": image,
            "environment": api_environment(env, api_url, web_url),
            "ports": {"8000": "HTTP"},
        }
    }
    endpoint = {
        "containerName": "api",
        "containerPort": 8000,
        "healthCheck": {
            "path": "/health", "intervalSeconds": 30, "timeoutSeconds": 10,
            "healthyThreshold": 2, "unhealthyThreshold": 5, "successCodes": "200-299",
        },
    }
    print(f"Re-deploying API with CORS_ORIGINS={web_url} ...")
    deploy(API_SERVICE, containers, endpoint, env)
    wait_ready(API_SERVICE, env)
    print(f"\n  Console:  {web_url}\n  API:      {api_url}\n  Health:   {api_url}/health\n")


def stage_status(env) -> None:
    for name in (API_SERVICE, WEB_SERVICE):
        st = service_state(name, env)
        print(f"  {name}: {st[0] if st else 'DOES NOT EXIST'}  {st[1] if st else ''}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["services", "api", "web", "finalize", "status"])
    args = ap.parse_args()
    env = load_env()
    if not env.get("AWS_ACCESS_KEY_ID"):
        raise SystemExit("AWS_ACCESS_KEY_ID missing from .env")
    {"services": stage_services, "api": stage_api, "web": stage_web,
     "finalize": stage_finalize, "status": stage_status}[args.stage](env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
