# Tests

This directory contains automated tests for the AI Metadata Enricher platform.

## Purpose

Comprehensive test coverage ensures:
- **Quality**: Code works as expected
- **Reliability**: Changes don't break existing functionality
- **Documentation**: Tests document expected behavior
- **Confidence**: Safe to refactor and improve code

## Test Structure

```
tests/
├── unit/                  # Unit tests (fast, isolated)
│   ├── functions/        # Function-specific tests
│   ├── services/         # Service layer tests
│   └── models/           # Model and validation tests
├── integration/          # Integration tests (slower, external dependencies)
│   ├── api/             # API endpoint tests
│   ├── storage/         # Storage interaction tests
│   └── events/          # Event processing tests
├── e2e/                 # End-to-end tests (full workflows)
└── fixtures/            # Test data and fixtures
    ├── data/           # Sample data files
    └── schemas/        # Test schemas
```

## Test Types

### Unit Tests
- **Scope**: Single function, class, or module
- **Speed**: Fast (< 1 second per test)
- **Dependencies**: Mocked or stubbed
- **Purpose**: Validate business logic

### Integration Tests
- **Scope**: Multiple components working together
- **Speed**: Moderate (seconds per test)
- **Dependencies**: Real services (local or test environment)
- **Purpose**: Validate component interactions

### End-to-End Tests
- **Scope**: Complete user workflows
- **Speed**: Slow (minutes per test)
- **Dependencies**: Full system deployed
- **Purpose**: Validate system behavior

## Testing Frameworks

### Python
```bash
# Install dependencies
pip install pytest pytest-cov pytest-mock

# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_example.py
```

### JavaScript/TypeScript
```bash
# Install dependencies
npm install --save-dev jest @types/jest

# Run all tests
npm test

# Run with coverage
npm test -- --coverage

# Run specific test file
npm test -- path/to/test.spec.ts
```

## Test Naming Convention

### File Naming
- Unit tests: `test_{module_name}.py` or `{module}.test.ts`
- Integration tests: `test_{feature}_integration.py`
- E2E tests: `test_{workflow}_e2e.py`

### Test Function Naming
```python
def test_should_[expected_behavior]_when_[condition]():
    # Example: test_should_return_error_when_input_invalid()
    pass
```

## Writing Good Tests

### AAA Pattern (Arrange, Act, Assert)

```python
def test_should_enrich_metadata_when_valid_content():
    # Arrange - Set up test data and dependencies
    content = create_test_content()
    enricher = MetadataEnricher()
    
    # Act - Execute the code under test
    result = enricher.enrich(content)
    
    # Assert - Verify the expected outcome
    assert result.status == "success"
    assert result.metadata is not None
```

### Best Practices

1. **One Assertion Per Test**: Each test validates one specific behavior
2. **Independent Tests**: Tests don't depend on each other
3. **Repeatable**: Tests produce same results every time
4. **Fast**: Keep unit tests fast for quick feedback
5. **Clear Names**: Test name describes what's being tested
6. **Meaningful Assertions**: Use descriptive assertion messages

## Test Coverage

### Coverage Goals
- **Minimum**: 80% overall coverage
- **Critical Paths**: 100% coverage
- **New Code**: 90%+ coverage required

### Running Coverage Reports

```bash
# Python
pytest --cov=src --cov-report=html
# Open htmlcov/index.html in browser

# JavaScript
npm test -- --coverage
# Open coverage/lcov-report/index.html in browser
```

## Mocking and Fixtures

### Mocking External Dependencies

```python
from unittest.mock import Mock, patch

def test_should_call_external_api():
    # Mock external API call
    with patch('src.services.api_client.call') as mock_call:
        mock_call.return_value = {"status": "ok"}
        
        result = service.process()
        
        assert result == {"status": "ok"}
        mock_call.assert_called_once()
```

### Test Fixtures

```python
import pytest

@pytest.fixture
def sample_metadata():
    return {
        "title": "Test Document",
        "author": "Test Author",
        "date": "2026-01-12"
    }

def test_should_validate_metadata(sample_metadata):
    validator = MetadataValidator()
    assert validator.validate(sample_metadata) is True
```

## Integration Test Setup

### Azure Resources for Testing

Use separate Azure resources for testing:
- Test storage accounts
- Test Cosmos DB accounts
- Test AI service instances

Configure via environment variables:
```bash
AZURE_STORAGE_ACCOUNT_TEST="sttestaccount"
AZURE_COSMOS_DB_TEST="cosmos-test"
```

### Test Data Cleanup

Always clean up test data:
```python
@pytest.fixture
def test_storage(request):
    # Setup
    storage = create_test_storage()
    
    # Provide to test
    yield storage
    
    # Cleanup
    storage.cleanup()
```

## Running Tests in CI/CD

### GitHub Actions Example

```yaml
- name: Run Tests
  run: |
    pip install -r requirements-test.txt
    pytest --cov=src --cov-report=xml

- name: Upload Coverage
  uses: codecov/codecov-action@v3
  with:
    file: ./coverage.xml
```

## Test Documentation

Each test should have:
- Clear name describing the scenario
- Docstring explaining the test purpose
- Comments for complex setup or assertions

```python
def test_should_reject_invalid_json_schema():
    """
    Verify that the validator rejects content that doesn't 
    conform to the defined JSON schema.
    
    Given: Invalid content structure
    When: Validation is performed
    Then: Validation fails with appropriate error
    """
    # Test implementation
    pass
```

## Performance Testing

For performance-critical components:
- Benchmark tests to track performance
- Load testing for scalability validation
- Profile slow tests and optimize

```python
import pytest

@pytest.mark.benchmark
def test_enrichment_performance(benchmark):
    result = benchmark(enrich_metadata, sample_content)
    assert result.duration < 1.0  # Max 1 second
```

## Security Testing

Include security-focused tests:
- Input validation tests
- Authentication/authorization tests
- SQL injection prevention
- XSS prevention
- Secrets leakage prevention

## Troubleshooting

### Tests Failing Locally
1. Check dependencies are installed
2. Verify environment variables
3. Ensure test data is available
4. Check for port conflicts

### Flaky Tests
1. Identify timing issues
2. Add appropriate waits
3. Mock external dependencies
4. Ensure test isolation

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Jest Documentation](https://jestjs.io/)
- [Testing Best Practices](https://testingjavascript.com/)
- [Azure Functions Testing](https://learn.microsoft.com/en-us/azure/azure-functions/functions-test-a-function)

---

Tests will be added as code is developed.
