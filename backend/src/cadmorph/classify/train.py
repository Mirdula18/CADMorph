"""GAT symbol-spotting training (T020): python -m cadmorph.classify.train

Trains on synthgen-labeled sheets (Constitution V: fixtures precede
implementation) and saves pinned, hash-recorded eval-mode weights under
backend/models/. Deterministic: seeded generation, seeded training.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import torch

from cadmorph.classify.data import align_records, load_records
from cadmorph.classify.features import CLASSES, graph_tensors
from cadmorph.classify.model import CLASSIFIER_WEIGHTS, GATClassifier, models_dir, save_pinned
from cadmorph.determinism import seed_all
from cadmorph.extraction.provider import get_provider
from cadmorph.graph.build import build_graph

TRAIN_SEEDS = tuple(range(1, 21))
SITE_SEEDS = tuple(range(1, 6))
EVAL_SEED = 101  # held out from training
ALL_MUTATIONS = ["dim-change", "add", "remove", "move", "text-edit", "style"]


def _labeled_sheet(pair_dir: Path, revision: str) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """(x, edge_index, labels) for one rendered sheet; label -1 = unlabeled."""
    graph = get_provider("pdf").extract(pair_dir / f"{revision}.pdf", "old")
    graph = build_graph(graph)
    assignment = align_records(graph, load_records(pair_dir / f"entities-{revision}.json"))
    labels = torch.tensor(
        [
            CLASSES.index(assignment[e.entity_id]["semantic"]) if e.entity_id in assignment else -1
            for e in graph.entities
        ],
        dtype=torch.long,
    )
    x, edge_index = graph_tensors(graph, include_position=True)
    return x, edge_index, labels


def build_dataset(data_dir: Path) -> list[tuple[torch.Tensor, torch.Tensor, torch.Tensor]]:
    from synthgen import make_pair

    sheets = []
    for seed in TRAIN_SEEDS:
        pair_dir = data_dir / f"floorplan-{seed}"
        make_pair("floorplan", ALL_MUTATIONS, pair_dir, seed=seed)
        sheets.append(_labeled_sheet(pair_dir, "v1"))
        sheets.append(_labeled_sheet(pair_dir, "v2"))
    for seed in SITE_SEEDS:
        pair_dir = data_dir / f"site-{seed}"
        make_pair("site", [], pair_dir, seed=seed)
        sheets.append(_labeled_sheet(pair_dir, "v1"))
    return sheets


def accuracy(model: GATClassifier, sheets: list) -> float:
    correct = total = 0
    with torch.no_grad():
        for x, edge_index, labels in sheets:
            mask = labels >= 0
            pred = model(x, edge_index).argmax(dim=1)
            correct += int((pred[mask] == labels[mask]).sum())
            total += int(mask.sum())
    return correct / max(total, 1)


def train(data_dir: Path, epochs: int = 200, lr: float = 0.003) -> tuple[GATClassifier, float]:
    seed_all()
    sheets = build_dataset(data_dir)

    from synthgen import make_pair

    eval_dir = data_dir / f"floorplan-eval-{EVAL_SEED}"
    make_pair("floorplan", ALL_MUTATIONS, eval_dir, seed=EVAL_SEED)
    eval_sheets = [_labeled_sheet(eval_dir, "v1"), _labeled_sheet(eval_dir, "v2")]

    model = GATClassifier()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    for epoch in range(epochs):
        model.train()
        total_loss = 0.0
        for x, edge_index, labels in sheets:
            mask = labels >= 0
            optimizer.zero_grad()
            logits = model(x, edge_index)
            loss = torch.nn.functional.cross_entropy(logits[mask], labels[mask])
            loss.backward()
            optimizer.step()
            total_loss += float(loss)
        if (epoch + 1) % 50 == 0:
            model.eval()
            print(
                f"epoch {epoch + 1}: loss={total_loss / len(sheets):.4f} "
                f"train_acc={accuracy(model, sheets):.4f} eval_acc={accuracy(model, eval_sheets):.4f}"
            )
    model.eval()
    return model, accuracy(model, eval_sheets)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--out", default=None, help="models dir (default backend/models)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        model, eval_acc = train(Path(tmp), epochs=args.epochs)
    out = Path(args.out) if args.out else models_dir()
    digest = save_pinned(model, CLASSIFIER_WEIGHTS, out)
    print(f"held-out accuracy (seed {EVAL_SEED}): {eval_acc:.4f}")
    print(f"pinned weights: {out / CLASSIFIER_WEIGHTS} sha256={digest}")


if __name__ == "__main__":
    main()
