# Test: Add vanilla upstream tree and verify it appears
branch vanilla
$manage tree add -u -V linux $repourl#vanilla
update
# Verify the tree was added (check via Django shell)
result=$($manage shell -c "from kernel_tracker.models import Tree; print(Tree.objects.filter(is_vanilla=True).count())")
if [[ "$result" != "1" ]]; then
    echo "Expected 1 vanilla tree, got $result"
    exit 1
fi
