"""CLI: python -m synthgen make-pair --preset floorplan --mutations dim-change,add --out data/gt/pair01"""

from __future__ import annotations

import argparse

from synthgen.pairs import make_pair


def main() -> None:
    parser = argparse.ArgumentParser(prog="synthgen")
    sub = parser.add_subparsers(dest="command", required=True)

    mp = sub.add_parser("make-pair", help="generate a ground-truth revision pair + answer key")
    mp.add_argument("--preset", required=True, choices=["floorplan", "site", "dense", "unrelated"])
    mp.add_argument("--mutations", default="", help="comma-separated: dim-change,add,remove,move,text-edit,style or 'none'")
    mp.add_argument("--out", required=True)
    mp.add_argument("--seed", type=int, default=7)
    mp.add_argument("--entities", type=int, default=10000, help="entity count for the dense preset")
    mp.add_argument("--move-distance", type=float, default=20.0)
    mp.add_argument("--export-offset", default="0,0", help="dx,dy in points applied to v2")
    mp.add_argument("--export-scale", type=float, default=1.0)

    args = parser.parse_args()
    mutations = [m for m in args.mutations.split(",") if m and m != "none"]
    dx, dy = (float(v) for v in args.export_offset.split(","))
    key_path = make_pair(
        args.preset,
        mutations,
        args.out,
        seed=args.seed,
        entities=args.entities,
        move_distance=args.move_distance,
        export_offset=(dx, dy),
        export_scale=args.export_scale,
    )
    print(f"answer key written: {key_path}")


if __name__ == "__main__":
    main()
