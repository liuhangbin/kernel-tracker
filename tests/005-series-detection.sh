# Test: Verify series detection works (placeholder - needs multi-commit series)
# For now just verify the Series model is accessible
result=$($manage shell -c "from kernel_tracker.models import Series; print(Series.objects.count())")
if [[ "$result" -lt "0" ]]; then
    echo "Expected non-negative series count, got $result"
    exit 1
fi
