import numpy as np
import pandas as pd

def score_frame(df, weights, min_history=30, history_rows=8400):
    out = df.copy()
    for feature, weight in weights.items():
        scores, statuses = [], []
        for i, value in enumerate(out[feature]):
            hist = pd.to_numeric(out.loc[max(0, i-history_rows):i-1, feature], errors="coerce").dropna() if i else pd.Series(dtype=float)
            if pd.isna(value):
                score, status = np.nan, "missing"
            elif len(hist) < min_history:
                score, status = np.nan, "insufficient_history"
            else:
                percentile = 100 * ((hist < value).sum() + 0.5 * (hist == value).sum()) / len(hist)
                score, status = round(weight * min(max(percentile / 95, 0), 1), 3), "ok"
            scores.append(score); statuses.append(status)
        out[feature+"_score"] = scores
        out[feature+"_status"] = statuses
    cols = [k+"_score" for k in weights]
    out["score"] = out[cols].sum(axis=1, min_count=len(cols)).round(2)
    out["valid_indicators"] = out[cols].notna().sum(axis=1)
    out["engine_status"] = np.where(out["valid_indicators"] == len(cols), "official", "warming_up")
    return out
