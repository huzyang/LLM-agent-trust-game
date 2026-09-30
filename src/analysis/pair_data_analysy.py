"""Export every pair transaction grouped by proportion; equal amounts are retained."""
import argparse
from pathlib import Path
import pandas as pd


def process_column(df, col_name):
    """Keep all observations, including equal amounts on different links."""
    required = {'proportion', col_name}
    if not required.issubset(df.columns):
        raise ValueError(f'Missing columns: {sorted(required - set(df.columns))}')
    grouped = df.groupby('proportion', sort=True)[col_name].apply(list)
    return pd.DataFrame({key: pd.Series(values) for key, values in grouped.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='Pair-data CSV or XLSX')
    parser.add_argument('--output', required=True, type=Path, help='Output XLSX')
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Input and output must be different files')
    df = pd.read_csv(args.input) if args.input.suffix.lower() == '.csv' else pd.read_excel(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(args.output, engine='openpyxl') as writer:
        process_column(df, 'sent_amount').to_excel(writer, sheet_name='group_sent', index=False)
        process_column(df, 'returned_amount').to_excel(writer, sheet_name='group_return', index=False)
    print(f'Saved {len(df)} transactions without deduplication to {args.output}')


if __name__ == '__main__':
    main()
