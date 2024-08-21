from litestar.contrib.htmx.request import HTMXRequest


def index_url(request: HTMXRequest) -> str:
    return request.app.route_reverse('index')

