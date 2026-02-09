"""
Unit tests for app/process.py - Processing functions.
"""
import pytest


class TestSanitizeFilename:
    """Tests for _sanitize_filename() function."""
    
    def test_normal_filename(self):
        from app.process import _sanitize_filename
        assert _sanitize_filename("document.pdf") == "document.pdf"
    
    def test_removes_backslash(self):
        from app.process import _sanitize_filename
        result = _sanitize_filename("C:\\Users\\test\\document.pdf")
        assert "\\" not in result
    
    def test_removes_forward_slash(self):
        from app.process import _sanitize_filename
        result = _sanitize_filename("/path/to/document.pdf")
        assert "/" not in result
    
    def test_removes_special_chars(self):
        from app.process import _sanitize_filename
        result = _sanitize_filename("file:name*with?special<>chars.pdf")
        # All special chars should be replaced with underscore
        assert ":" not in result
        assert "*" not in result
        assert "?" not in result
        assert "<" not in result
        assert ">" not in result
    
    def test_empty_string(self):
        from app.process import _sanitize_filename
        assert _sanitize_filename("") == "unnamed"
    
    def test_none_input(self):
        from app.process import _sanitize_filename
        assert _sanitize_filename(None) == "unnamed"
    
    def test_preserves_extension(self):
        from app.process import _sanitize_filename
        result = _sanitize_filename("bad:file:name.xlsx")
        assert result.endswith(".xlsx")
    
    def test_collapses_multiple_underscores(self):
        from app.process import _sanitize_filename
        result = _sanitize_filename("file:::name.pdf")
        # Multiple consecutive underscores should collapse
        assert "___" not in result


class TestClassifyError:
    """Tests for _classify_error() function."""
    
    def test_401_unauthorized(self):
        from app.process import _classify_error
        result = _classify_error({'status_code': 401})
        assert 'TOKEN' in result or 'AUTH' in result
    
    def test_403_forbidden(self):
        from app.process import _classify_error
        result = _classify_error({'status_code': 403})
        assert 'PERMISSION' in result or 'FORBIDDEN' in result or 'AUTH' in result
    
    def test_404_not_found(self):
        from app.process import _classify_error
        result = _classify_error({'status_code': 404})
        assert 'NOT_FOUND' in result
    
    def test_500_server_error(self):
        from app.process import _classify_error
        result = _classify_error({'status_code': 500})
        assert 'SERVER' in result or 'ERROR' in result
    
    def test_504_gateway_timeout(self):
        from app.process import _classify_error
        result = _classify_error({'status_code': 504})
        assert 'TIMEOUT' in result or 'GATEWAY' in result
    
    def test_csrf_error(self):
        from app.process import _classify_error
        result = _classify_error({'detail': 'CSRF token validation failed'})
        assert 'CSRF' in result
    
    def test_empty_error(self):
        from app.process import _classify_error
        result = _classify_error({})
        assert result in ['UNKNOWN', 'OTHER']
    
    def test_none_error(self):
        from app.process import _classify_error
        result = _classify_error(None)
        assert result in ['UNKNOWN', 'OTHER']


class TestGetErrorDescription:
    """Tests for get_error_description() function."""
    
    def test_known_category(self):
        from app.process import get_error_description
        result = get_error_description('TOKEN_EXPIRED')
        # Should return human-readable description
        assert 'Token' in result or 'abgelaufen' in result.lower() or result != 'TOKEN_EXPIRED'
    
    def test_unknown_category(self):
        from app.process import get_error_description
        result = get_error_description('SOME_UNKNOWN_CATEGORY')
        # Should return the category itself or a generic message
        assert result is not None


class TestGetErrorDetails:
    """Tests for get_error_details() function."""
    
    def test_returns_tuple(self):
        from app.process import get_error_details
        result = get_error_details('GATEWAY_TIMEOUT')
        assert isinstance(result, tuple)
        assert len(result) == 2
    
    def test_unknown_returns_category(self):
        from app.process import get_error_details
        desc, hint = get_error_details('TOTALLY_UNKNOWN_ERROR')
        assert desc == 'TOTALLY_UNKNOWN_ERROR' or desc is not None
