import importlib
import sys


def test_import_utils_has_no_io_side_effects():
    # Ensure a fresh import
    sys.modules.pop("data_models.utils", None)
    # Import should not perform IO or create DataFrame globals like applicants_df/staff_df
    mod = importlib.import_module("data_models.utils")

    # Module must expose the function to run alignment explicitly
    assert hasattr(mod, "align_staff_availabilities")

    # These names were present previously at module scope and triggered IO on import.
    for forbidden in ("applicants_df", "staff_df", "aligned_staff", "applicant_time_map"):
        assert not hasattr(mod, forbidden), f"{forbidden} should not be present on import"
