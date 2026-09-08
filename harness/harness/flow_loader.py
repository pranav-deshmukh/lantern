"""Declarative YAML loader that builds :class:`Flow` objects from YAML files."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml

from .contracts import Contract, is_base_model_type, is_union_type
from .core import Flow, Step
from .governance import ApprovalCallback, PolicyEngine, PolicyRule


class FlowLoadError(ValueError):
    """Raised when a flow YAML file cannot be loaded or its references resolved."""


def load_flow(
    yaml_path: str,
    *,
    approval_callback: ApprovalCallback | None = None,
) -> Flow:
    """Build a :class:`Flow` from a declarative YAML file.

    The YAML file contains a ``steps`` list. Each step needs a ``name`` and a
    dotted ``function`` path. Optional ``input_model`` and ``output_model``
    dotted paths attach a contract, and an optional ``governed_action``
    attaches governance using the rules in the top-level ``policies`` list.
    """
    path = Path(yaml_path)
    document = _read_document(path)

    if not isinstance(document, dict):
        raise FlowLoadError(
            f"Flow file '{path}' must contain a mapping with a 'steps' list."
        )

    raw_steps = document.get("steps")
    if not isinstance(raw_steps, list):
        raise FlowLoadError(f"Flow file '{path}' must contain a 'steps' list.")

    policy_engine = _build_policy_engine(
        document.get("policies"), path, approval_callback
    )

    steps: list[Step] = []
    for index, raw_step in enumerate(raw_steps):
        steps.append(_build_step(raw_step, index, path, policy_engine))

    return Flow(steps)


def _read_document(path: Path) -> Any:
    """Read and parse the YAML file, wrapping failures with file context."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise FlowLoadError(f"Could not read flow file '{path}': {error}") from error

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise FlowLoadError(
            f"Could not parse flow file '{path}': {error}"
        ) from error


def _build_policy_engine(
    raw_policies: Any,
    path: Path,
    approval_callback: ApprovalCallback | None,
) -> PolicyEngine | None:
    """Build a policy engine from the optional top-level ``policies`` list."""
    if raw_policies is None:
        return None

    if not isinstance(raw_policies, list):
        raise FlowLoadError(
            f"Flow file '{path}' must define 'policies' as a list of policy rules."
        )

    rules: list[PolicyRule] = []
    for index, raw_rule in enumerate(raw_policies):
        if not isinstance(raw_rule, dict):
            raise FlowLoadError(
                f"Flow file '{path}' policy at index {index} must be a mapping."
            )
        try:
            rules.append(PolicyRule(**raw_rule))
        except (TypeError, ValueError) as error:
            raise FlowLoadError(
                f"Flow file '{path}' has an invalid policy at index {index}: {error}"
            ) from error

    return PolicyEngine(rules, approval_callback)


def _build_step(
    raw_step: Any,
    index: int,
    path: Path,
    policy_engine: PolicyEngine | None,
) -> Step:
    """Build a single :class:`Step` from its YAML mapping."""
    if not isinstance(raw_step, dict):
        raise FlowLoadError(
            f"Flow file '{path}' step at index {index} must be a mapping."
        )

    name = raw_step.get("name")
    if not isinstance(name, str) or not name.strip():
        raise FlowLoadError(
            f"Flow file '{path}' step at index {index} is missing a non-empty 'name'."
        )

    function_path = raw_step.get("function")
    if not isinstance(function_path, str) or not function_path:
        raise FlowLoadError(
            f"Flow file '{path}' step '{name}' is missing a 'function' dotted path."
        )

    function = _import_dotted(
        function_path, path=path, step_name=name, kind="function"
    )
    if not callable(function):
        raise FlowLoadError(
            f"Flow file '{path}' step '{name}' function '{function_path}' is not callable."
        )

    contract = _build_contract(raw_step, name, path)
    rules_files = _resolve_context_files(
        raw_step.get("rules_files"), path, name, "rules_files"
    )
    skills_files = _resolve_context_files(
        raw_step.get("skills_files"), path, name, "skills_files"
    )

    try:
        step = Step(
            name,
            function,
            contract=contract,
            rules_files=rules_files,
            skills_files=skills_files,
        )
    except (TypeError, ValueError) as error:
        raise FlowLoadError(
            f"Flow file '{path}' step '{name}' is invalid: {error}"
        ) from error

    governed_action = raw_step.get("governed_action")
    if governed_action is not None:
        if not isinstance(governed_action, str) or not governed_action:
            raise FlowLoadError(
                f"Flow file '{path}' step '{name}' has an empty 'governed_action'."
            )
        if policy_engine is None:
            raise FlowLoadError(
                f"Flow file '{path}' step '{name}' uses 'governed_action' "
                "but no 'policies' were defined."
            )
        try:
            step = step.with_governance(governed_action, policy_engine)
        except (TypeError, ValueError) as error:
            raise FlowLoadError(
                f"Flow file '{path}' step '{name}' has invalid governance: {error}"
            ) from error

    return step


def _build_contract(raw_step: dict[str, Any], name: str, path: Path) -> Contract | None:
    """Build a contract from the optional input/output model dotted paths."""
    input_model_path = raw_step.get("input_model")
    output_model_path = raw_step.get("output_model")

    if input_model_path is None and output_model_path is None:
        return None
    if input_model_path is None or output_model_path is None:
        raise FlowLoadError(
            f"Flow file '{path}' step '{name}' must specify both 'input_model' "
            "and 'output_model' or neither."
        )

    input_model = _import_model(
        input_model_path, path, name, "input_model", allow_union=False
    )
    output_model = _import_model(
        output_model_path, path, name, "output_model", allow_union=True
    )

    try:
        return Contract(input_model, output_model)
    except TypeError as error:
        raise FlowLoadError(
            f"Flow file '{path}' step '{name}' has invalid models: {error}"
        ) from error


def _resolve_context_files(
    raw_paths: Any,
    yaml_path: Path,
    step_name: str,
    kind: str,
) -> list[str] | None:
    """Resolve and eagerly validate declared context files.

    Paths are resolved relative to the YAML file's directory (not the process
    working directory). Missing files raise immediately at load time so a bad
    flow never starts running.
    """
    if raw_paths is None:
        return None

    if not isinstance(raw_paths, list) or not all(
        isinstance(item, str) for item in raw_paths
    ):
        raise FlowLoadError(
            f"Flow file '{yaml_path}' step '{step_name}' {kind} must be a list "
            "of path strings."
        )

    resolved: list[str] = []
    for declared in raw_paths:
        candidate = (yaml_path.parent / declared).resolve()
        if not candidate.is_file():
            raise FlowLoadError(
                f"Flow file '{yaml_path}' step '{step_name}' references missing "
                f"context file '{declared}' (resolved to '{candidate}')."
            )
        resolved.append(str(candidate))
    return resolved


def _import_model(
    dotted_path: Any,
    path: Path,
    step_name: str,
    kind: str,
    *,
    allow_union: bool = False,
) -> Any:
    """Import and validate a Pydantic model (or Union) from a dotted path."""
    if not isinstance(dotted_path, str) or not dotted_path:
        raise FlowLoadError(
            f"Flow file '{path}' step '{step_name}' {kind} must be a dotted path string."
        )

    model = _import_dotted(dotted_path, path=path, step_name=step_name, kind=kind)
    valid = is_base_model_type(model) or (allow_union and is_union_type(model))
    if not valid:
        if allow_union:
            raise FlowLoadError(
                f"Flow file '{path}' step '{step_name}' {kind} '{dotted_path}' "
                "is not a Pydantic BaseModel subclass or a Union of them."
            )
        raise FlowLoadError(
            f"Flow file '{path}' step '{step_name}' {kind} '{dotted_path}' "
            "is not a Pydantic BaseModel subclass."
        )
    return model


def _import_dotted(
    dotted_path: str,
    *,
    path: Path,
    step_name: str,
    kind: str,
) -> Any:
    """Import ``module.attribute`` and return the attribute, with clear errors."""
    module_name, separator, attribute_name = dotted_path.rpartition(".")
    if not separator:
        raise FlowLoadError(
            f"Flow file '{path}' step '{step_name}' {kind} path '{dotted_path}' "
            "must be a dotted path such as 'package.module.attribute'."
        )

    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        raise FlowLoadError(
            f"Flow file '{path}' step '{step_name}' could not import module "
            f"'{module_name}' for {kind} '{dotted_path}': {error}"
        ) from error

    try:
        return getattr(module, attribute_name)
    except AttributeError:
        raise FlowLoadError(
            f"Flow file '{path}' step '{step_name}' could not find {kind} "
            f"'{dotted_path}': module '{module_name}' has no attribute "
            f"'{attribute_name}'."
        ) from None
