"""
Pytest configuration and fixtures for DMS Migration tests.
"""
import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def pytest_configure(config):
    """Suppress third-party SQLAlchemy HANA dialect warnings (not our code)."""
    # Note: sqlalchemy-hana 4.5 fixed dbapi() rename and supports statement caching.
    # These filters are kept as safety nets but may no longer trigger.
    config.addinivalue_line(
        "filterwarnings",
        "ignore:The dbapi\\(\\) classmethod.*has been renamed:DeprecationWarning"
    )
    config.addinivalue_line(
        "filterwarnings",
        "ignore:Dialect hana.hdbcli will not make use of SQL compilation caching:Warning"
    )


@pytest.fixture(scope="session")
def misc_engine():
    """Database engine for MISC database (staging data)."""
    from app_config import MiscEngine
    misc_db = MiscEngine.load()
    return misc_db.engine


@pytest.fixture(scope="session")
def dil_engine():
    """Database engine for DIL database (SAP source data)."""
    from app_config import DilEngine
    try:
        dil_db = DilEngine.load()
        return dil_db.engine
    except Exception:
        pytest.skip("DIL database not available")


@pytest.fixture
def sample_document_data():
    """Sample document data for testing."""
    import pandas as pd
    return pd.DataFrame([
        {
            'documentnumber': '0000000000000010002159971',
            'documentpart': '000',
            'documenttype': 'IY1',
            'documentversion': '00',
            'description': 'Test Document 1',
        },
        {
            'documentnumber': '0000000000000010002159972',
            'documentpart': '000',
            'documenttype': 'IY1',
            'documentversion': '00',
            'description': 'Test Document 2',
        }
    ])


@pytest.fixture
def sample_staging_record():
    """Sample staging record dict for execute tests."""
    return {
        'id': 999999,
        'batch_id': 'TEST_BATCH_001',
        'source_documentnumber': '0000000000000010002159971',
        'source_documentpart': '000',
        'source_documenttype': 'IY1',
        'source_documentversion': '00',
        'source_loioid': 'ABC123DEF456',
        'source_description': 'Test Document',
        'target_documentnumber': '',
        'target_documentpart': '000',
        'target_documenttype': 'IY1',
        'target_documentversion': '00',
        'authorization_group': None,
        'filename': 'test.pdf',
        'file_size_bytes': 1024,
        'skip_migration': 0,
        'container_created': 0
    }
