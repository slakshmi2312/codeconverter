import ast
from dataclasses import dataclass
from typing import Dict, List

from tree_sitter_languages import get_parser


LANG_TO_TS = {
    "python": "python",
    "java": "java",
    "c": "c",
    "javascript": "javascript",
}


@dataclass
class ASTFeatures:
    node_types: List[str]
    node_count: int
    max_depth: int
    root_type: str


def _walk_tree_sitter(node, depth: int, types: List[str]) -> int:
    types.append(node.type)
    max_depth = depth
    for child in node.children:
        max_depth = max(max_depth, _walk_tree_sitter(child, depth + 1, types))
    return max_depth


def parse_with_tree_sitter(code: str, language: str) -> ASTFeatures:
    parser = get_parser(LANG_TO_TS[language])
    tree = parser.parse(code.encode("utf-8", errors="ignore"))
    root = tree.root_node
    node_types: List[str] = []
    max_depth = _walk_tree_sitter(root, 1, node_types)
    return ASTFeatures(
        node_types=node_types,
        node_count=len(node_types),
        max_depth=max_depth,
        root_type=root.type,
    )


def parse_python_ast(code: str) -> ASTFeatures:
    root = ast.parse(code)
    node_types = [type(node).__name__ for node in ast.walk(root)]
    # ast.walk is breadth-first and does not expose direct depth cheaply.
    return ASTFeatures(
        node_types=node_types,
        node_count=len(node_types),
        max_depth=0,
        root_type=type(root).__name__,
    )


def extract_ast_features(code: str, language: str) -> ASTFeatures:
    language = (language or "").lower().strip()
    if language == "python":
        try:
            return parse_python_ast(code)
        except Exception:
            pass

    if language in LANG_TO_TS:
        return parse_with_tree_sitter(code, language)

    return ASTFeatures(node_types=[], node_count=0, max_depth=0, root_type="unknown")


def ast_feature_dict(code: str, language: str) -> Dict[str, object]:
    feat = extract_ast_features(code, language)
    return {
        "node_types": feat.node_types,
        "node_count": feat.node_count,
        "max_depth": feat.max_depth,
        "root_type": feat.root_type,
    }
