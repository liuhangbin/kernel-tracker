"""Cursor-based pagination for querysets."""

from django.utils.http import urlencode


class Pages:
    """Splits a queryset into pages using cursor-based pagination.

    Returns pages starting after a given PK. To get the next page,
    pass the last returned PK as next_pk.
    """

    def __init__(self, query, next_pk=None, limit=50, desc=False):
        self.limit = limit
        if next_pk and query is not None:
            if desc:
                query = query.filter(pk__lt=next_pk)
            else:
                query = query.filter(pk__gt=next_pk)
        if query is not None:
            if not next_pk:
                query = query.filter(pk__gte=0)
            self.data = list(query[:limit])
        else:
            self.data = ()

    def __iter__(self):
        return iter(self.data)

    def has_next(self):
        return len(self.data) == self.limit


class RequestPages(Pages):
    """Extends Pages with Django request integration.

    Reads next_pk and page number from request GET parameters.
    """

    def __init__(self, request, query, limit=50, desc=False, keys=("next", "page")):
        self.request = request
        self.keys = keys
        next_pk = request.GET.get(keys[0])
        if next_pk is not None:
            try:
                next_pk = int(next_pk)
                if next_pk <= 0:
                    next_pk = None
            except ValueError:
                next_pk = None
        try:
            self._page = int(request.GET.get(keys[1], 0))
        except ValueError:
            next_pk = None
        if self._page < 0:
            next_pk = None
        if not next_pk or query is None:
            self._page = 1
        super().__init__(query, next_pk, limit, desc)

    def page(self):
        if not self._page:
            return "unknown"
        return self._page

    def url(self):
        parms = self.request.GET.dict()
        if self._page:
            parms.update(
                ((self.keys[0], self.data[-1].pk), (self.keys[1], self._page + 1))
            )
        else:
            parms.update(((self.keys[0], self.data[-1].pk),))
            try:
                del parms[self.keys[1]]
            except KeyError:
                pass
        return urlencode(parms)
