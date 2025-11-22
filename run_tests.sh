#!/bin/bash
# Test runner for semantika

echo "========================================="
echo " Semantika Unit Tests"
echo "========================================="
echo ""

# Check if pytest is installed
if ! python3 -m pytest --version > /dev/null 2>&1; then
    echo "❌ pytest not found. Installing test dependencies..."
    pip3 install pytest pytest-asyncio pytest-cov
    echo ""
fi

# Run tests with coverage
echo "Running tests..."
echo ""

python3 -m pytest tests/ \
    -v \
    --tb=short \
    --cov=utils \
    --cov=sources \
    --cov-report=term-missing \
    --cov-report=html

echo ""
echo "========================================="
echo " Test Results"
echo "========================================="
echo ""
echo "Coverage report generated in: htmlcov/index.html"
echo ""
