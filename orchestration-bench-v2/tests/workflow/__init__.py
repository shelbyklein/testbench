"""OB2-10 workflow lane tests.

Every test in this package is **OFFLINE validation**. Nothing here executes a native
workflow, invokes `claude -p`, or makes any other paid model call. All evidence produced
is synthetic: the events these tests emit carry `synthetic: true`.
"""
OFFLINE_VALIDATION = True
