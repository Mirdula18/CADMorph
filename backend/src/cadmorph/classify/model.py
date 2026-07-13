"""GAT symbol-spotting model (T020, research R4).

A two-layer Graph Attention Network over the attributed drawing graph:
node = entity, output = semantic type logits. Weights are pinned artifacts —
loaded in eval mode and hash-checked against models/meta.json so a silent
weight swap cannot change outputs unnoticed (Constitution IV, R11).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import torch
from torch_geometric.nn import GATConv

from cadmorph.classify.features import CLASSES, FEATURE_DIM
from cadmorph.determinism import check_weights, file_sha256

CLASSIFIER_WEIGHTS = "gat_classifier.pt"
META_FILE = "meta.json"


def models_dir() -> Path:
    override = os.environ.get("CADMORPH_MODELS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "models"


class GATClassifier(torch.nn.Module):
    """GAT with a self-feature skip path.

    Pure stacked attention over kNN-proximity edges over-smooths: an
    entity's own vector-exact features (size, stroke, segment structure)
    are what identify its symbol class, while attention supplies
    neighborhood context. The head sees both, concatenated.
    """

    def __init__(self, in_dim: int = FEATURE_DIM, hidden: int = 32, heads: int = 4) -> None:
        super().__init__()
        self.lin_self = torch.nn.Linear(in_dim, hidden * heads)
        self.conv1 = GATConv(in_dim, hidden, heads=heads)
        self.conv2 = GATConv(hidden * heads, hidden, heads=1)
        self.head = torch.nn.Linear(hidden * heads + hidden, len(CLASSES))

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        h_self = torch.nn.functional.relu(self.lin_self(x))
        h_graph = torch.nn.functional.elu(self.conv1(x, edge_index))
        h_graph = torch.nn.functional.elu(self.conv2(h_graph, edge_index))
        return self.head(torch.cat([h_self, h_graph], dim=1))


def save_pinned(model: torch.nn.Module, weights_name: str, directory: Path | None = None) -> str:
    """Save weights and record their hash in meta.json; returns the hash."""
    directory = directory or models_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / weights_name
    torch.save(model.state_dict(), path)
    digest = file_sha256(path)
    meta_path = directory / META_FILE
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta[weights_name] = digest
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return digest


def pinned_hash(weights_name: str, directory: Path | None = None) -> str:
    directory = directory or models_dir()
    meta = json.loads((directory / META_FILE).read_text(encoding="utf-8"))
    return meta[weights_name]


def load_pinned(
    model: torch.nn.Module, weights_name: str, directory: Path | None = None
) -> torch.nn.Module:
    """Load hash-checked weights into ``model`` and freeze it in eval mode."""
    directory = directory or models_dir()
    path = directory / weights_name
    check_weights(path, pinned_hash(weights_name, directory))
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    model.eval()
    for param in model.parameters():
        param.requires_grad_(False)
    return model


def load_classifier(directory: Path | None = None) -> GATClassifier:
    return load_pinned(GATClassifier(), CLASSIFIER_WEIGHTS, directory)  # type: ignore[return-value]
