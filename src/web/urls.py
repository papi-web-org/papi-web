from typing import Any
from urllib.parse import urlencode

from litestar.plugins.htmx import HTMXRequest

from web.tunnel import request_is_tunnelled


def build_get_url(
    base_url: str,
    endpoint_path: str,
    params: dict[str, Any] | None = None,
) -> str:
    url = base_url[:-1] if base_url.endswith('/') else base_url
    url += endpoint_path
    if params:
        url += '?' + urlencode(params)
    return url


def build_internal_get_url(
    request: HTMXRequest,
    route_name: str,
    route_params: dict[str, Any] | None = None,
    query_params: dict[str, Any] | None = None,
) -> str:
    return build_get_url(
        get_base_url(request),
        request.app.route_reverse(route_name, **(route_params or {})),
        query_params,
    )


def get_base_url(request: HTMXRequest) -> str:
    scheme = request.url.scheme
    if request_is_tunnelled(request.scope):
        # The tunnel terminates TLS and reaches the server over loopback, so
        # the scheme on the connection is not the one the caller used.
        scheme = request.headers.get('x-forwarded-proto') or scheme
    port = '' if request.url.port in (80, 443, None) else f':{request.url.port}'
    return f'{scheme}://{request.url.hostname}{port}'


def index_url(request: HTMXRequest) -> str:
    return request.app.route_reverse('index')


def admin_event_url(
    request: HTMXRequest,
    event_uniq_id: str,
) -> str:
    return request.app.route_reverse('admin-event', event_uniq_id=event_uniq_id)


def admin_event_players_url(
    request: HTMXRequest,
    event_uniq_id: str,
) -> str:
    return request.app.route_reverse(
        'admin-event-players-tab', event_uniq_id=event_uniq_id
    )


def admin_event_tournaments_url(
    request: HTMXRequest,
    event_uniq_id: str,
) -> str:
    return request.app.route_reverse(
        'admin-event-tournaments-tab', event_uniq_id=event_uniq_id
    )


def admin_event_pairings_url(
    request: HTMXRequest,
    event_uniq_id: str,
    tournament_id: int,
) -> str:
    return request.app.route_reverse(
        'admin-event-pairings-tab',
        event_uniq_id=event_uniq_id,
        tournament_id=tournament_id,
    )


def data_transfer_item_url(
    request: HTMXRequest,
    event_uniq_id: str,
) -> str:
    return request.app.route_reverse(
        'event-data-transfer-item', event_uniq_id=event_uniq_id
    )
