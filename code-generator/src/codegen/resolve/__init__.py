"""
Resolve layer for PLC code generation.

This package contains the semantic resolution step between:
- normalized config
and
- output generators

Current focus:
- resolving module classes for PLC code generation
"""

from codegen.resolve.types import (
    ResolvedCustomParameter,
    ResolvedModuleClass,
    ResolvedModuleClasses,
    ResolvedModuleVariable,
    ResolvedTarget,
    ResolvedValue,
)

__all__ = [
    "ResolvedCustomParameter",
    "ResolvedModuleClass",
    "ResolvedModuleClasses",
    "ResolvedModuleVariable",
    "ResolvedTarget",
    "ResolvedValue",
]