"""Pluggable extraction providers.

Each module in this package exposes a focused capability (images, tables,
math, …) that can be independently enabled or disabled via config flags.
All providers fail gracefully — if a dependency is missing or extraction
errors out, the main pipeline continues unaffected.
"""
