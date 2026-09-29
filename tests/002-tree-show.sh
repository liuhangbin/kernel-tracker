# Test: List configured trees
result=$($manage tree show 2>&1)
if ! echo "$result" | grep -q "linux"; then
    echo "Expected 'linux' in tree list, got: $result"
    exit 1
fi
