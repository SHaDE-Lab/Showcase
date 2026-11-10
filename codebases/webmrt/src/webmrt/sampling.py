"""Create data/sample_RF_Data.csv: a seeded, stratified sample of the full WebMRT training table.

    python -m webmrt.sampling  path/to/RF_Data.csv  [out.csv]  [n_rows]

Strata: Shade_AtMeasurement (0/1/2) x solar-altitude tercile. The rows holding the minimum and maximum of
`surr_pervious` are always kept so that the min-max normalisation of that column is identical to the full table.
"""
import sys
from pathlib import Path

import pandas as pd

SEED = 42


def make_sample(src, n=450, seed=SEED) -> pd.DataFrame:
    df = pd.read_csv(src)
    must = df.loc[[df["surr_pervious"].idxmin(), df["surr_pervious"].idxmax()]]
    alt_bin = pd.qcut(df["Solar_Altitude"], 3, labels=False)
    strata = df["Shade_AtMeasurement"].astype(str) + "_" + alt_bin.astype(str)
    frac = n / len(df)
    parts = [g.sample(n=max(1, round(len(g) * frac)), random_state=seed) for _, g in df.groupby(strata)]
    out = pd.concat(parts + [must])
    out = out.loc[~out.index.duplicated()]
    return out.sort_index()


if __name__ == "__main__":
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[2] / "data" / "sample_RF_Data.csv"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 450
    s = make_sample(src, n)
    s.to_csv(dst, index=False)
    print(f"wrote {len(s)} of {len(pd.read_csv(src))} rows to {dst}")
