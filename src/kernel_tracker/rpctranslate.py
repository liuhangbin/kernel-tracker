"""JSON-RPC translation layer.

Provides the @json_call decorator and the Translator class for
automatic parameter validation, type conversion, and response
serialization.
"""

import inspect
import json
import typing
from functools import wraps
from types import NoneType, UnionType

from django.http import JsonResponse

from kernel_tracker import models, processing, utils


class UnknownType(Exception):
    """A parameter type that is not supported by the translator."""


class ReportedError(Exception):
    """Base class for errors reported to users."""

    level = ""


class ValidateError(ReportedError):
    """Data does not conform to the required rules."""

    level = "system"


class RpcError(ReportedError):
    """User-supplied data could not be processed."""

    level = "user"


class RpcWarning(ReportedError):
    """User-supplied data caused a non-fatal warning."""

    level = "user"

    def __init__(self, *args, result=None):
        super().__init__(*args)
        self.result = result


class DataWrapper:
    """Wraps an object for RPC response with extra attributes.

    Usage: DataWrapper(commit, is_partial=True, downstream=[...])
    The extra kwargs are added to the serialized response.
    """

    def __init__(self, data, **kwargs):
        self.data = data
        self.extra = kwargs


class MultipleReturn(list):
    pass


class Translator:
    """Validates and converts JSON request data to match function signatures."""

    def __init__(self, f):
        self.sig = inspect.signature(f)
        self._preprocess()

    def _preprocess(self):
        self.mandatory = set()
        for k in self.sig.parameters:
            if self.sig.parameters[k].default == inspect.Parameter.empty:
                self.mandatory.add(k)

    def _commit_from_message(self, message, id):
        """Resolve a downstream commit message to its upstream counterpart."""

        class FakeCommit:
            pass

        commit = FakeCommit()
        commit.message = message
        searcher = processing.ReferenceSearcher(None)
        refs = searcher.find_refs(commit, searcher.re_mention)
        if not refs:
            raise RpcWarning(f"cannot find upstream reference in commit {id}")
        if len(refs) == 1:
            return refs[0]
        return MultipleReturn(refs)

    def translate_request(self, name, item, atype, in_list=False):
        """Convert a single JSON value to the expected Python type."""

        def assume_type(item_type):
            if type(item) is not item_type:
                raise ValidateError(f"parameter {name} has a wrong type")

        # Handle Optional[X] (Union[X, None])
        if typing.get_origin(atype) == UnionType:
            args = set(typing.get_args(atype))
            args.discard(NoneType)
            if len(args) == 1:
                atype = args.pop()

        if atype in (int, str, bool):
            assume_type(atype)
            return item

        if atype == models.Commit:
            if in_list and type(item) is dict:
                attrs = ("message", "id")
                keys = list(item.keys())
                for a in attrs:
                    if a not in item:
                        raise ValidateError(f"missing '{a}' attribute for commit")
                    keys.remove(a)
                if keys:
                    raise ValidateError(f"unknown commit attribute {keys[0]}")
                return self._commit_from_message(**item)
            assume_type(str)
            oid = utils.full_hash(item)
            if oid:
                try:
                    return (
                        models.Commit.objects.filter(oid=str(oid))
                        .prefetch_related("upstream")
                        .get()
                    )
                except models.Commit.DoesNotExist:
                    pass
            raise RpcError(f"commit {item} not found")

        if atype == models.Tree:
            assume_type(str)
            try:
                return models.Tree.objects.get(name=item)
            except models.Tree.DoesNotExist:
                raise RpcError(f"tree {item} does not exist")

        if hasattr(atype, "__origin__"):
            origin = atype.__origin__
            if issubclass(origin, list):
                assume_type(list)
                result = []
                warnings = []
                for i in item:
                    try:
                        r = self.translate_request(
                            name, i, atype.__args__[0], in_list=True
                        )
                        if type(r) is MultipleReturn:
                            result.extend(r)
                        elif r is not None:
                            result.append(r)
                    except RpcWarning as e:
                        warnings.append(str(e))
                if warnings:
                    raise RpcWarning(*warnings, result=result)
                return result

        raise UnknownType(f"unhandled request type {atype!s}")

    def process_request(self, data):
        """Process a JSON request, returning (args, config, warnings)."""
        config = {}
        warnings = []
        result = {}
        missing = self.mandatory.copy()
        for k in data:
            if k == "commit_with_subject":
                config[k] = True
                continue
            if k not in self.sig.parameters:
                raise ValidateError(f"unknown parameter {k}")
            try:
                missing.remove(k)
            except KeyError:
                pass
            try:
                result[k] = self.translate_request(
                    k, data[k], self.sig.parameters[k].annotation
                )
            except RpcWarning as e:
                warnings.extend(e.args)
                result[k] = e.result
        if missing:
            raise ValidateError(f"missing parameters: {', '.join(missing)}")
        return result, config, warnings

    def process_response(self, data, config):
        """Serialize a Python object to JSON-compatible data."""
        atype = type(data)
        if atype in (int, str, bool):
            return data
        if atype is list:
            return [self.process_response(d, config) for d in data]
        if atype is dict:
            return {k: self.process_response(v, config) for k, v in data.items()}

        extra = {}
        if atype == DataWrapper:
            extra = {k: self.process_response(v, config) for k, v in data.extra.items()}
            data = data.data
            atype = type(data)

        result = None
        if atype == models.Commit:
            result = {
                "commit": data.oid,
                "merge": data.is_merge,
                "trees": data.tree_names(),
            }
            if "commit_with_subject" in config:
                result["subject"] = data.subject
        elif atype == models.Tree:
            result = {
                "name": data.name,
                "url": data.remote_url(),
                "type": data.get_kind_display(),
            }
            if data.origin:
                result["origin"] = data.origin.version
        elif atype == models.Series:
            result = {
                "head": data.head,
                "link": data.link,
                "name": data.name,
            }

        if not result:
            raise UnknownType(f"unhandled response type {atype!s}")
        result.update(extra)
        return result


def json_call(f):
    """Decorator that adds a JSON request handler to an RPC function.

    The decorated function gains a .json_wrapper attribute that accepts
    a Django HttpRequest and returns a JsonResponse.
    """
    translator = Translator(f)

    @wraps(f)
    def wrapper(request):
        try:
            try:
                data = json.loads(request.body.decode("utf-8"))
            except json.JSONDecodeError as e:
                raise ValidateError(f"wrong json supplied: {e}") from None
            data, config, warnings = translator.process_request(data)
            return JsonResponse(
                {
                    "result": translator.process_response(f(**data), config),
                    "warnings": warnings,
                    "vanilla": models.Tree.objects.get(is_vanilla=True).name,
                }
            )
        except ReportedError as e:
            return JsonResponse({"error": str(e), "type": e.level})

    f.json_wrapper = wrapper
    return f


def check_regex(f):
    """Decorator that catches database regex errors and returns RPC errors."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            if not utils.is_db_regex_exception(e):
                raise
            raise RpcError("Invalid regex specified.")

    return wrapper
