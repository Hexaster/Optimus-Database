# Retained generic CSV/Excel helper; no repository callers currently use it. See docs/legacy_code.md.
import pandas as pd

def load_data(file_path: str) -> pd.DataFrame:
    """Load data from a CSV or Excel file into a pandas DataFrame."""
    # When file_path.endswith('.csv'), return pd.read_csv(file_path).
    if file_path.endswith('.csv'):
        return pd.read_csv(file_path)
    # When file_path.endswith(('.xls', '.xlsx')), return pd.read_excel(file_path).
    elif file_path.endswith(('.xls', '.xlsx')):
        return pd.read_excel(file_path)
    # Otherwise, stop with a diagnostic: Unsupported file format. Please provide a CSV or Excel
    # file.
    else:
        raise ValueError("Unsupported file format. Please provide a CSV or Excel file.")