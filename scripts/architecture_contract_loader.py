"""
Architecture Contract Loader — Runtime Drift Validator.

Loads the canonical runtime architecture contract from:
    architecture/runtime_architecture_contract.yaml

Scans the repository for configuration drift against the contract and
produces structured violation reports.

Validated rules:
    SB-001      Service Bus queue name default (Python config)
    SB-002      Service Bus queue name default (Bicep parameter)
    SEARCH-001  AI Search index name default (search writer factory)
    SEARCH-002  Non-canonical index name literals in scripts/
    SEARCH-003  Non-canonical index name literals in src/
    COSMOS-001  Cosmos database name default
    COSMOS-002  Cosmos state container name default
    COSMOS-003  Cosmos audit container name default
    ENVVAR-001  SEARCH_ENDPOINT vs AZURE_SEARCH_ENDPOINT inconsistency
    MSG-001     Orchestrator source must not reference purview-events

Violation output format:
    ARCHITECTURE_DRIFT_DETECTED
      Rule     : <rule_id>
      Category : <category>
      File     : <path>:<line>
      Expected : <canonical_value>
      Found    : <actual_value>
      Detail   : <description>

Usage:
    python scripts/architecture_contract_loader.py

Exit codes:
    0   All checks pass  → ARCHITECTURE_CONTRACT_PASS
    1   Violations found → ARCHITECTURE_DRIFT_DETECTED
    2   Fatal error (contract missing, YAML parse failure)
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
except ImportError:
    print(
        "FATAL: PyYAML is required.\n"
        "Install with: pip install pyyaml\n"
        "Or:           pip install -r requirements.txt"
    )
    sys.exit(2)

# ---------------------------------------------------------------------------
# Repository paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve()
REPO_ROOT: Path = _HERE.parent.parent
CONTRACT_PATH: Path = REPO_ROOT / "architecture" / "runtime_architecture_contract.yaml"


# ---------------------------------------------------------------------------
# Violation model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractViolation:
    """A single architecture contract rule violation."""

    rule_id: str
    category: str
    file: str
    line: int
    expected: str
    found: str
    description: str

    def format(self) -> str:
        """Return a structured ARCHITECTURE_DRIFT_DETECTED block."""
        return (
            "ARCHITECTURE_DRIFT_DETECTED\n"
            f"  Rule     : {self.rule_id}\n"
            f"  Category : {self.category}\n"
            f"  File     : {self.file}:{self.line}\n"
            f"  Expected : {self.expected}\n"
            f"  Found    : {self.found}\n"
            f"  Detail   : {self.description}"
        )


# ---------------------------------------------------------------------------
# Contract loader
# ---------------------------------------------------------------------------


def load_contract() -> Dict[str, Any]:
    """
    Load and parse the runtime architecture contract.

    The contract file uses '---' as section dividers, producing a
    multi-document YAML stream.  All documents are merged into a single
    dictionary so callers work with one unified mapping.

    Later documents override earlier ones on key conflicts (there are none
    in the current contract, but this is the safe merge behaviour).

    Raises:
        FileNotFoundError: Contract YAML not found at CONTRACT_PATH.
        yaml.YAMLError:    Contract file contains invalid YAML.
    """
    if not CONTRACT_PATH.exists():
        raise FileNotFoundError(
            f"Architecture contract not found: {CONTRACT_PATH}\n"
            "Ensure architecture/runtime_architecture_contract.yaml is present."
        )
    with CONTRACT_PATH.open(encoding="utf-8") as fh:
        documents = list(yaml.safe_load_all(fh))

    # Merge all non-None document dicts into a single mapping
    merged: Dict[str, Any] = {}
    for doc in documents:
        if isinstance(doc, dict):
            merged.update(doc)
    return merged


def get_canonical_names(contract: Dict[str, Any]) -> Dict[str, str]:
    """Extract canonical resource names from the contract."""
    section = contract.get("canonical_resource_names", {})
    return {
        "service_bus_queue": section.get("service_bus_queue", ""),
        "ai_search_index": section.get("ai_search_index", ""),
        "cosmos_database": section.get("cosmos_database", ""),
        "cosmos_state_container": section.get("cosmos_state_container", ""),
        "cosmos_audit_container": section.get("cosmos_audit_container", ""),
    }


# ---------------------------------------------------------------------------
# File scanning utilities
# ---------------------------------------------------------------------------


def _file_lines(path: Path) -> List[tuple[int, str]]:
    """Return (1-based lineno, line) pairs.  Empty list if file absent."""
    if not path.exists():
        return []
    return list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))


def _find_env_default(path: Path, env_var: str) -> List[tuple[int, str]]:
    """
    Locate os.environ.get(env_var, "default") in *path* and return
    (lineno, default_value) pairs.

    Handles multi-line call patterns:
        os.environ.get(
            "ENV_VAR", "default-value"
        )
    """
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    # \s* between the opening paren and the variable name catches newlines/indentation
    pattern = re.compile(
        r'os\.environ\.get\(\s*["\']'
        + re.escape(env_var)
        + r'["\'],\s*["\']([^"\']+)["\']'
    )
    results: List[tuple[int, str]] = []
    for m in pattern.finditer(content):
        lineno = content[: m.start()].count("\n") + 1
        results.append((lineno, m.group(1)))
    return results


def _find_bicep_param_default(path: Path, param_name: str) -> List[tuple[int, str]]:
    """
    Locate Bicep `param <name> <type> = '<value>'` declarations.
    Returns (lineno, default_value) pairs.
    """
    pattern = re.compile(
        r"param\s+" + re.escape(param_name) + r"\s+\w+\s*=\s*'([^']+)'"
    )
    results: List[tuple[int, str]] = []
    for lineno, line in _file_lines(path):
        m = pattern.search(line)
        if m:
            results.append((lineno, m.group(1)))
    return results


def _find_literal(path: Path, literal: str) -> List[tuple[int, str]]:
    """Return (lineno, stripped_line) pairs where *literal* appears verbatim."""
    return [
        (lineno, line.strip())
        for lineno, line in _file_lines(path)
        if literal in line
    ]


def _py_files(directory: Path) -> List[Path]:
    """All .py files under *directory*, recursively sorted."""
    if not directory.exists():
        return []
    return sorted(directory.rglob("*.py"))


# ---------------------------------------------------------------------------
# Known non-canonical AI Search index name variants
# ---------------------------------------------------------------------------

_NON_CANONICAL_INDEX_VARIANTS: frozenset[str] = frozenset(
    {
        "metadata-index-v1",
        "metadata-context-index-v1",
    }
)


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------


def _rule_sb001(canon: Dict[str, str]) -> List[ContractViolation]:
    """SB-001 — SERVICE_BUS_QUEUE_NAME Python default in config.py."""
    expected = canon["service_bus_queue"]
    path = REPO_ROOT / "src" / "orchestrator" / "config.py"
    violations: List[ContractViolation] = []
    for lineno, found in _find_env_default(path, "SERVICE_BUS_QUEUE_NAME"):
        if found != expected:
            violations.append(
                ContractViolation(
                    rule_id="SB-001",
                    category="service_bus_queue",
                    file="src/orchestrator/config.py",
                    line=lineno,
                    expected=expected,
                    found=found,
                    description=(
                        "SERVICE_BUS_QUEUE_NAME os.environ.get() default does not "
                        "match the contract canonical queue name."
                    ),
                )
            )
    return violations


def _rule_sb002(canon: Dict[str, str]) -> List[ContractViolation]:
    """SB-002 — serviceBusQueueName Bicep parameter default."""
    expected = canon["service_bus_queue"]
    path = REPO_ROOT / "infrastructure" / "bicep" / "orchestrator-app.bicep"
    violations: List[ContractViolation] = []
    for lineno, found in _find_bicep_param_default(path, "serviceBusQueueName"):
        if found != expected:
            violations.append(
                ContractViolation(
                    rule_id="SB-002",
                    category="service_bus_queue",
                    file="infrastructure/bicep/orchestrator-app.bicep",
                    line=lineno,
                    expected=expected,
                    found=found,
                    description=(
                        "Bicep serviceBusQueueName parameter default does not match "
                        "the contract canonical queue name."
                    ),
                )
            )
    return violations


def _rule_search001(canon: Dict[str, str]) -> List[ContractViolation]:
    """SEARCH-001 — SEARCH_INDEX_NAME default in search writer factory."""
    expected = canon["ai_search_index"]
    path = (
        REPO_ROOT / "src" / "infrastructure" / "search_writer" / "client_factory.py"
    )
    violations: List[ContractViolation] = []
    for lineno, found in _find_env_default(path, "SEARCH_INDEX_NAME"):
        if found != expected:
            violations.append(
                ContractViolation(
                    rule_id="SEARCH-001",
                    category="ai_search_index",
                    file="src/infrastructure/search_writer/client_factory.py",
                    line=lineno,
                    expected=expected,
                    found=found,
                    description=(
                        f"SEARCH_INDEX_NAME default '{found}' does not match the "
                        f"contract canonical index name '{expected}'. "
                        "Note: this file also uses SEARCH_ENDPOINT instead of "
                        "AZURE_SEARCH_ENDPOINT — see rule ENVVAR-001."
                    ),
                )
            )
    return violations


def _rule_search002(canon: Dict[str, str]) -> List[ContractViolation]:
    """SEARCH-002 — Non-canonical index name literals in scripts/."""
    expected = canon["ai_search_index"]
    scripts_dir = REPO_ROOT / "scripts"
    # Exclude this validator itself — it legitimately defines the variant names
    _self = Path(__file__).resolve()
    violations: List[ContractViolation] = []
    for py_file in _py_files(scripts_dir):
        if py_file.resolve() == _self:
            continue
        for variant in _NON_CANONICAL_INDEX_VARIANTS:
            for lineno, _ in _find_literal(py_file, variant):
                violations.append(
                    ContractViolation(
                        rule_id="SEARCH-002",
                        category="ai_search_index",
                        file=str(py_file.relative_to(REPO_ROOT)),
                        line=lineno,
                        expected=expected,
                        found=variant,
                        description=(
                            f"Non-canonical AI Search index name '{variant}' is "
                            f"hardcoded in a script. Contract canonical name is "
                            f"'{expected}'."
                        ),
                    )
                )
    return violations


def _rule_search003(canon: Dict[str, str]) -> List[ContractViolation]:
    """SEARCH-003 — Non-canonical index name literals in src/."""
    expected = canon["ai_search_index"]
    src_dir = REPO_ROOT / "src"
    violations: List[ContractViolation] = []
    for py_file in _py_files(src_dir):
        for variant in _NON_CANONICAL_INDEX_VARIANTS:
            for lineno, _ in _find_literal(py_file, variant):
                violations.append(
                    ContractViolation(
                        rule_id="SEARCH-003",
                        category="ai_search_index",
                        file=str(py_file.relative_to(REPO_ROOT)),
                        line=lineno,
                        expected=expected,
                        found=variant,
                        description=(
                            f"Non-canonical AI Search index name '{variant}' found "
                            f"in application source. Contract canonical name is "
                            f"'{expected}'."
                        ),
                    )
                )
    return violations


def _rule_cosmos001(canon: Dict[str, str]) -> List[ContractViolation]:
    """COSMOS-001 — COSMOS_DATABASE_NAME default."""
    expected = canon["cosmos_database"]
    path = REPO_ROOT / "src" / "orchestrator" / "config.py"
    violations: List[ContractViolation] = []
    for lineno, found in _find_env_default(path, "COSMOS_DATABASE_NAME"):
        if found != expected:
            violations.append(
                ContractViolation(
                    rule_id="COSMOS-001",
                    category="cosmos_database",
                    file="src/orchestrator/config.py",
                    line=lineno,
                    expected=expected,
                    found=found,
                    description="COSMOS_DATABASE_NAME default does not match contract.",
                )
            )
    return violations


def _rule_cosmos002(canon: Dict[str, str]) -> List[ContractViolation]:
    """COSMOS-002 — COSMOS_STATE_CONTAINER default."""
    expected = canon["cosmos_state_container"]
    path = REPO_ROOT / "src" / "orchestrator" / "config.py"
    violations: List[ContractViolation] = []
    for lineno, found in _find_env_default(path, "COSMOS_STATE_CONTAINER"):
        if found != expected:
            violations.append(
                ContractViolation(
                    rule_id="COSMOS-002",
                    category="cosmos_state_container",
                    file="src/orchestrator/config.py",
                    line=lineno,
                    expected=expected,
                    found=found,
                    description=(
                        "COSMOS_STATE_CONTAINER default does not match contract."
                    ),
                )
            )
    return violations


def _rule_cosmos003(canon: Dict[str, str]) -> List[ContractViolation]:
    """COSMOS-003 — COSMOS_AUDIT_CONTAINER default."""
    expected = canon["cosmos_audit_container"]
    path = REPO_ROOT / "src" / "orchestrator" / "config.py"
    violations: List[ContractViolation] = []
    for lineno, found in _find_env_default(path, "COSMOS_AUDIT_CONTAINER"):
        if found != expected:
            violations.append(
                ContractViolation(
                    rule_id="COSMOS-003",
                    category="cosmos_audit_container",
                    file="src/orchestrator/config.py",
                    line=lineno,
                    expected=expected,
                    found=found,
                    description=(
                        "COSMOS_AUDIT_CONTAINER default does not match contract."
                    ),
                )
            )
    return violations


def _rule_envvar001() -> List[ContractViolation]:
    """
    ENVVAR-001 — SEARCH_ENDPOINT vs AZURE_SEARCH_ENDPOINT inconsistency.

    The search writer factory reads SEARCH_ENDPOINT while the RAG pipeline
    reads AZURE_SEARCH_ENDPOINT.  Both target the same Azure AI Search service.
    This inconsistency means a deployment that sets only one variable will
    silently leave the other path unconfigured.
    """
    path = (
        REPO_ROOT / "src" / "infrastructure" / "search_writer" / "client_factory.py"
    )
    violations: List[ContractViolation] = []
    for lineno, line in _file_lines(path):
        if (
            "SEARCH_ENDPOINT" in line
            and "AZURE_SEARCH_ENDPOINT" not in line
            and (
                "os.environ" in line
                or "environ[" in line
                or "environ.get" in line
            )
        ):
            violations.append(
                ContractViolation(
                    rule_id="ENVVAR-001",
                    category="env_var_naming",
                    file="src/infrastructure/search_writer/client_factory.py",
                    line=lineno,
                    expected="AZURE_SEARCH_ENDPOINT",
                    found="SEARCH_ENDPOINT",
                    description=(
                        "Search writer reads SEARCH_ENDPOINT; RAG pipeline reads "
                        "AZURE_SEARCH_ENDPOINT. Both target the same Azure AI Search "
                        "service. Inconsistent naming creates a deployment "
                        "configuration risk: setting one does not configure the other."
                    ),
                )
            )
    return violations


def _rule_msg001() -> List[ContractViolation]:
    """
    MSG-001 — Orchestrator source must not reference purview-events.

    The orchestrator consumes only 'enrichment-requests' (contract §messaging).
    'purview-events' is the upstream event routing queue and must not appear
    in application source code.
    """
    src_dir = REPO_ROOT / "src"
    violations: List[ContractViolation] = []
    for py_file in _py_files(src_dir):
        for lineno, _ in _find_literal(py_file, "purview-events"):
            violations.append(
                ContractViolation(
                    rule_id="MSG-001",
                    category="messaging_topology",
                    file=str(py_file.relative_to(REPO_ROOT)),
                    line=lineno,
                    expected="enrichment-requests (sole consumer queue per contract)",
                    found="'purview-events' reference in src/",
                    description=(
                        "The orchestrator must consume only 'enrichment-requests'. "
                        "'purview-events' is the upstream routing queue and must not "
                        "appear in application source code."
                    ),
                )
            )
    return violations


# ---------------------------------------------------------------------------
# Main validation runner
# ---------------------------------------------------------------------------

_RULE_COUNT = 10  # SB-001, SB-002, SEARCH-001..003, COSMOS-001..003, ENVVAR-001, MSG-001


def run_validation() -> List[ContractViolation]:
    """
    Load the architecture contract and execute all validation rules.

    Returns a (possibly empty) list of ContractViolation objects.

    Raises:
        FileNotFoundError: CONTRACT_PATH does not exist.
        yaml.YAMLError:    CONTRACT_PATH contains invalid YAML.
    """
    contract = load_contract()
    canon = get_canonical_names(contract)

    violations: List[ContractViolation] = []
    violations.extend(_rule_sb001(canon))
    violations.extend(_rule_sb002(canon))
    violations.extend(_rule_search001(canon))
    violations.extend(_rule_search002(canon))
    violations.extend(_rule_search003(canon))
    violations.extend(_rule_cosmos001(canon))
    violations.extend(_rule_cosmos002(canon))
    violations.extend(_rule_cosmos003(canon))
    violations.extend(_rule_envvar001())
    violations.extend(_rule_msg001())
    return violations


def print_report(violations: List[ContractViolation]) -> None:
    """Print a structured validation report to stdout."""
    sep = "=" * 70
    print(sep)
    print("ARCHITECTURE CONTRACT VALIDATION REPORT")
    print(f"Contract  : architecture/runtime_architecture_contract.yaml")
    print(f"Rules     : {_RULE_COUNT} checks executed")
    print(sep)

    if not violations:
        print()
        print("ARCHITECTURE_CONTRACT_PASS")
        print("All rules satisfied. Repository is aligned with the contract.")
        print()
        print(sep)
        return

    print(f"\n{len(violations)} violation(s) detected:\n")
    for i, violation in enumerate(violations, start=1):
        print(f"[{i:02d}] {violation.format()}\n")

    print(sep)
    print(f"ARCHITECTURE_DRIFT_DETECTED — {len(violations)} violation(s).")
    print("Resolve all violations before deployment.")
    print(sep)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        violations = run_validation()
    except FileNotFoundError as exc:
        print(f"FATAL: {exc}")
        sys.exit(2)
    except yaml.YAMLError as exc:
        print(f"FATAL: Contract YAML parse error — {exc}")
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: Unexpected error during validation — {exc}")
        sys.exit(2)

    print_report(violations)
    sys.exit(1 if violations else 0)
