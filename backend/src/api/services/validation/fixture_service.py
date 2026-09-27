"""Version-controlled task and artifact fixtures for Basil Validation."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.runtime.validation_profile import ValidationRuntimeProfile
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_provider_run_service import (
    AgentTaskProviderRunService,
)


class ValidationFixtureService:
    """Seeds only session-owned records and documents."""

    pdf_fixture_id = "validation-pdf-live"
    html_fixture_id = "validation-html-live"
    local_preview_fixture_id = "validation-local-preview"
    local_preview_artifact_id = "validation-index"
    run_history_fixture_id = "validation-run-history-root"
    managed_history_fixture_id = "validation-managed-history"

    def __init__(
        self,
        profile: ValidationRuntimeProfile,
        knowledge_service: SQLiteKnowledgeService,
    ) -> None:
        self.profile = profile
        self.knowledge_service = knowledge_service
        self.documents_root = profile.fixtures_root / "documents"
        self.manifest_path = profile.fixtures_root / "fixture-manifest.json"
        self._provider_interaction_tasks: dict[str, asyncio.Task] = {}

    async def seed(self) -> dict[str, Any]:
        self.profile.ensure_directories()
        self.documents_root.mkdir(parents=True, exist_ok=True)
        existing_manifest = (
            json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if self.manifest_path.exists()
            else {}
        )
        revision = int(existing_manifest.get("pdfRevision", 1))
        html_revision = int(existing_manifest.get("htmlRevision", 1))
        local_preview_revision = int(existing_manifest.get("localPreviewRevision", 1))
        documents = self._write_documents(
            revision=revision,
            html_revision=html_revision,
            local_preview_revision=local_preview_revision,
        )
        for fixture in self._fixture_definitions(documents):
            existing = await self.knowledge_service.agent_task_service.get_agent_task(
                fixture["id"]
            )
            if existing is not None:
                continue
            await self.knowledge_service.agent_task_service.store_agent_task(
                agent_task_id=fixture["id"],
                original_prompt=fixture["prompt"],
                transcribed_prompt=fixture["prompt"],
                status=fixture["status"],
                root_task_id=fixture.get("root_task_id"),
                previous_task_id=fixture.get("previous_task_id"),
                chain_sequence_number=fixture.get("chain_sequence_number", 0),
                title=fixture["title"],
                app_name="Basil Validation",
                origin_type="validation_fixture",
            )
            await self.knowledge_service.agent_task_service.update_agent_task_status(
                fixture["id"],
                fixture["status"],
                result_data=fixture["result_data"],
            )
            await self.knowledge_service.agent_task_service.update_execution_timeline(
                fixture["id"],
                fixture["timeline"],
            )

        manifest = {
            "fixtureIDs": [fixture["id"] for fixture in self._fixture_definitions(documents)],
            "pdfFixtureID": self.pdf_fixture_id,
            "pdfPath": str(documents["pdf"]),
            "pdfRevision": revision,
            "htmlFixtureID": self.html_fixture_id,
            "htmlPath": str(documents["html"]),
            "htmlRevision": html_revision,
            "localPreviewFixtureID": self.local_preview_fixture_id,
            "localPreviewArtifactID": self.local_preview_artifact_id,
            "localPreviewPath": str(documents["local_preview_html"]),
            "localPreviewRevision": local_preview_revision,
            "managedHistoryPath": str(documents["managed_history"]),
            "managedHistoryHTMLPath": str(documents["managed_history_html"]),
            "seededAt": datetime.now(timezone.utc).isoformat(),
        }
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    async def mutate(self, fixture_id: str) -> dict[str, Any]:
        if fixture_id not in {
            self.pdf_fixture_id,
            self.html_fixture_id,
            self.local_preview_fixture_id,
            self.managed_history_fixture_id,
        }:
            raise ValueError("Unknown validation fixture.")
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if fixture_id == self.managed_history_fixture_id:
            return await self._mutate_managed_history_fixture(manifest)
        if fixture_id == self.html_fixture_id:
            revision = int(manifest["htmlRevision"]) + 1
            target = Path(manifest["htmlPath"])
            temporary = target.with_suffix(".replacement.html")
            temporary.write_text(_html_fixture_document(revision), encoding="utf-8")
            os.replace(temporary, target)
            manifest["htmlRevision"] = revision
            manifest["mutatedAt"] = datetime.now(timezone.utc).isoformat()
            self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            return {
                "fixtureID": fixture_id,
                "path": str(target),
                "revision": revision,
            }
        if fixture_id == self.local_preview_fixture_id:
            revision = int(manifest["localPreviewRevision"]) + 1
            target = Path(manifest["localPreviewPath"])
            temporary = target.with_suffix(".replacement.html")
            temporary.write_text(
                _local_preview_fixture_document(revision),
                encoding="utf-8",
            )
            os.replace(temporary, target)
            manifest["localPreviewRevision"] = revision
            manifest["mutatedAt"] = datetime.now(timezone.utc).isoformat()
            self.manifest_path.write_text(
                json.dumps(manifest, indent=2),
                encoding="utf-8",
            )
            return {
                "fixtureID": fixture_id,
                "path": str(target),
                "revision": revision,
            }
        revision = int(manifest["pdfRevision"]) + 1
        target = Path(manifest["pdfPath"])
        temporary = target.with_suffix(".replacement.pdf")
        temporary.write_bytes(_two_page_pdf_bytes(f"Live PDF revision {revision}"))
        os.replace(temporary, target)
        manifest["pdfRevision"] = revision
        manifest["mutatedAt"] = datetime.now(timezone.utc).isoformat()
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {
            "fixtureID": fixture_id,
            "path": str(target),
            "revision": revision,
        }

    async def _mutate_managed_history_fixture(self, manifest: dict[str, Any]) -> dict[str, Any]:
        from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.blob_store import (
            ManagedHistoryBlobStore,
        )
        from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.managed_file_history_service import (
            ManagedFileHistoryService,
        )
        from api.services.agent_processing.tools.direct_application_interactions.file_system.text_file_write import (
            LocalTextFileWriter,
        )

        target = Path(manifest["managedHistoryPath"])
        html_target = Path(manifest["managedHistoryHTMLPath"])
        service = ManagedFileHistoryService(
            db_path=self.knowledge_service.db_path,
            blob_store=ManagedHistoryBlobStore(self.profile.data_root / "managed_file_history" / "blobs"),
            text_writer=LocalTextFileWriter([self.profile.fixtures_root]),
        )
        existing_versions = await service.list_versions(str(target.resolve()))
        next_version = len(existing_versions) + 2
        result = await service.apply_managed_write(
            root_task_id=self.managed_history_fixture_id,
            agent_task_id=self.managed_history_fixture_id,
            path=str(target),
            content=f"Managed history fixture v{next_version}\n",
            mode="overwrite",
        )
        if not result.get("success"):
            raise RuntimeError(f"Managed history fixture mutation failed: {result.get('error')}")
        html_result = await service.apply_managed_write(
            root_task_id=self.managed_history_fixture_id,
            agent_task_id=self.managed_history_fixture_id,
            path=str(html_target),
            content=_managed_history_html_fixture_document(next_version),
            mode="overwrite",
        )
        if not html_result.get("success"):
            raise RuntimeError(f"Managed history HTML fixture mutation failed: {html_result.get('error')}")
        manifest["mutatedAt"] = datetime.now(timezone.utc).isoformat()
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {
            "fixtureID": self.managed_history_fixture_id,
            "path": str(target),
            "htmlPath": str(html_target),
            "version": next_version,
        }

    def probe(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {"ready": False, "reason": "fixtures_not_seeded"}
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return {
            "ready": True,
            "pdfFixtureID": manifest["pdfFixtureID"],
            "pdfPath": manifest["pdfPath"],
            "pdfRevision": manifest["pdfRevision"],
            "htmlFixtureID": manifest["htmlFixtureID"],
            "htmlPath": manifest["htmlPath"],
            "htmlRevision": manifest["htmlRevision"],
            "localPreviewFixtureID": manifest["localPreviewFixtureID"],
            "localPreviewArtifactID": manifest["localPreviewArtifactID"],
            "localPreviewPath": manifest["localPreviewPath"],
            "localPreviewRevision": manifest["localPreviewRevision"],
            "managedHistoryPath": manifest.get("managedHistoryPath"),
        }

    async def start_provider_interaction_fixture(
        self,
        *,
        scenario: str,
        routing_service: Any,
    ) -> dict[str, str]:
        """Launch one session-owned ACP interaction fixture through the live routing path."""

        fixture_modes = {
            "form": "elicitation_before_prompt_response",
            "permission": "permission_request_before_prompt_response",
        }
        try:
            fixture_mode = fixture_modes[scenario]
        except KeyError as error:
            raise ValueError("Unknown provider interaction validation scenario.") from error

        fixture_id = f"validation-provider-{scenario}-{uuid.uuid4().hex}"
        workspace_root = self.profile.fixtures_root / fixture_id / "workspace"
        workspace_root.mkdir(parents=True, exist_ok=False)
        await self.knowledge_service.agent_task_service.store_agent_task(
            agent_task_id=fixture_id,
            original_prompt=f"Run the isolated provider {scenario} interaction fixture.",
            transcribed_prompt=f"Run the isolated provider {scenario} interaction fixture.",
            status="processing",
            root_task_id=fixture_id,
            title=f"Provider interaction validation: {scenario}",
            app_name="Basil Validation",
            origin_type="validation_fixture",
        )
        profile = await self.knowledge_service.provider_profile_repository.create_profile(
            display_name=f"Validation ACP {scenario} fixture",
            launch_argv=(
                sys.executable,
                "-m",
                "api.services.agent_providers.testing.process_fixture",
                "--fixture-mode",
                fixture_mode,
            ),
            environment_allowlist=("PYTHONPATH",),
        )
        grant = await self.knowledge_service.provider_profile_repository.grant_workspace(
            provider_profile_id=str(profile["id"]),
            canonical_workspace_root=str(workspace_root),
        )
        record = await self.knowledge_service.get_agent_task(fixture_id)
        if record is None:
            raise RuntimeError("Validation provider fixture task was not persisted.")

        provider_run_service = AgentTaskProviderRunService(
            provider_profile_repository=self.knowledge_service.provider_profile_repository,
            provider_run_repository=self.knowledge_service.provider_run_repository,
            provider_interaction_repository=self.knowledge_service.provider_interaction_repository,
            routing_service=routing_service,
        )
        task = asyncio.create_task(
            provider_run_service.run_provider_task(
                agent_task_id=fixture_id,
                agent_task_record=record,
                provider_target={
                    "provider_profile_id": str(profile["id"]),
                    "workspace_grant_id": str(grant["id"]),
                    "candidate_workspace_path": str(workspace_root),
                },
            )
        )
        self._provider_interaction_tasks[fixture_id] = task
        task.add_done_callback(
            lambda completed_task: self._provider_interaction_tasks.pop(fixture_id, None)
        )
        return {
            "agentTaskID": fixture_id,
            "scenario": scenario,
            "workspaceRoot": str(workspace_root),
        }

    def _write_documents(
        self,
        revision: int,
        html_revision: int = 1,
        local_preview_revision: int = 1,
    ) -> dict[str, Path]:
        self.documents_root.mkdir(parents=True, exist_ok=True)
        documents = {
            "markdown": self.documents_root / "run-summary.md",
            "text": self.documents_root / "notes.txt",
            "code": self.documents_root / "preview.py",
            "html": self.documents_root / "report.html",
            "html_css": self.documents_root / "report.css",
            "html_js": self.documents_root / "report.js",
            "local_preview_html": self.documents_root / "local-preview" / "index.html",
            "local_preview_css": self.documents_root / "local-preview" / "app.css",
            "local_preview_js": self.documents_root / "local-preview" / "app.js",
            "local_preview_server": self.documents_root / "local-preview" / "server.py",
            "pdf": self.documents_root / "live-preview.pdf",
            "managed_history": self.documents_root / "managed-history-fixture.txt",
            "managed_history_html": self.documents_root / "managed-history-html-fixture.html",
        }
        if not documents["markdown"].exists():
            documents["markdown"].write_text("# Validation run\n\nThis is a session-owned Markdown fixture.", encoding="utf-8")
        if not documents["text"].exists():
            documents["text"].write_text("Session-owned plain-text preview fixture.\n", encoding="utf-8")
        if not documents["code"].exists():
            documents["code"].write_text("def validation_fixture() -> str:\n    return 'ready'\n", encoding="utf-8")
        if not documents["managed_history"].exists():
            documents["managed_history"].write_text("Managed history fixture v1\n", encoding="utf-8")
        if not documents["managed_history_html"].exists():
            documents["managed_history_html"].write_text(
                _managed_history_html_fixture_document(1),
                encoding="utf-8",
            )
        documents["html"].write_text(_html_fixture_document(html_revision), encoding="utf-8")
        documents["html_css"].write_text(_html_fixture_stylesheet(), encoding="utf-8")
        documents["html_js"].write_text(_html_fixture_javascript(), encoding="utf-8")
        documents["local_preview_html"].parent.mkdir(parents=True, exist_ok=True)
        documents["local_preview_html"].write_text(
            _local_preview_fixture_document(local_preview_revision),
            encoding="utf-8",
        )
        documents["local_preview_css"].write_text(
            _local_preview_fixture_stylesheet(),
            encoding="utf-8",
        )
        documents["local_preview_js"].write_text(
            _local_preview_fixture_javascript(),
            encoding="utf-8",
        )
        if not documents["local_preview_server"].exists():
            documents["local_preview_server"].write_text(
                "from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler\n"
                "import argparse\n"
                "from pathlib import Path\n"
                "\n"
                "parser = argparse.ArgumentParser()\n"
                "parser.add_argument('--host', default='127.0.0.1')\n"
                "parser.add_argument('--port', type=int, required=True)\n"
                "args = parser.parse_args()\n"
                "root = Path(__file__).resolve().parent\n"
                "\n"
                "class Handler(SimpleHTTPRequestHandler):\n"
                "    def __init__(self, *handler_args, **handler_kwargs):\n"
                "        super().__init__(*handler_args, directory=str(root), **handler_kwargs)\n"
                "\n"
                "ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()\n",
                encoding="utf-8",
            )
        if not documents["pdf"].exists():
            documents["pdf"].write_bytes(_two_page_pdf_bytes(f"Live PDF revision {revision}"))
        return documents

    def _fixture_definitions(self, documents: dict[str, Path]) -> list[dict[str, Any]]:
        def result(
            message: str,
            outcome: str,
            files: list[Path],
        ) -> dict[str, Any]:
            return {
                "finalizer_result": {
                    "summary_text": message,
                    "result_payload": {
                        "message": message,
                        "outcome": outcome,
                        "files": [
                            {
                                "artifact_id": f"validation-{path.stem}",
                                "name": path.name,
                                "path": str(path),
                                "kind": "file",
                                "operation": "write",
                            }
                            for path in files
                        ],
                    },
                }
            }

        def managed_result(
            message: str,
            outcome: str,
            managed_files: list[tuple[Path, str]],
        ) -> dict[str, Any]:
            """Like `result`, but sets a top-level `review.kind` on each file so
            `build_file_artifact_presentation` (see
            `api/routes/agent_tasks/projections/artifact_presentation.py`) treats
            it as reviewable without requiring the legacy per-task
            revision-capture round trip that managed-history writes
            intentionally bypass. That function reads `source.get("review")`
            directly off the file dict, not off a nested `artifact` object, and
            recomputes every other artifact field itself, so only `review` needs
            to be supplied here. `managed_files` pairs each path with its review
            kind (`"text"` or `"html"`)."""
            return {
                "finalizer_result": {
                    "summary_text": message,
                    "result_payload": {
                        "message": message,
                        "outcome": outcome,
                        "files": [
                            {
                                "artifact_id": f"validation-{path.stem}",
                                "name": path.name,
                                "path": str(path),
                                "kind": "file",
                                "operation": "write",
                                "review": {
                                    "revision": 1,
                                    "revision_count": 1,
                                    "kind": review_kind,
                                    "snapshot_status": "available",
                                },
                            }
                            for path, review_kind in managed_files
                        ],
                    },
                }
            }

        def timeline(summary: str) -> list[dict[str, str]]:
            return [
                {"id": "prepare", "type": "phase", "title": "Preparing request"},
                {"id": "work", "type": "phase", "title": "Preparing approach"},
                {"id": "result", "type": "phase", "title": summary},
            ]

        return [
            {
                "id": self.run_history_fixture_id,
                "title": "Integration workflow history",
                "prompt": "Inspect the integration workflow and prepare its baseline evidence.",
                "status": "completed",
                "result_data": result(
                    "Run 1 is ready for history review.",
                    "success",
                    [documents["markdown"]],
                ),
                "timeline": timeline("Completing task"),
                "root_task_id": self.run_history_fixture_id,
                "chain_sequence_number": 0,
            },
            {
                "id": "validation-run-history-follow-up-1",
                "title": "Integration workflow history",
                "prompt": "Add the deployment constraints found during the review.",
                "status": "completed",
                "result_data": result(
                    "Run 2 is ready for history review.",
                    "success",
                    [documents["text"]],
                ),
                "timeline": timeline("Completing task"),
                "root_task_id": self.run_history_fixture_id,
                "previous_task_id": self.run_history_fixture_id,
                "chain_sequence_number": 1,
            },
            {
                "id": "validation-run-history-follow-up-2",
                "title": "Integration workflow history",
                "prompt": "Produce the final implementation brief with the reviewed evidence.",
                "status": "completed",
                "result_data": result(
                    "Run 3 is ready for history review.",
                    "success",
                    [documents["code"]],
                ),
                "timeline": timeline("Completing task"),
                "root_task_id": self.run_history_fixture_id,
                "previous_task_id": "validation-run-history-follow-up-1",
                "chain_sequence_number": 2,
            },
            {
                "id": self.pdf_fixture_id,
                "title": "Live PDF preview",
                "prompt": "Review a live-updating PDF artifact.",
                "status": "completed",
                "result_data": result("The PDF fixture is ready for review.", "success", [documents["pdf"]]),
                "timeline": timeline("Completing task"),
            },
            {
                "id": "validation-markdown",
                "title": "Markdown artifact",
                "prompt": "Review a Markdown artifact.",
                "status": "completed",
                "result_data": result("Markdown and text fixtures are ready.", "success", [documents["markdown"], documents["text"]]),
                "timeline": timeline("Completing task"),
            },
            {
                "id": "validation-source",
                "title": "Source and HTML artifacts",
                "prompt": "Review source and HTML artifacts.",
                "status": "completed",
                "result_data": result("Code and HTML fixtures are ready.", "success", [documents["code"], documents["html"]]),
                "timeline": timeline("Completing task"),
            },
            {
                "id": self.html_fixture_id,
                "title": "Live HTML preview",
                "prompt": "Review a live-updating styled HTML artifact.",
                "status": "completed",
                "result_data": result(
                    "The live HTML fixture is ready for rendered-preview review.",
                    "success",
                    [documents["html"]],
                ),
                "timeline": timeline("Completing task"),
                "root_task_id": self.html_fixture_id,
            },
            {
                "id": self.local_preview_fixture_id,
                "title": "Local web preview",
                "prompt": "Review a session-owned local web preview artifact.",
                # Kept non-terminal only when Package 6A's forced-approval-prompt
                # scenario is active: create_pending_execution_approval (see
                # execution_approvals/repository.py) can only transition an
                # agent task into 'awaiting_user_input' when its current
                # status is not already completed/failed/cancelled, so a
                # live Approve/Deny prompt can never appear against a
                # terminal fixture task. Every other validation scenario
                # (including this same fixture's static/whitelisted-command
                # steps) is unaffected and keeps the normal 'completed' seed.
                "status": "processing" if self.profile.force_approval_prompts else "completed",
                "result_data": result(
                    "The local web preview fixture is ready for static and server review.",
                    "success",
                    [documents["local_preview_html"], documents["local_preview_server"]],
                ),
                "timeline": timeline("Completing task"),
                "root_task_id": self.local_preview_fixture_id,
            },
            {
                "id": self.managed_history_fixture_id,
                "title": "Managed file history",
                "prompt": "Review a session-owned managed file history fixture.",
                "status": "completed",
                "result_data": managed_result(
                    "The managed history fixture is ready for version review and restore.",
                    "success",
                    [
                        (documents["managed_history"], "text"),
                        (documents["managed_history_html"], "html"),
                    ],
                ),
                "timeline": timeline("Completing task"),
                "root_task_id": self.managed_history_fixture_id,
            },
            {
                "id": "validation-partial",
                "title": "Partial result",
                "prompt": "Review a partial task outcome.",
                "status": "completed",
                "result_data": result("A usable partial result is available.", "partial", []),
                "timeline": timeline("Completing task"),
            },
            {
                "id": "validation-failed",
                "title": "Failed fixture",
                "prompt": "Review a failed task outcome.",
                "status": "failed",
                "result_data": {"failure_info": {"error": "Fixture failure for presentation testing."}},
                "timeline": timeline("Needs attention"),
            },
        ]


def _html_fixture_document(revision: int) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Release readiness preview</title>
<link rel="stylesheet" href="report.css">
<script defer src="report.js"></script>
</head>
<body>
<main class="workspace">
<header class="hero">
<p class="eyebrow">Basil validation fixture</p>
<h1>Release readiness dashboard</h1>
<p>Styled local HTML, linked assets, and deterministic live refresh evidence.</p>
</header>
<section class="cards" aria-label="Release metrics">
<article><span>Revision</span><output id="fixture-revision">{revision}</output></article>
<article><span>Preview health</span><strong>Rendered</strong></article>
<article><span>Updated card</span><strong>Evidence set {revision}</strong></article>
</section>
<section class="activity">
<h2>Validation activity</h2>
<ol>
<li>Loaded the linked stylesheet from the artifact directory.</li>
<li>Executed the linked JavaScript renderer marker.</li>
<li>Rendered a locally hosted document without external network access.</li>
<li>Observed revision {revision} in the already-open preview.</li>
<li>Preserved the dedicated preview window while the artifact changed.</li>
<li>Confirmed the artifact event caused a content refresh.</li>
<li>Kept the document readable at a normal desktop window size.</li>
<li>Retained enough content to prove overflow and scrolling.</li>
</ol>
</section>
</main>
</body>
</html>
"""


def _managed_history_html_fixture_document(revision: int) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Managed HTML history fixture</title>
</head>
<body>
<h1>Managed HTML history fixture</h1>
<p>Session-owned managed-history HTML artifact for detached preview version review.</p>
<output id="managed-history-html-revision">{revision}</output>
</body>
</html>
"""


def _html_fixture_javascript() -> str:
    return """document.documentElement.dataset.rendered = "true";
console.log(`BASIL_PREVIEW_RENDERED:${document.querySelector("#fixture-revision")?.textContent ?? "unknown"}`);
"""


def _local_preview_fixture_document(revision: int) -> str:
    return f"""<!doctype html>
<html lang="en" data-revision="{revision}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local preview fixture</title>
<link rel="stylesheet" href="app.css">
<script defer src="app.js"></script>
</head>
<body>
<main class="preview-workspace">
<header class="preview-hero">
<p class="preview-eyebrow">Basil validation fixture</p>
<h1>Basil local preview validation</h1>
<p>Session-owned loopback server with deterministic rendered evidence.</p>
</header>
<section class="preview-metrics" aria-label="Local preview metrics">
<article><span>Revision</span><output id="local-preview-revision">{revision}</output></article>
<article><span>Server</span><strong>Loopback only</strong></article>
<article><span>Renderer</span><strong id="rendered-at">Loading</strong></article>
</section>
<section class="preview-activity">
<h2>Rendered validation activity</h2>
<ol>
<li>Loaded this page through the approved local server.</li>
<li>Loaded a linked stylesheet and a linked JavaScript asset.</li>
<li>Emitted a deterministic console render marker.</li>
<li>Rendered revision {revision} after an artifact event refresh.</li>
<li>Kept enough content to prove ordinary overflow behavior.</li>
<li>Preserved the preview window while the artifact changed.</li>
<li>Captured a screenshot only when preview feedback was submitted.</li>
<li>Retained local loopback scope without any external network dependency.</li>
</ol>
</section>
</main>
</body>
</html>
"""


def _local_preview_fixture_stylesheet() -> str:
    return """* { box-sizing: border-box; }
body { margin: 0; color: #132442; background: #eaf2ff; font: 16px -apple-system, BlinkMacSystemFont, sans-serif; }
.preview-workspace { min-height: 100vh; padding: 40px; }
.preview-hero { padding: 32px; border-radius: 20px; color: #fff; background: linear-gradient(135deg, #062c75, #2462bd); box-shadow: 0 18px 42px rgba(6, 44, 117, 0.24); }
.preview-eyebrow { margin: 0 0 8px; color: #c9dcff; font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
h1, h2, p { margin-top: 0; }
.preview-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin: 24px 0; }
.preview-metrics article { display: grid; gap: 10px; min-height: 132px; padding: 22px; border: 1px solid #c6d8f4; border-radius: 16px; background: #fff; box-shadow: 0 8px 18px rgba(19, 54, 106, 0.09); }
.preview-metrics span { color: #4b6088; font-size: 13px; font-weight: 600; }
.preview-metrics output, .preview-metrics strong { color: #062c75; font-size: 24px; font-weight: 750; }
.preview-activity { max-width: 760px; padding: 24px; border-radius: 16px; background: #fff; box-shadow: 0 8px 18px rgba(19, 54, 106, 0.09); }
.preview-activity ol { max-height: 172px; margin: 0; overflow: auto; padding-left: 24px; }
.preview-activity li { margin: 0 0 14px; line-height: 1.45; }
@media (max-width: 700px) { .preview-workspace { padding: 20px; } .preview-metrics { grid-template-columns: 1fr; } }
"""


def _local_preview_fixture_javascript() -> str:
    return """const revision = document.documentElement.dataset.revision ?? "unknown";
document.querySelector("#rendered-at").textContent = new Date().toISOString();
document.documentElement.dataset.rendered = "true";
console.log(`BASIL_PREVIEW_RENDERED:${revision}`);
"""


def _html_fixture_stylesheet() -> str:
    return """* { box-sizing: border-box; }
body { margin: 0; color: #14213d; background: #edf4ff; font: 16px -apple-system, BlinkMacSystemFont, sans-serif; }
.workspace { min-height: 100vh; padding: 40px; }
.hero { padding: 32px; border-radius: 20px; color: #fff; background: linear-gradient(135deg, #003087, #2657b8); box-shadow: 0 18px 42px rgba(0, 48, 135, 0.22); }
.eyebrow { margin: 0 0 8px; color: #cde0ff; font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
h1, h2, p { margin-top: 0; }
.cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin: 24px 0; }
.cards article { display: grid; gap: 10px; min-height: 132px; padding: 22px; border: 1px solid #c8d8f2; border-radius: 16px; background: #fff; box-shadow: 0 8px 18px rgba(19, 54, 106, 0.09); }
.cards span { color: #4b6088; font-size: 13px; font-weight: 600; }
.cards output, .cards strong { color: #003087; font-size: 30px; font-weight: 750; }
.activity { max-width: 760px; padding: 24px; border-radius: 16px; background: #fff; box-shadow: 0 8px 18px rgba(19, 54, 106, 0.09); }
.activity ol { max-height: 172px; margin: 0; overflow: auto; padding-left: 24px; }
.activity li { margin: 0 0 14px; line-height: 1.45; }
@media (max-width: 700px) { .workspace { padding: 20px; } .cards { grid-template-columns: 1fr; } }
"""


def _two_page_pdf_bytes(label: str) -> bytes:
    """Produce a small valid two-page PDF without a runtime PDF dependency."""
    safe_label = label.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
        f"<< /Length {len(f'BT /F1 24 Tf 72 720 Td ({safe_label}) Tj ET'.encode('latin-1'))} >>\nstream\nBT /F1 24 Tf 72 720 Td ({safe_label}) Tj ET\nendstream",
        "<< /Length 42 >>\nstream\nBT /F1 18 Tf 72 720 Td (Page two) Tj ET\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, object_body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n{object_body}\nendobj\n".encode("latin-1"))
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(payload)
