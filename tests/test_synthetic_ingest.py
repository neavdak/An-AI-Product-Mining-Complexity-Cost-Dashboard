import io

import pandas as pd
import pytest

from app.ingest import DataValidationError, load_uploads, normalise
from app.synthetic import generate


def test_generator_is_deterministic(synth):
    from datetime import date

    again = generate(seed=7, as_of=date(2026, 8, 1))
    pd.testing.assert_frame_equal(synth.features, again.features)
    assert synth.feedback["text"].tolist() == again.feedback["text"].tolist()


def test_generator_shapes(synth):
    assert len(synth.features) == 42
    assert synth.features["feature_id"].is_unique
    assert len(synth.feedback) > 800
    assert {"feature_id", "month", "active_users"} <= set(synth.usage.columns)
    # archetypes are hidden from the CSV output
    assert "archetype" not in synth.features.columns
    assert (synth.feedback["feature_id"] == "").mean() > 0.05  # some untagged tickets


def test_normalise_full(dataset):
    assert len(dataset.features) == 42
    assert pd.api.types.is_datetime64_any_dtype(dataset.usage["month"])
    assert dataset.summary()["n_tickets"] == len(dataset.feedback)


def test_flat_catalog_with_aliases():
    flat = pd.DataFrame({
        "Feature ID": ["A", "B"], "Name": ["Alpha", "Beta"],
        "direct_revenue_attributed": ["₹1,00,000", "5000"], "tier_dependency": [10, 2],
        "MAU": [900, 50], "maintenance_hours": [40, 300], "bug_tickets": [1, 20],
    })
    ds = normalise(flat)
    assert ds.features["monthly_revenue_inr"].tolist() == [100000.0, 5000.0]
    assert ds.features["enterprise_clients"].tolist() == [10.0, 2.0]
    assert len(ds.usage) == 2 and len(ds.engineering) == 2
    assert any("usage_monthly" in w for w in ds.warnings)


def test_missing_required_column():
    with pytest.raises(DataValidationError):
        normalise(pd.DataFrame({"feature_id": ["A"]}))


def test_load_uploads_roundtrip(synth):
    files = {}
    for key, df in (("features", synth.features), ("usage", synth.usage),
                    ("engineering", synth.engineering), ("feedback", synth.feedback)):
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        files[key] = buf.getvalue().encode()
    ds = load_uploads(files)
    assert len(ds.features) == 42 and len(ds.feedback) == len(synth.feedback)
