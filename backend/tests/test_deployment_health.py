from __future__ import annotations

import json

import pytest

from control_center.deployment_health import (
    BaselineSource,
    DependencyRelationship,
    DeploymentHealthUnavailable,
    EvidenceSource,
    ServiceCategory,
    load_compose_file,
    parse_compose_text,
    parse_image_reference,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VALID_COMPOSE = """
services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: super-secret-value
    healthcheck:
      test: ["CMD", "true"]

  auth-service:
    image: ghcr.io/omnibioai/omnibioai-auth:latest
    build:
      context: ${MACHINE_DIR}/omnibioai-auth
    environment:
      JWT_SECRET: another-secret-value
      AUTH_TOKEN: token-value
    ports:
      - "8080:8000"
    depends_on:
      mysql:
        condition: service_healthy

  api-gateway:
    image: ghcr.io/omnibioai/omnibioai-api-gateway:latest
    depends_on:
      - auth-service

  celery-worker:
    build:
      context: ${MACHINE_DIR}/omnibioai-workbench
      dockerfile: Dockerfile.app
    depends_on:
      mysql:
        condition: service_started

  web-ui:
    build:
      context: .
      dockerfile: Dockerfile.web

  mystery-service:
    image: some-registry.example.com/unrelated/thing:1.2.3
"""


def _service(inventory, service_id):
    return next(s for s in inventory.services if s.service_id == service_id)


def _dep(inventory, from_service, to_service):
    return next(
        d for d in inventory.dependencies if d.from_service == from_service and d.to_service == to_service
    )


# ---------------------------------------------------------------------------
# Valid parsing / inventory shape
# ---------------------------------------------------------------------------


def test_valid_compose_parses_all_services():
    inventory = parse_compose_text(_VALID_COMPOSE, deployment_repository="omnibioai-studio")
    ids = {s.service_id for s in inventory.services}
    assert ids == {
        "mysql", "auth-service", "api-gateway", "celery-worker", "web-ui", "mystery-service",
    }
    assert inventory.warnings == ()


def test_service_inventory_fields():
    inventory = parse_compose_text(_VALID_COMPOSE)
    auth = _service(inventory, "auth-service")
    assert auth.display_name == "Auth Service"
    assert auth.build_configured is True
    assert auth.healthcheck_configured is False
    assert auth.ports == (8000,)
    assert auth.dependency_count == 1


def test_healthcheck_and_build_flags():
    inventory = parse_compose_text(_VALID_COMPOSE)
    mysql = _service(inventory, "mysql")
    assert mysql.healthcheck_configured is True
    assert mysql.build_configured is False


def test_baseline_source_recorded():
    inventory = parse_compose_text(_VALID_COMPOSE, baseline_source=BaselineSource.RELEASE)
    assert inventory.baseline_source is BaselineSource.RELEASE
    default_inventory = parse_compose_text(_VALID_COMPOSE)
    assert default_inventory.baseline_source is BaselineSource.UNKNOWN


# ---------------------------------------------------------------------------
# Ownership mapping
# ---------------------------------------------------------------------------


def test_ownership_from_build_context_wins_evidence_tier():
    inventory = parse_compose_text(_VALID_COMPOSE)
    auth = _service(inventory, "auth-service")
    assert auth.repository == "omnibioai-auth"
    assert auth.ownership_evidence.source is EvidenceSource.COMPOSE_BUILD_CONTEXT


def test_ownership_from_image_when_no_build_context():
    inventory = parse_compose_text(_VALID_COMPOSE)
    gateway = _service(inventory, "api-gateway")
    assert gateway.repository == "omnibioai-api-gateway"
    assert gateway.ownership_evidence.source is EvidenceSource.COMPOSE_IMAGE


def test_ownership_from_static_mapping_fallback():
    compose = """
services:
  toolserver:
    image: ghcr.io/some-other-org/toolserver:latest
"""
    inventory = parse_compose_text(compose)
    toolserver = _service(inventory, "toolserver")
    assert toolserver.repository == "omnibioai-toolserver"
    assert toolserver.ownership_evidence.source is EvidenceSource.STATIC_OWNERSHIP_MAPPING


def test_ownership_via_dockerfile_path_segment():
    compose = """
services:
  rag:
    build:
      context: ${MACHINE_DIR}
      dockerfile: omnibioai-rag/Dockerfile
"""
    inventory = parse_compose_text(compose)
    rag = _service(inventory, "rag")
    assert rag.repository == "omnibioai-rag"
    assert rag.ownership_evidence.source is EvidenceSource.COMPOSE_BUILD_CONTEXT


def test_ownership_relative_build_context_uses_deployment_repository():
    inventory = parse_compose_text(_VALID_COMPOSE, deployment_repository="omnibioai-studio")
    web_ui = _service(inventory, "web-ui")
    assert web_ui.repository == "omnibioai-studio"
    assert "omnibioai-studio" in web_ui.ownership_evidence.detail


def test_ownership_relative_build_context_without_deployment_repository_is_unknown():
    inventory = parse_compose_text(_VALID_COMPOSE)  # no deployment_repository supplied
    web_ui = _service(inventory, "web-ui")
    assert web_ui.repository is None
    assert web_ui.ownership_evidence is None
    assert web_ui.completeness.repository_known is False


def test_unknown_ownership_stays_unknown_not_guessed():
    inventory = parse_compose_text(_VALID_COMPOSE)
    mystery = _service(inventory, "mystery-service")
    assert mystery.repository is None
    assert mystery.ownership_evidence is None
    assert mystery.completeness.repository_known is False


def test_ownership_never_invents_human_owner():
    inventory = parse_compose_text(_VALID_COMPOSE)
    for service in inventory.services:
        assert service.repository is None or service.repository.startswith("omnibioai-")


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def test_known_category_resolved():
    inventory = parse_compose_text(_VALID_COMPOSE)
    assert _service(inventory, "mysql").category is ServiceCategory.DATABASE_STORAGE
    assert _service(inventory, "auth-service").category is ServiceCategory.SECURITY
    assert _service(inventory, "api-gateway").category is ServiceCategory.CONTROL_PLANE


def test_unrecognized_service_id_category_is_unknown_not_guessed():
    inventory = parse_compose_text(_VALID_COMPOSE)
    mystery = _service(inventory, "mystery-service")
    assert mystery.category is ServiceCategory.UNKNOWN
    assert mystery.completeness.category_known is False


# ---------------------------------------------------------------------------
# Dependency model
# ---------------------------------------------------------------------------


def test_depends_on_list_syntax_is_soft_by_default():
    inventory = parse_compose_text(_VALID_COMPOSE)
    edge = _dep(inventory, "api-gateway", "auth-service")
    assert edge.relationship is DependencyRelationship.SOFT
    assert edge.evidence.source is EvidenceSource.COMPOSE_DEPENDS_ON


def test_depends_on_mapping_syntax_service_healthy_is_hard():
    inventory = parse_compose_text(_VALID_COMPOSE)
    edge = _dep(inventory, "auth-service", "mysql")
    assert edge.relationship is DependencyRelationship.HARD


def test_depends_on_mapping_syntax_service_started_is_soft():
    inventory = parse_compose_text(_VALID_COMPOSE)
    edge = _dep(inventory, "celery-worker", "mysql")
    assert edge.relationship is DependencyRelationship.SOFT


def test_depends_on_completed_successfully_is_hard():
    compose = """
services:
  deploy-verify:
    image: python:3.12-slim
  workbench:
    build:
      context: ${MACHINE_DIR}/omnibioai-workbench
    depends_on:
      deploy-verify:
        condition: service_completed_successfully
"""
    inventory = parse_compose_text(compose)
    edge = _dep(inventory, "workbench", "deploy-verify")
    assert edge.relationship is DependencyRelationship.HARD


def test_dependency_evidence_present_on_every_edge():
    inventory = parse_compose_text(_VALID_COMPOSE)
    assert len(inventory.dependencies) == 3
    for edge in inventory.dependencies:
        assert edge.evidence.source is EvidenceSource.COMPOSE_DEPENDS_ON
        assert edge.to_service in edge.evidence.detail


def test_depends_on_does_not_infer_from_coexistence():
    # web-ui and mystery-service share no depends_on -- no edge invented.
    inventory = parse_compose_text(_VALID_COMPOSE)
    pairs = {(d.from_service, d.to_service) for d in inventory.dependencies}
    assert ("web-ui", "mystery-service") not in pairs
    assert ("mystery-service", "web-ui") not in pairs


def test_unknown_dependency_target_recorded_with_warning_not_failure():
    compose = """
services:
  a:
    image: something
    depends_on:
      - b
"""
    inventory = parse_compose_text(compose)
    assert len(inventory.dependencies) == 1
    assert inventory.dependencies[0].to_service == "b"
    assert any("unknown_dependency_target" in w for w in inventory.warnings)


def test_malformed_depends_on_marks_dependencies_unknown():
    compose = """
services:
  a:
    image: something
    depends_on: "not-a-list-or-mapping"
"""
    inventory = parse_compose_text(compose)
    service = _service(inventory, "a")
    assert service.completeness.dependencies_known is False
    assert service.dependency_count == 0
    assert "dependencies" in service.completeness.missing_fields


def test_malformed_depends_on_mapping_value_recorded_with_warning():
    compose = """
services:
  a:
    image: something
  b:
    image: something
    depends_on:
      a: "not-a-mapping-either"
"""
    inventory = parse_compose_text(compose)
    service = _service(inventory, "b")
    # still produces an edge (SOFT, condition unknown), just flags the anomaly
    assert service.dependency_count == 1
    assert any("malformed_depends_on:b" in w for w in inventory.warnings)


def test_malformed_depends_on_list_entry_skipped_with_warning():
    compose = """
services:
  a:
    image: something
    depends_on:
      - 42
"""
    inventory = parse_compose_text(compose)
    service = _service(inventory, "a")
    assert service.dependency_count == 0
    assert any("malformed_depends_on" in w for w in inventory.warnings)


# ---------------------------------------------------------------------------
# Image / tag parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected_registry,expected_repository,expected_tag,expected_digest",
    [
        ("mysql:8.0", None, "mysql", "8.0", None),
        ("omnibioai/omnibioai-auth:latest", None, "omnibioai/omnibioai-auth", "latest", None),
        ("ghcr.io/omnibioai/omnibioai-auth:1.2.3", "ghcr.io", "omnibioai/omnibioai-auth", "1.2.3", None),
        ("localhost:5000/myimage:dev", "localhost:5000", "myimage", "dev", None),
    ],
)
def test_image_reference_parsing(raw, expected_registry, expected_repository, expected_tag, expected_digest):
    ref = parse_image_reference(raw)
    assert ref.registry == expected_registry
    assert ref.repository == expected_repository
    assert ref.tag == expected_tag
    assert ref.digest == expected_digest
    assert ref.raw == raw


def test_digest_image_reference():
    ref = parse_image_reference(
        "ghcr.io/omnibioai/omnibioai-auth@sha256:" + "a" * 64
    )
    assert ref.digest == "sha256:" + "a" * 64
    assert ref.tag is None
    assert ref.is_untagged is False  # pinned by digest, not "unknown version"


def test_untagged_image_reference():
    ref = parse_image_reference("postgres")
    assert ref.tag is None
    assert ref.is_untagged is True
    assert ref.is_latest_tag is False


def test_latest_tag_not_treated_as_verified():
    ref = parse_image_reference("ghcr.io/omnibioai/omnibioai-api-gateway:latest")
    assert ref.tag == "latest"
    assert ref.is_latest_tag is True
    # "latest" is still just a string tag, not evidence of a real version.


def test_variable_containing_image_reference_does_not_crash():
    ref = parse_image_reference("myimage:${TAG}")
    assert ref.has_variable is True
    assert ref.tag == "${TAG}"

    ref_whole = parse_image_reference("${SOME_IMAGE}")
    assert ref_whole.has_variable is True
    assert ref_whole.repository == "${SOME_IMAGE}"


def test_image_metadata_on_service_reflects_tag_parsing():
    inventory = parse_compose_text(_VALID_COMPOSE)
    mysql = _service(inventory, "mysql")
    assert mysql.image.repository == "mysql"
    assert mysql.image.tag == "8.0"


def test_ports_extraction_handles_int_dict_and_string_forms():
    compose = """
services:
  a:
    image: something
    ports:
      - 9000
      - "127.0.0.1:9001:9002"
      - target: 9003
        published: 9004
      - "not-a-port"
      - null
      - true
"""
    inventory = parse_compose_text(compose)
    service = _service(inventory, "a")
    assert service.ports == (9000, 9002, 9003)


def test_ports_extraction_ignores_non_list_value():
    compose = """
services:
  a:
    image: something
    ports: "not-a-list"
"""
    inventory = parse_compose_text(compose)
    assert _service(inventory, "a").ports == ()


def test_build_shorthand_string_form_used_for_ownership_and_build_configured():
    compose = """
services:
  a:
    build: ${MACHINE_DIR}/omnibioai-a
"""
    inventory = parse_compose_text(compose)
    service = _service(inventory, "a")
    assert service.build_configured is True
    assert service.repository == "omnibioai-a"


# ---------------------------------------------------------------------------
# Security / redaction
# ---------------------------------------------------------------------------


def _flatten_strings(obj) -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for value in obj.values():
            out.extend(_flatten_strings(value))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_flatten_strings(item))
    elif isinstance(obj, str):
        out.append(obj)
    return out


_FORBIDDEN_MARKERS = (
    "super-secret-value", "another-secret-value", "token-value",
    "MYSQL_ROOT_PASSWORD", "JWT_SECRET", "AUTH_TOKEN",
)


def test_serialized_output_excludes_environment_and_secret_values():
    inventory = parse_compose_text(_VALID_COMPOSE, deployment_repository="omnibioai-studio")
    payload = json.dumps(inventory.to_public_dict())
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in payload


def test_serialized_output_excludes_absolute_developer_paths_with_no_repo_segment():
    compose = """
services:
  weird:
    build:
      context: /home/manish/Desktop/machine/some-private-tree
      dockerfile: Dockerfile
"""
    inventory = parse_compose_text(compose, deployment_repository="omnibioai-studio")
    payload = json.dumps(inventory.to_public_dict())
    assert "/home/manish" not in payload
    weird = _service(inventory, "weird")
    # Absolute (non-relative) context with no omnibioai-* segment -> UNKNOWN,
    # never silently attributed to the deployment repo (that fallback is only
    # for genuinely relative contexts).
    assert weird.repository is None


def test_absolute_path_containing_repo_segment_is_normalized_not_leaked():
    # An absolute build context can still supply ownership evidence via its
    # omnibioai-<name> segment (section 11: "may help determine repository
    # ownership internally"), but the raw absolute path string itself must
    # never appear anywhere in the serialized output -- only the matched,
    # normalized repository name.
    compose = """
services:
  weird:
    build:
      context: /home/manish/Desktop/machine/omnibioai-weird
      dockerfile: Dockerfile
"""
    inventory = parse_compose_text(compose)
    payload = json.dumps(inventory.to_public_dict())
    assert "/home/manish" not in payload
    weird = _service(inventory, "weird")
    assert weird.repository == "omnibioai-weird"


def test_serialized_output_excludes_container_ids_and_backend_handles():
    inventory = parse_compose_text(_VALID_COMPOSE, deployment_repository="omnibioai-studio")
    payload = json.dumps(inventory.to_public_dict())
    for marker in ("container_id", "backend_handle", "slurm", "job_id"):
        assert marker not in payload.lower()


def test_to_public_dict_is_allowlisted_not_recursive_environment_dump():
    inventory = parse_compose_text(_VALID_COMPOSE)
    auth = _service(inventory, "auth-service").to_public_dict()
    assert set(auth.keys()) == {
        "service_id", "display_name", "category", "repository", "ownership_evidence",
        "image", "build_configured", "healthcheck_configured", "ports",
        "dependency_count", "evidence", "completeness",
    }


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_missing_compose_file_raises_typed_error(tmp_path):
    with pytest.raises(DeploymentHealthUnavailable) as excinfo:
        load_compose_file(tmp_path / "does-not-exist.yml")
    assert excinfo.value.code == "compose_not_found"


def test_malformed_yaml_raises_typed_error():
    with pytest.raises(DeploymentHealthUnavailable) as excinfo:
        parse_compose_text("services: [this is not: valid: yaml: -")
    assert excinfo.value.code == "invalid_yaml"


def test_root_not_mapping_raises_typed_error():
    with pytest.raises(DeploymentHealthUnavailable) as excinfo:
        parse_compose_text("- just\n- a\n- list\n")
    assert excinfo.value.code == "root_not_mapping"


def test_services_key_not_a_mapping_raises_typed_error():
    with pytest.raises(DeploymentHealthUnavailable) as excinfo:
        parse_compose_text("services: not-a-mapping\n")
    assert excinfo.value.code == "invalid_services_key"


def test_missing_services_key_returns_empty_inventory_not_error():
    inventory = parse_compose_text("version: '3.8'\n")
    assert inventory.services == ()
    assert "missing_services_key" in inventory.warnings


def test_empty_services_returns_empty_inventory_with_warning():
    inventory = parse_compose_text("services: {}\n")
    assert inventory.services == ()
    assert "empty_services" in inventory.warnings


def test_empty_document_returns_empty_inventory():
    inventory = parse_compose_text("")
    assert inventory.services == ()
    assert "empty_document" in inventory.warnings


def test_invalid_service_definition_skipped_with_warning():
    compose = """
services:
  good:
    image: mysql:8.0
  bad: null
"""
    inventory = parse_compose_text(compose)
    ids = {s.service_id for s in inventory.services}
    assert ids == {"good"}
    assert any("invalid_service_definition:bad" in w for w in inventory.warnings)


def test_load_compose_file_reads_explicit_path(tmp_path):
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(_VALID_COMPOSE, encoding="utf-8")
    inventory = load_compose_file(compose_path, deployment_repository="omnibioai-studio")
    assert len(inventory.services) == 6


# ---------------------------------------------------------------------------
# Determinism / completeness
# ---------------------------------------------------------------------------


def test_serialization_is_deterministic():
    first = parse_compose_text(_VALID_COMPOSE, deployment_repository="omnibioai-studio").to_public_dict()
    second = parse_compose_text(_VALID_COMPOSE, deployment_repository="omnibioai-studio").to_public_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_metadata_completeness_known_service():
    inventory = parse_compose_text(_VALID_COMPOSE)
    auth = _service(inventory, "auth-service")
    assert auth.completeness.is_complete is True
    assert auth.completeness.missing_fields == ()


def test_metadata_completeness_partial_service():
    inventory = parse_compose_text(_VALID_COMPOSE)
    mystery = _service(inventory, "mystery-service")
    assert mystery.completeness.is_complete is False
    assert set(mystery.completeness.missing_fields) == {"repository", "category"}
