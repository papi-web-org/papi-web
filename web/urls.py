from litestar.contrib.htmx.request import HTMXRequest


def index_url(request: HTMXRequest) -> str:
    return request.app.route_reverse('index')


def event_url(request: HTMXRequest, event_uniq_id: str) -> str:
    return request.app.route_reverse('render-event', event_uniq_id=event_uniq_id)


def login_url(request: HTMXRequest, event_uniq_id: str, screen_id: str) -> str:
    return request.app.route_reverse('login', event_uniq_id=event_uniq_id, screen_id=screen_id)


def screen_url(request: HTMXRequest, event_uniq_id: str, screen_id: str) -> str:
    return request.app.route_reverse('render-screen', event_uniq_id=event_uniq_id, screen_id=screen_id)


def rotator_url(request: HTMXRequest, event_uniq_id: str, rotator_id: str) -> str:
    return request.app.route_reverse(
        'render-rotator', event_uniq_id=event_uniq_id, rotator_id=rotator_id)


def rotator_screen_url(request: HTMXRequest, event_uniq_id: str, rotator_id: str, rotator_screen_index: int) -> str:
    return request.app.route_reverse(
        'render-rotator-screen', event_uniq_id=event_uniq_id, rotator_id=rotator_id,
        rotator_screen_index=rotator_screen_index)


def download_event_url(request: HTMXRequest, event_uniq_id: str) -> str:
    return request.app.route_reverse(
        'download-event', event_uniq_id=event_uniq_id)


def download_tournament_url(request: HTMXRequest, event_uniq_id: str, tournament_uniq_id: str) -> str:
    return request.app.route_reverse(
        'download-tournament', event_uniq_id=event_uniq_id, tournament_uniq_id=tournament_uniq_id)
