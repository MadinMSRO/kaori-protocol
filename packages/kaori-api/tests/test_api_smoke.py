def test_imports():
    """Verify that the package can be imported."""
    import kaori_api
    assert kaori_api.__version__ is not None
