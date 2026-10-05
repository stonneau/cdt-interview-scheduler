def test_web_app_import():
    import importlib

    # Importing the module should not raise ModuleNotFoundError for local packages
    importlib.import_module("ui.web_app")
