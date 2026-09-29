"""Management command for git tree manipulation.

Usage:
  manage.py tree add [-u|-d] [-V] name url[#branch]
  manage.py tree change name [-u url] [-n new-name]
  manage.py tree delete name
  manage.py tree alias name [-a url] [-r url]
  manage.py tree show [-u|-d]
"""

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.utils import IntegrityError

from kernel_tracker import models, processing, utils
from kernel_tracker.repository import repository


class Command(BaseCommand):
    help = "Git tree manipulation. Adds, changes, deletes, or lists git trees."
    missing_args_message = "please specify a subcommand"

    def add_arguments(self, parser):
        class SubParser(CommandParser):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)

        subparsers = parser.add_subparsers(
            title="Git tree commands", parser_class=SubParser
        )

        parser_add = subparsers.add_parser("add", help="add a new git tree")
        parser_add.set_defaults(func=self.handle_add)
        self.add_arguments_add(parser_add)

        parser_change = subparsers.add_parser(
            "change", help="change a tracked git tree"
        )
        parser_change.set_defaults(func=self.handle_change)
        self.add_arguments_change(parser_change)

        parser_delete = subparsers.add_parser(
            "delete",
            aliases=("rm", "remove"),
            help="delete a tracked git tree and its git remote",
        )
        parser_delete.set_defaults(func=self.handle_delete)
        self.add_arguments_delete(parser_delete)

        parser_alias = subparsers.add_parser(
            "alias", help="manage URL aliases of a tracked git tree"
        )
        parser_alias.set_defaults(func=self.handle_alias)
        self.add_arguments_alias(parser_alias)

        parser_show = subparsers.add_parser(
            "show", aliases=("ls", "list"), help="list tracked git trees"
        )
        parser_show.set_defaults(func=self.handle_show)
        self.add_arguments_show(parser_show)

    def add_arguments_add(self, parser):
        for k, v in models.Tree.TREE_KINDS:
            parser.add_argument(
                f"-{k}",
                f"--{v}",
                action="store_true",
                default=False,
                help=f"the repository is an {v} tree",
            )
        parser.add_argument(
            "-V",
            "--vanilla",
            action="store_true",
            default=False,
            help="mark the repository as the vanilla tree",
        )
        parser.add_argument("name", help="repository name")
        parser.add_argument("url", help="repository URL (or URL#branch)")

    def add_arguments_change(self, parser):
        parser.add_argument("name", help="repository name")
        parser.add_argument("-u", "--url", help="new repository URL (or URL#branch)")
        parser.add_argument("-n", "--new-name", help="new repository name")

    def add_arguments_delete(self, parser):
        parser.add_argument("name", help="repository name")

    def add_arguments_alias(self, parser):
        parser.add_argument("name", help="repository name")
        parser.add_argument("-a", "--add", help="add an alias URL (or URL#branch)")
        parser.add_argument(
            "-r", "--remove", help="remove an alias URL (or URL#branch)"
        )

    def add_arguments_show(self, parser):
        for k, v in models.Tree.TREE_KINDS:
            parser.add_argument(
                f"-{k}",
                f"--{v}",
                action="store_true",
                default=False,
                help=f"list {v} repositories",
            )

    def handle(self, **options):
        options["func"](**options)

    def split_url(self, url):
        url_parts = url.split("#")
        if len(url_parts) > 2:
            raise CommandError("only one branch can be specified")
        if len(url_parts) < 2:
            url_parts.append("main")
        return utils.normalize_git_url(url_parts[0]), url_parts[1]

    def handle_add(self, **options):
        if processing.check_running():
            raise CommandError("a cron job is currently running, cannot add a tree")
        kind = None
        for k, v in models.Tree.TREE_KINDS:
            if not options[v]:
                continue
            if kind:
                raise CommandError("repository can only be of one type")
            kind = k
        if not kind:
            raise CommandError("repository type must be specified")

        if options["vanilla"]:
            if models.Tree.objects.filter(is_vanilla=True).exists():
                raise CommandError("a vanilla tree has already been added")
        else:
            if not models.Tree.objects.all().exists():
                raise CommandError("the first added tree must be vanilla")

        url, branch = self.split_url(options["url"])
        tree = models.Tree(
            name=options["name"],
            url=url,
            branch=branch,
            kind=kind,
            is_vanilla=options["vanilla"],
        )
        try:
            tree.save()
        except IntegrityError:
            raise CommandError("a tree with the given name already exists")
        repository.remotes.create(tree.name, url)

    def handle_change(self, **options):
        if processing.check_running():
            raise CommandError(
                "a cron job is currently running, cannot change the tree"
            )
        try:
            tree = models.Tree.objects.get(name=options["name"])
        except models.Tree.DoesNotExist:
            raise CommandError("the tree with the given name does not exist")
        if options["url"]:
            tree.url, tree.branch = self.split_url(options["url"])
        if options["new_name"]:
            old_name = tree.name
            tree.name = options["new_name"]
        try:
            tree.save()
        except IntegrityError:
            raise CommandError("a tree with the given name already exists")
        if options["new_name"]:
            repository.remotes.rename(old_name, tree.name)
        if options["url"]:
            repository.remotes.set_url(tree.name, tree.url)

    def handle_delete(self, **options):
        if processing.check_running():
            raise CommandError("a cron job is currently running, cannot delete a tree")
        try:
            tree = models.Tree.objects.get(name=options["name"])
        except models.Tree.DoesNotExist:
            raise CommandError("the tree with the given name does not exist")

        # Other trees are compared against the vanilla tree, so removing it
        # while anything else remains would break the next `cron update`.
        if tree.is_vanilla and models.Tree.objects.exclude(pk=tree.pk).exists():
            raise CommandError(
                f"'{tree.name}' is the vanilla tree and other trees still "
                f"depend on it; delete those first"
            )

        commits = models.Commit.objects.filter(trees=tree).count()
        self.stdout.write(
            f"Tree '{tree.name}' ({tree.get_kind_display()}) is referenced by "
            f"{commits} commit(s). The tree and its git remote will be removed; "
            f"the commits themselves are kept."
        )
        try:
            answer = input(f"Type '{tree.name}' to confirm: ")
        except EOFError:
            raise CommandError("aborted, no input available")
        if answer != tree.name:
            raise CommandError("aborted, name did not match")

        tree.delete()
        if tree.name in repository.remotes.names():
            repository.remotes.delete(tree.name)
        self.stdout.write(f"Deleted tree '{tree.name}'.")

    def handle_alias(self, **options):
        try:
            tree = models.Tree.objects.get(name=options["name"])
        except models.Tree.DoesNotExist:
            raise CommandError("the tree with the given name does not exist")
        if options["add"]:
            url, branch = self.split_url(options["add"])
            try:
                alias = models.TreeAlias(tree=tree, url=url, branch=branch)
                alias.save()
            except IntegrityError:
                raise CommandError("an alias with the given URL#branch already exists")
        if options["remove"]:
            url, branch = self.split_url(options["remove"])
            tree.aliases.filter(url=url, branch=branch).delete()

    def handle_show(self, **options):
        kinds = []
        for k, v in models.Tree.TREE_KINDS:
            if options[v]:
                kinds.append(k)
        trees = models.Tree.objects.all()
        if kinds:
            trees = trees.filter(kind__in=kinds)
        parms = {"kind_len": 0, "name_len": 0}
        for t in trees:
            parms["kind_len"] = max(parms["kind_len"], len(t.get_kind_display()))
            parms["name_len"] = max(parms["name_len"], len(t.name))
        for t in trees:
            parms["kind"] = t.get_kind_display()
            parms["name"] = t.name
            parms["url"] = t.remote_url()
            parms["flag"] = "*" if t.is_vanilla else " "
            print("[{kind:{kind_len}}]{flag} {name:{name_len}} {url}".format(**parms))
            fill = " " * (parms["kind_len"] + parms["name_len"] + 4)
            for a in t.aliases.all():
                print(f"{fill} alias: {a.remote_url()}")
