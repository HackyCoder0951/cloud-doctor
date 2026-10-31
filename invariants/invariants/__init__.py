"""Cloud Doctor Layer 1 invariants. Standard library only (PyYAML is optional, see yaml_loader)."""
from .canonical import canonical_json, plan_hash, sha256_tag, sign_envelope, verify_envelope
from .catalog import Catalog, CatalogError
from .compose import INVARIANTS_VERSION, compose_decision
from .context import PolicyContext, ValidationResult
from .rules import RULE_IDS, approval_valid, catalogue_risk, parse_timestamp, validate_plan

__version__ = "inv-0.1"

__all__ = [
    "__version__", "canonical_json", "sha256_tag", "plan_hash", "sign_envelope", "verify_envelope",
    "Catalog", "CatalogError", "PolicyContext", "ValidationResult", "validate_plan", "compose_decision",
    "RULE_IDS", "approval_valid", "catalogue_risk", "parse_timestamp", "INVARIANTS_VERSION",
]
