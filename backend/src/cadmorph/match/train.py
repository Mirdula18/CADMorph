"""Siamese matcher training (T022): python -m cadmorph.match.train

Contrastive training on synthgen revision pairs: positives are the same
synthetic entity (shared uid) across v1/v2 — including mutated ones (moved,
re-dimensioned, restyled), which is exactly what the learned tier must still
pair; every other cross-revision entity is a negative (symmetric InfoNCE).
Prints the true-pair / false-pair similarity distributions used to calibrate
the operating threshold (T025).
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import torch

from cadmorph.classify.data import align_records, load_records
from cadmorph.classify.features import graph_tensors
from cadmorph.classify.model import models_dir, save_pinned
from cadmorph.determinism import seed_all
from cadmorph.extraction.provider import get_provider
from cadmorph.graph.build import build_graph
from cadmorph.match.model import ENCODER_WEIGHTS, SiameseEncoder, similarity_matrix

TRAIN_SEEDS = tuple(range(1, 21))
EVAL_SEED = 101  # held out from training
ALL_MUTATIONS = ["dim-change", "add", "remove", "move", "text-edit", "style"]
TEMPERATURE = 0.1

PairData = tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, list[tuple[int, int]]]


def _pair_data(pair_dir: Path) -> PairData:
    """(x1, ei1, x2, ei2, positives) with positives as (old_idx, new_idx)."""
    provider = get_provider("pdf")
    graphs = {}
    uid_maps: dict[str, dict[str, int]] = {}
    for revision in ("v1", "v2"):
        graph = build_graph(provider.extract(pair_dir / f"{revision}.pdf", "old"))
        assignment = align_records(graph, load_records(pair_dir / f"entities-{revision}.json"))
        index = {e.entity_id: i for i, e in enumerate(graph.entities)}
        uid_maps[revision] = {
            record["uid"]: index[entity_id] for entity_id, record in assignment.items()
        }
        graphs[revision] = graph
    positives = sorted(
        (i, uid_maps["v2"][uid])
        for uid, i in uid_maps["v1"].items()
        if uid in uid_maps["v2"]
    )
    x1, ei1 = graph_tensors(graphs["v1"], include_position=False)
    x2, ei2 = graph_tensors(graphs["v2"], include_position=False)
    return x1, ei1, x2, ei2, positives


def build_dataset(data_dir: Path, seeds: tuple[int, ...]) -> list[PairData]:
    from synthgen import make_pair

    pairs = []
    for seed in seeds:
        # Alternate mutation subsets so positives include every mutation type
        # and negatives include the adversarial identical-shape twin.
        mutations = ALL_MUTATIONS if seed % 2 else ["dim-change", "move", "twin"]
        pair_dir = data_dir / f"pair-{seed}"
        make_pair("floorplan", mutations, pair_dir, seed=seed, move_distance=10.0 * (seed % 5 + 1))
        pairs.append(_pair_data(pair_dir))
    return pairs


def _info_nce(sim: torch.Tensor, positives: list[tuple[int, int]]) -> torch.Tensor:
    logits = sim / TEMPERATURE
    old_idx = torch.tensor([p[0] for p in positives], dtype=torch.long)
    new_idx = torch.tensor([p[1] for p in positives], dtype=torch.long)
    loss_old = torch.nn.functional.cross_entropy(logits[old_idx], new_idx)
    loss_new = torch.nn.functional.cross_entropy(logits.t()[new_idx], old_idx)
    return (loss_old + loss_new) / 2.0


def sim_stats(encoder: SiameseEncoder, pairs: list[PairData]) -> tuple[float, float]:
    """(min true-pair similarity, max false-pair similarity) over ``pairs``."""
    min_true, max_false = 1.0, -1.0
    with torch.no_grad():
        for x1, ei1, x2, ei2, positives in pairs:
            sim = similarity_matrix(encoder(x1, ei1), encoder(x2, ei2))
            mask = torch.zeros_like(sim, dtype=torch.bool)
            for i, j in positives:
                mask[i, j] = True
                min_true = min(min_true, float(sim[i, j]))
            if (~mask).any():
                max_false = max(max_false, float(sim[~mask].max()))
    return min_true, max_false


def train(
    data_dir: Path, epochs: int = 150, lr: float = 0.005
) -> tuple[SiameseEncoder, tuple[float, float]]:
    seed_all()
    pairs = build_dataset(data_dir, TRAIN_SEEDS)
    eval_pairs = build_dataset(data_dir / "eval", (EVAL_SEED,))

    encoder = SiameseEncoder()
    optimizer = torch.optim.Adam(encoder.parameters(), lr=lr)
    for epoch in range(epochs):
        encoder.train()
        total = 0.0
        for x1, ei1, x2, ei2, positives in pairs:
            optimizer.zero_grad()
            sim = similarity_matrix(encoder(x1, ei1), encoder(x2, ei2))
            loss = _info_nce(sim, positives)
            loss.backward()
            optimizer.step()
            total += float(loss)
        if (epoch + 1) % 25 == 0:
            encoder.eval()
            min_true, max_false = sim_stats(encoder, eval_pairs)
            print(
                f"epoch {epoch + 1}: loss={total / len(pairs):.4f} "
                f"eval min_true={min_true:.4f} max_false={max_false:.4f}"
            )
    encoder.eval()
    return encoder, sim_stats(encoder, eval_pairs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--out", default=None, help="models dir (default backend/models)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        encoder, (min_true, max_false) = train(Path(tmp), epochs=args.epochs)
    out = Path(args.out) if args.out else models_dir()
    digest = save_pinned(encoder, ENCODER_WEIGHTS, out)
    print(f"held-out similarity gap: min_true={min_true:.4f} max_false={max_false:.4f}")
    print(f"pinned weights: {out / ENCODER_WEIGHTS} sha256={digest}")


if __name__ == "__main__":
    main()
