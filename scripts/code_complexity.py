#!/usr/bin/env python3
"""
Code complexity analyzer for finding long and deeply nested functions.

Usage:
    python scripts/code_complexity.py [path] [--min-lines N] [--min-depth N] [--top N]

Examples:
    python scripts/code_complexity.py src/kohakuriver
    python scripts/code_complexity.py src/kohakuriver --min-lines 50 --min-depth 4
    python scripts/code_complexity.py src/kohakuriver/runner/endpoints/terminal.py
"""

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FunctionInfo:
    """Information about a function's complexity."""

    file: str
    name: str
    line: int
    lines: int
    max_depth: int

    @property
    def short_file(self) -> str:
        """Get shortened file path."""
        parts = self.file.split("/")
        if len(parts) > 3:
            return "/".join(parts[-3:])
        return self.file


class DepthVisitor(ast.NodeVisitor):
    """AST visitor to calculate max nesting depth."""

    def __init__(self):
        self.max_depth = 0
        self.current_depth = 0

    def _visit_block(self, node):
        """Visit a node that increases nesting depth."""
        self.current_depth += 1
        self.max_depth = max(self.max_depth, self.current_depth)
        self.generic_visit(node)
        self.current_depth -= 1

    def visit_If(self, node):
        self._visit_block(node)

    def visit_For(self, node):
        self._visit_block(node)

    def visit_While(self, node):
        self._visit_block(node)

    def visit_With(self, node):
        self._visit_block(node)

    def visit_Try(self, node):
        self._visit_block(node)

    def visit_ExceptHandler(self, node):
        self._visit_block(node)

    def visit_Match(self, node):
        self._visit_block(node)

    def visit_match_case(self, node):
        self._visit_block(node)


class FunctionAnalyzer(ast.NodeVisitor):
    """AST visitor to analyze functions in a file."""

    def __init__(self, filepath: str, source_lines: list[str]):
        self.filepath = filepath
        self.source_lines = source_lines
        self.functions: list[FunctionInfo] = []

    def _get_function_lines(self, node) -> int:
        """Get number of lines in a function."""
        if hasattr(node, "end_lineno") and node.end_lineno:
            return node.end_lineno - node.lineno + 1
        # Fallback: count non-empty lines in body
        return len([n for n in ast.walk(node) if hasattr(n, "lineno")])

    def _get_max_depth(self, node) -> int:
        """Get maximum nesting depth in a function."""
        visitor = DepthVisitor()
        visitor.visit(node)
        return visitor.max_depth

    def _analyze_function(self, node, prefix: str = ""):
        """Analyze a function or method."""
        name = f"{prefix}{node.name}" if prefix else node.name
        lines = self._get_function_lines(node)
        max_depth = self._get_max_depth(node)

        self.functions.append(
            FunctionInfo(
                file=self.filepath,
                name=name,
                line=node.lineno,
                lines=lines,
                max_depth=max_depth,
            )
        )

        # Check for nested functions
        for child in ast.walk(node):
            if child is not node and isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                # Skip, will be handled separately
                pass

    def visit_FunctionDef(self, node):
        self._analyze_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._analyze_function(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        # Analyze methods with class prefix
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._analyze_function(child, prefix=f"{node.name}.")
        self.generic_visit(node)


def analyze_file(filepath: Path) -> list[FunctionInfo]:
    """Analyze a single Python file."""
    try:
        source = filepath.read_text()
        tree = ast.parse(source)
        lines = source.splitlines()

        analyzer = FunctionAnalyzer(str(filepath), lines)
        analyzer.visit(tree)
        return analyzer.functions
    except SyntaxError as e:
        print(f"  Syntax error in {filepath}: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  Error analyzing {filepath}: {e}", file=sys.stderr)
        return []


def analyze_directory(path: Path) -> list[FunctionInfo]:
    """Analyze all Python files in a directory."""
    all_functions = []

    for filepath in path.rglob("*.py"):
        # Skip common non-source directories
        parts = filepath.parts
        if any(
            p in parts for p in ["__pycache__", ".git", "node_modules", "venv", ".venv"]
        ):
            continue

        functions = analyze_file(filepath)
        all_functions.extend(functions)

    return all_functions


def print_report(
    functions: list[FunctionInfo],
    min_lines: int = 30,
    min_depth: int = 3,
    top_n: int = 20,
):
    """Print analysis report."""

    # Filter and sort by lines
    long_funcs = [f for f in functions if f.lines >= min_lines]
    long_funcs.sort(key=lambda f: f.lines, reverse=True)

    # Filter and sort by depth
    deep_funcs = [f for f in functions if f.max_depth >= min_depth]
    deep_funcs.sort(key=lambda f: f.max_depth, reverse=True)

    # Print header
    print("=" * 80)
    print("CODE COMPLEXITY REPORT")
    print("=" * 80)
    print(f"Total functions analyzed: {len(functions)}")
    print(f"Functions with >= {min_lines} lines: {len(long_funcs)}")
    print(f"Functions with >= {min_depth} nesting depth: {len(deep_funcs)}")
    print()

    # Print long functions
    print("-" * 80)
    print(f"TOP {top_n} LONGEST FUNCTIONS (>= {min_lines} lines)")
    print("-" * 80)
    print(f"{'Lines':>6}  {'Depth':>5}  {'Location':<50}  Function")
    print("-" * 80)

    for f in long_funcs[:top_n]:
        location = f"{f.short_file}:{f.line}"
        print(f"{f.lines:>6}  {f.max_depth:>5}  {location:<50}  {f.name}")

    if not long_funcs:
        print("  (none)")

    print()

    # Print deeply nested functions
    print("-" * 80)
    print(f"TOP {top_n} MOST DEEPLY NESTED FUNCTIONS (>= {min_depth} levels)")
    print("-" * 80)
    print(f"{'Depth':>5}  {'Lines':>6}  {'Location':<50}  Function")
    print("-" * 80)

    for f in deep_funcs[:top_n]:
        location = f"{f.short_file}:{f.line}"
        print(f"{f.max_depth:>5}  {f.lines:>6}  {location:<50}  {f.name}")

    if not deep_funcs:
        print("  (none)")

    print()
    print("=" * 80)

    # Summary recommendations
    critical = [f for f in functions if f.lines >= 100 or f.max_depth >= 5]
    if critical:
        print("CRITICAL: The following functions need refactoring:")
        for f in critical:
            reasons = []
            if f.lines >= 100:
                reasons.append(f"{f.lines} lines")
            if f.max_depth >= 5:
                reasons.append(f"depth {f.max_depth}")
            print(f"  - {f.short_file}:{f.line} {f.name} ({', '.join(reasons)})")
        print()


def main():
    parser = argparse.ArgumentParser(description="Analyze Python code complexity")
    parser.add_argument(
        "path", nargs="?", default="src/kohakuriver", help="Path to analyze"
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=30,
        help="Minimum lines to report (default: 30)",
    )
    parser.add_argument(
        "--min-depth",
        type=int,
        default=3,
        help="Minimum nesting depth to report (default: 3)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of top results to show (default: 20)",
    )

    args = parser.parse_args()

    path = Path(args.path)

    if not path.exists():
        print(f"Error: Path not found: {path}", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing: {path}")
    print()

    if path.is_file():
        functions = analyze_file(path)
    else:
        functions = analyze_directory(path)

    print_report(
        functions,
        min_lines=args.min_lines,
        min_depth=args.min_depth,
        top_n=args.top,
    )


if __name__ == "__main__":
    main()
