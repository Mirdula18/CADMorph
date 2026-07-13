"""Siamese graph matcher (T022, research R6 tier 3).

One shared-weight GAT encoder embeds the entities of both revisions;
cross-revision correspondence is scored by cosine similarity of the
L2-normalized embeddings. Position features are excluded so a moved entity
embeds like its counterpart (R7). Weights are pinned and hash-checked like
the classifier (Constitution IV).
"""

from __future__ import annotations

from pathlib import Path

import torch
from torch_geometric.nn import GATConv

from cadmorph.classify.features import BASE_DIM, graph_tensors
from cadmorph.classify.model import load_pinned
from cadmorph.models import DrawingGraph

ENCODER_WEIGHTS = "siamese_encoder.pt"
EMBED_DIM = 32


class SiameseEncoder(torch.nn.Module):
    def __init__(self, in_dim: int = BASE_DIM, hidden: int = 32, heads: int = 4) -> None:
        super().__init__()
        self.conv1 = GATConv(in_dim, hidden, heads=heads)
        self.conv2 = GATConv(hidden * heads, EMBED_DIM, heads=1)

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        h = torch.nn.functional.elu(self.conv1(x, edge_index))
        z = self.conv2(h, edge_index)
        return torch.nn.functional.normalize(z, dim=1)


def embed_graph(graph: DrawingGraph, encoder: SiameseEncoder) -> torch.Tensor:
    """L2-normalized embeddings [n, EMBED_DIM] in canonical entity order."""
    if not graph.entities:
        return torch.zeros((0, EMBED_DIM))
    x, edge_index = graph_tensors(graph, include_position=False)
    with torch.no_grad():
        return encoder(x, edge_index)


def similarity_matrix(emb_old: torch.Tensor, emb_new: torch.Tensor) -> torch.Tensor:
    """Cosine similarity [n_old, n_new] (embeddings are already normalized)."""
    return emb_old @ emb_new.t()


def load_encoder(directory: Path | None = None) -> SiameseEncoder:
    return load_pinned(SiameseEncoder(), ENCODER_WEIGHTS, directory)  # type: ignore[return-value]
