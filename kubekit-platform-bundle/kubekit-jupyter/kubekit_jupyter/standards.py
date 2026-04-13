"""Platform standards surfaced via %kfp_standards.

In the real implementation this would pull from the `platform-standards`
library or a team-maintained skill file. v1 keeps it inline so the magic
works with zero setup, then migrates to external storage.
"""
from __future__ import annotations

_STANDARDS = {
    "overview": """
Welcome. This is the team's KFP platform. The fastest path from notebook to production:

    1. %kfp_walkthrough                         ← full tour if you're new
    2. %kfp_new component my_loader             ← scaffold a component cell
    3. %kfp_new component my_trainer            ← scaffold another
    4. %kfp_new pipeline my_training             ← scaffold a pipeline cell
    5. %kfp_decompile ./out/my_training          ← generate a production repo
    6. Open NEXT_STEPS.md and follow the checklist

Core conventions at a glance:

- Components are small, typed, and declare resource specs (cpu=, memory=).
- All logging goes through the platform logger, never print().
- All inputs and outputs flow through KFP artifacts, not side channels.
- Secrets come from the platform secret manager, never hardcoded.
- Every component has at least one test.

Use %kfp_standards <topic> for details. Topics: component, pipeline, resources, logging, secrets.
""",
    "component": """
KFP component conventions:

- Decorate with @dsl.component or @kubekit.component
- Every parameter must have a type annotation
- Declare cpu= and memory= in the decorator (default: 500m / 2Gi)
- Use Input[...] and Output[...] for artifacts, not string paths
- Keep components under ~200 lines; split if larger
""",
    "pipeline": """
KFP pipeline conventions:

- One @dsl.pipeline function per module
- Parameters must be typed and have reasonable defaults
- Use kubekit.submit() rather than calling the KFP client directly
- Tag every pipeline with project, owner, and model_name
- Exit handlers are required for pipelines that mutate state
""",
    "resources": """
Resource spec guidelines:

- Default: cpu='500m', memory='2Gi'
- Spark driver: cpu='2', memory='8Gi'
- Spark executor: configure via kubekit.SparkConfig, not component resources
- GPU: request via accelerator='nvidia-tesla-t4' (or newer)
- Never request more than you measured you need — platform audits for waste
""",
    "logging": """
Logging conventions:

    from kubekit.logging import get_logger
    log = get_logger(__name__)
    log.info("structured.event", foo=bar)

- Use structured fields, not formatted strings
- Never use print()
- inference-logger handles ML-specific events (predictions, features)
""",
    "secrets": """
Secrets conventions:

- Never hardcode credentials in code or notebooks
- Use kubekit.secrets.get("name") to retrieve from platform secret manager
- Secret references in YAML configs use ${SECRET_NAME} syntax
- Audit tooling flags any string literal that looks like a credential
""",
}


def get_standards(topic: str) -> str:
    return _STANDARDS.get(topic, _STANDARDS["overview"]).strip()
