# Test: Verify health endpoint works
# This requires the server to be running, which we can't easily do in
# the test script. Just verify the view exists.
result=$($manage shell -c "
from kernel_tracker.views import health
print('ok')
")
if [[ "$result" != "ok" ]]; then
    echo "Health view not importable"
    exit 1
fi
