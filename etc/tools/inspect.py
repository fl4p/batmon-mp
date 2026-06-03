"""Decode a mints .bin store to physical units and print it as a table.

Host-side inspection tool (the "nice table" used to investigate corrupt frames).
Schema is read from the filename, values are decoded with the batmon quantization
(see batmon.py). Useful for eyeballing a time window or the largest anomalies.

Examples:
    python -m etc.tools.inspect path/to/JKPferdestall-...-HHhBBHHB.bin
    python -m etc.tools.inspect FILE --window 995700 996050      # boot-relative time (/10 s)
    python -m etc.tools.inspect FILE --top current 10            # 10 rows of largest |current|
    python -m etc.tools.inspect FILE --raw                       # keep corrupt frames

Run from the repo root (so `import mints` resolves), or via `python -m etc.tools.inspect`.
"""
import argparse

import pandas as pd

from mints import Store

# decoders: column name -> (physical value, header label). batmon.py is the producer.
DECODE = {
    'voltage': (lambda s: s / 100.0, 'V'),
    'current': (lambda s: s / 100.0, 'A'),
    'temp2': (lambda s: s / 2.0 - 40.0, 'T_C'),
    'soc2': (lambda s: s / 2.0, 'SoC_%'),
    'cell_min': (lambda s: s, 'cmin_mV'),
    'cell_max': (lambda s: s, 'cmax_mV'),
}


def decode(df):
    """Return a copy with batmon columns decoded to physical units (renamed)."""
    out = pd.DataFrame(index=df.index)
    for col in df.columns:
        if col in DECODE:
            fn, label = DECODE[col]
            out[label] = fn(df[col])
        else:
            out[col] = df[col]
    if {'cmax_mV', 'cmin_mV'}.issubset(out.columns):
        out['spread_mV'] = out['cmax_mV'] - out['cmin_mV']
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('file', help='path to a {name}-{cols}-{fmt}.bin store')
    ap.add_argument('--raw', action='store_true',
                    help='do NOT reject corrupt frames (show torn/garbled rows)')
    ap.add_argument('--window', nargs=2, type=int, metavar=('LO', 'HI'),
                    help='only rows with boot-relative time (/10 s) in [LO, HI]')
    ap.add_argument('--top', nargs=2, metavar=('COL', 'N'),
                    help='show N rows with the largest |COL| (decoded column, e.g. current)')
    ap.add_argument('--head', type=int, default=0, help='show only the first N rows')
    ap.add_argument('--tail', type=int, default=0, help='show only the last N rows')
    args = ap.parse_args()

    pd.set_option('display.max_columns', 500)
    pd.set_option('display.width', 1000)
    pd.set_option('display.max_rows', 100000)
    pd.set_option('display.float_format', lambda x: f'{x:.2f}')

    raw = Store.read_file_to_pandas(args.file, reject_outliers=not args.raw)
    df = decode(raw)

    if args.window:
        lo, hi = args.window
        df = df[(df.index >= lo) & (df.index <= hi)]
    if args.top:
        col, n = args.top[0], int(args.top[1])
        if col in DECODE:  # accept the raw column name (e.g. 'current') as well as 'A'
            col = DECODE[col][1]
        # positional sort: the 'time' index has duplicates, so reindex() won't work
        order = df[col].abs().to_numpy().argsort()[::-1][:n]
        df = df.iloc[order]
    if args.head:
        df = df.head(args.head)
    if args.tail:
        df = df.tail(args.tail)

    print(f'{len(raw)} frames ({"raw" if args.raw else "cleaned"}), showing {len(df)}')
    print(df.to_string())


if __name__ == '__main__':
    main()
