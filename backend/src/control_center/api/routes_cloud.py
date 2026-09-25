from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from control_center.core.auth import infra_viewer
from control_center.core.public_view import public_cloud

router = APIRouter()


@router.get("/cloud")
def get_cloud(full: bool = Depends(infra_viewer)) -> JSONResponse:
    # Region/queue/account/project/context/host are operator detail; the
    # public dashboard gets label + configured only (core/public_view.py).
    data = {
        "aws": {
            "label": "AWS Batch",
            "configured": bool(os.environ.get("AWS_ACCESS_KEY_ID") or
                               os.environ.get("AWS_BATCH_JOB_QUEUE")),
            "region": os.environ.get("AWS_DEFAULT_REGION", ""),
            "queue": os.environ.get("AWS_BATCH_JOB_QUEUE", ""),
        },
        "azure": {
            "label": "Azure Batch",
            "configured": bool(os.environ.get("AZURE_BATCH_ACCOUNT_NAME") or
                               os.environ.get("AZURE_CLIENT_ID")),
            "account": os.environ.get("AZURE_BATCH_ACCOUNT_NAME", ""),
        },
        "gcp": {
            "label": "Google Cloud Batch",
            "configured": bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or
                               os.environ.get("GCP_PROJECT")),
            "project": os.environ.get("GCP_PROJECT", ""),
            "region": os.environ.get("GCP_REGION", ""),
        },
        "kubernetes": {
            "label": "Kubernetes",
            "configured": bool(os.environ.get("KUBECONFIG") or
                               os.environ.get("KUBERNETES_SERVICE_HOST")),
            "context": os.environ.get("KUBE_CONTEXT", ""),
        },
        "local": {
            "label": "Local Docker",
            "configured": True,
            "note": "Always available",
        },
        "slurm": {
            "label": "Slurm HPC",
            "configured": bool(os.environ.get("SLURM_HOST") or
                               os.environ.get("HPC_HOST")),
            "host": os.environ.get("SLURM_HOST") or os.environ.get("HPC_HOST", ""),
        },
    }
    return JSONResponse(data if full else public_cloud(data))
