r"""Upload, deploy, and undeploy DistilBERT on Vertex AI.

Terraform owns the (gated) Endpoint resource. This script owns model
*versions* — they are training artifacts, not Terraform state. Running
any subcommand talks to GCP; do not invoke it from CI.

Usage (from the repo root, after Workbench training)::

    python -m nlp.endpoint.register upload \\
        --model-dir gs://co-tf-artifacts-dev/nlp/models/distilbert-sent \\
        --display-name distilbert-sent

    python -m nlp.endpoint.register deploy \\
        --model MODEL_RESOURCE_NAME \\
        --endpoint "$VERTEX_ENDPOINT_ID" \\
        --machine-type n1-standard-4 \\
        --accelerator NVIDIA_TESLA_T4

    python -m nlp.endpoint.register undeploy \\
        --endpoint "$VERTEX_ENDPOINT_ID"

Cost: a deployed T4 replica bills until undeployed. Undeploy after the
Dataflow replay drains. An empty Endpoint (Terraform resource, no replica)
does not bill for GPU.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)

_DEFAULT_LOCATION = "europe-central2"
_DEFAULT_STAGING = "gs://co-tf-artifacts-dev/nlp/vertex-staging/"
# Prebuilt PyTorch CPU prediction container. Swap for a GPU container
# (pytorch-gpu.*) when deploying with a T4 accelerator.
_DEFAULT_CONTAINER = "europe-docker.pkg.dev/vertex-ai/prediction/pytorch-cpu.2-3:latest"
_HF_PREDICT_ROUTE = "predict"
_HF_HEALTH_ROUTE = "health"


def _init_aiplatform(project: str, location: str) -> None:
    """Initialise the Vertex SDK.

    Args:
        project: GCP project.
        location: Region.
    """
    import google.cloud.aiplatform as aiplatform  # type: ignore[import-untyped, attr-defined, unused-ignore]

    aiplatform.init(project=project, location=location)


def upload_model(args: argparse.Namespace) -> str:
    """Upload a local Hugging Face directory to Vertex Model Registry.

    Args:
        args: Parsed CLI args.

    Returns:
        The uploaded model's resource name.
    """
    import google.cloud.aiplatform as aiplatform  # type: ignore[import-untyped, attr-defined, unused-ignore]

    _init_aiplatform(args.project, args.location)
    logger.info("Uploading %s → Vertex Model Registry", args.model_dir)
    if not args.model_dir.startswith("gs://"):
        raise SystemExit(
            "--model-dir must be a gs:// URI. Copy the Hugging Face export "
            f"first, e.g. gsutil -m cp -r {args.model_dir} {args.artifact_uri}"
        )
    model = aiplatform.Model.upload(
        display_name=args.display_name,
        artifact_uri=args.model_dir,
        serving_container_image_uri=args.container,
        serving_container_predict_route=f"/{_HF_PREDICT_ROUTE}",
        serving_container_health_route=f"/{_HF_HEALTH_ROUTE}",
        serving_container_ports=[8080],
        labels={
            "project": "pop-vibe-check",
            "model": "distilbert-sent",
            "managed_by": "nlp-endpoint-register",
        },
        description=args.description,
        sync=True,
    )
    logger.info("Uploaded model %s", model.resource_name)
    if args.version_alias:
        logger.info(
            "Set alias %r on this version in the Vertex console if needed.",
            args.version_alias,
        )
    print(model.resource_name)
    return str(model.resource_name)


def deploy_model(args: argparse.Namespace) -> None:
    """Deploy a registry model onto the (already created) Endpoint.

    Args:
        args: Parsed CLI args.
    """
    import google.cloud.aiplatform as aiplatform  # type: ignore[import-untyped, attr-defined, unused-ignore]

    _init_aiplatform(args.project, args.location)
    endpoint = aiplatform.Endpoint(args.endpoint)
    model = aiplatform.Model(args.model)
    kwargs: dict[str, object] = {
        "model": model,
        "deployed_model_display_name": args.deployed_name or "distilbert-sent",
        "machine_type": args.machine_type,
        "min_replica_count": args.min_replicas,
        "max_replica_count": args.max_replicas,
        "traffic_percentage": 100,
        "sync": True,
    }
    if args.accelerator:
        kwargs["accelerator_type"] = args.accelerator
        kwargs["accelerator_count"] = args.accelerator_count
    logger.info(
        "Deploying %s onto %s (%s, accelerator=%s). This bills until undeploy.",
        args.model,
        args.endpoint,
        args.machine_type,
        args.accelerator or "none",
    )
    endpoint.deploy(**kwargs)
    logger.info("Deployed. Predict with VERTEX_ENDPOINT_ID=%s", args.endpoint)


def undeploy_model(args: argparse.Namespace) -> None:
    """Undeploy every replica on the Endpoint (stops GPU/CPU billing).

    Args:
        args: Parsed CLI args.
    """
    import google.cloud.aiplatform as aiplatform  # type: ignore[import-untyped, attr-defined, unused-ignore]

    _init_aiplatform(args.project, args.location)
    endpoint = aiplatform.Endpoint(args.endpoint)
    deployed = list(endpoint.list_models())
    if not deployed:
        logger.info("No deployed models on %s — nothing to undeploy.", args.endpoint)
        return
    for deployed_model in deployed:
        deployed_id = getattr(deployed_model, "id", None) or str(deployed_model)
        logger.info("Undeploying %s from %s", deployed_id, args.endpoint)
        endpoint.undeploy(deployed_model_id=deployed_id, sync=True)
    logger.info("Endpoint %s has no replicas.", args.endpoint)


def _common(parser: argparse.ArgumentParser) -> None:
    """Add project/location flags shared by every subcommand.

    Args:
        parser: Subparser to extend.
    """
    parser.add_argument(
        "--project",
        default=os.environ.get("VERTEX_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT"),
        help="GCP project (VERTEX_PROJECT / GOOGLE_CLOUD_PROJECT).",
    )
    parser.add_argument(
        "--location",
        default=os.environ.get("VERTEX_LOCATION", _DEFAULT_LOCATION),
        help="Vertex region.",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list.

    Returns:
        Parsed namespace with ``command`` set.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    upload = sub.add_parser(
        "upload", help="Upload a model directory to Model Registry."
    )
    _common(upload)
    upload.add_argument(
        "--model-dir", required=True, help="Local HF directory or gs:// URI."
    )
    upload.add_argument(
        "--artifact-uri",
        default=_DEFAULT_STAGING,
        help="GCS URI Vertex copies artifacts from when --model-dir is local.",
    )
    upload.add_argument("--display-name", default="distilbert-sent")
    upload.add_argument("--container", default=_DEFAULT_CONTAINER)
    upload.add_argument("--version-alias", default="production")
    upload.add_argument(
        "--description",
        default="DistilBERT 3-class sentiment (neg/neu/pos), MAX_LEN=128.",
    )

    deploy = sub.add_parser("deploy", help="Deploy a registry model onto the Endpoint.")
    _common(deploy)
    deploy.add_argument("--model", required=True, help="Model resource name.")
    deploy.add_argument(
        "--endpoint",
        default=os.environ.get("VERTEX_ENDPOINT_ID"),
        help="Endpoint id or resource name (VERTEX_ENDPOINT_ID).",
    )
    deploy.add_argument("--deployed-name", default="distilbert-sent")
    deploy.add_argument(
        "--machine-type",
        default="n1-standard-4",
        help=(
            "n1-standard-4 + T4 is the default serving shape; "
            "use n1-standard-8 for CPU-only."
        ),
    )
    deploy.add_argument(
        "--accelerator",
        default="NVIDIA_TESLA_T4",
        help="Accelerator type, or empty string for CPU.",
    )
    deploy.add_argument("--accelerator-count", type=int, default=1)
    deploy.add_argument("--min-replicas", type=int, default=1)
    deploy.add_argument("--max-replicas", type=int, default=1)

    undeploy = sub.add_parser(
        "undeploy", help="Remove every replica (stop GPU billing)."
    )
    _common(undeploy)
    undeploy.add_argument(
        "--endpoint",
        default=os.environ.get("VERTEX_ENDPOINT_ID"),
        help="Endpoint id or resource name.",
    )

    args = parser.parse_args(argv)
    if not args.project:
        parser.error("--project / VERTEX_PROJECT is required")
    if args.command in {"deploy", "undeploy"} and not args.endpoint:
        parser.error("--endpoint / VERTEX_ENDPOINT_ID is required")
    if args.command == "deploy" and args.accelerator == "":
        args.accelerator = None
    return args


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list.

    Returns:
        Process exit code.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    if args.command == "upload":
        upload_model(args)
    elif args.command == "deploy":
        deploy_model(args)
    elif args.command == "undeploy":
        undeploy_model(args)
    else:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
