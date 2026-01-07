def test_imports():
    """Verify that the package can be imported."""
    import kaori_db
    assert kaori_db.__version__ is not None
