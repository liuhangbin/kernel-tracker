# Test: Verify commits were processed
result=$($manage shell -c "from kernel_tracker.models import Commit; print(Commit.objects.count())")
if [[ "$result" -lt "1" ]]; then
    echo "Expected at least 1 commit, got $result"
    exit 1
fi
