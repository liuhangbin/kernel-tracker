# Test: Verify commits are associated with the correct tree
result=$($manage shell -c "
from kernel_tracker.models import Commit, Tree
tree = Tree.objects.get(name='linux')
commits = Commit.objects.filter(trees=tree)
print(commits.count())
")
if [[ "$result" -lt "1" ]]; then
    echo "Expected commits in linux tree, got $result"
    exit 1
fi
